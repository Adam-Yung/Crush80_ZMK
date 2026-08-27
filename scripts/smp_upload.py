#!/usr/bin/env python3
"""
Raw SMP (Simple Management Protocol) firmware upload for Crush80.

This script implements the SMP serial transport from scratch, giving us
complete control over timing, chunk sizes, and retry behavior. Unlike the
Go mcumgr tool, we can:
  - Send very small chunks (64-256 bytes)
  - Wait for ACK before sending next chunk
  - Retry individual chunks on timeout
  - Show exact byte-level progress

SMP Serial framing:
  - Packet header: 0x06 0x09  (initial frame)
  - Fragment header: 0x04 0x14 (continuation frames)
  - Body is base64-encoded
  - Lines terminated with 0x0A (newline)
  - Max frame size: 128 bytes (per Zephyr default)

SMP packet structure (CBOR over NMP):
  - 8-byte header: op, flags, len(2), group(2), seq, id
  - CBOR payload

Image upload uses group=1 (IMAGE), id=1 (UPLOAD).
"""

import sys
import os
import time
import struct
import base64
import hashlib
import serial
import cbor2  # pip install cbor2

# SMP constants
SMP_OP_WRITE = 2
SMP_GROUP_IMAGE = 1
SMP_ID_UPLOAD = 1

# Serial framing
FRAME_HDR_PKT = bytes([0x06, 0x09])
FRAME_HDR_FRAG = bytes([0x04, 0x14])
FRAME_NEWLINE = b'\n'
MAX_FRAME_LINE = 127  # max base64 payload per line (128 - header byte overhead)

CHUNK_SIZE = 192  # bytes of image data per SMP request (conservative)
TIMEOUT_SEC = 8   # per-chunk timeout
MAX_RETRIES_PER_CHUNK = 5
MAX_TOTAL_STALLS = 30  # give up after this many total stalled chunks


def crc16_mcumgr(data: bytes) -> int:
    """CRC-16/XMODEM used by mcumgr serial framing."""
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


def build_smp_header(op, flags, length, group, seq, cmd_id):
    """Build 8-byte SMP header."""
    return struct.pack('>BBHHBBH', op, flags, length, group, seq, cmd_id, 0)[:8]


def build_upload_request(image_data: bytes, offset: int, image_len: int, seq: int) -> bytes:
    """Build a complete SMP image upload request."""
    chunk_end = min(offset + CHUNK_SIZE, image_len)
    chunk = image_data[offset:chunk_end]

    payload = {
        "off": offset,
        "data": chunk,
        "len": image_len,
    }
    if offset == 0:
        sha = hashlib.sha256(image_data).digest()
        payload["sha"] = sha

    cbor_payload = cbor2.dumps(payload)

    header = struct.pack('>BBHHBB',
                         SMP_OP_WRITE,  # op
                         0,             # flags
                         len(cbor_payload),  # length
                         SMP_GROUP_IMAGE,    # group
                         seq & 0xFF,         # sequence
                         SMP_ID_UPLOAD)      # command id
    return header + cbor_payload


def encode_smp_serial(packet: bytes) -> bytes:
    """Encode an SMP packet into serial frames (base64 + framing)."""
    pkt_len = len(packet)
    # The "body" is: 2-byte length (big-endian) + packet data
    body = struct.pack('>H', pkt_len) + packet
    # Add CRC16
    crc = crc16_mcumgr(body)
    body += struct.pack('>H', crc)

    # Base64 encode
    b64 = base64.b64encode(body)

    # Split into frames of max 93 base64 chars each
    # (128 - 2 header - 1 newline - some margin = ~93 usable)
    max_b64_per_frame = 93
    frames = []
    pos = 0
    first = True
    while pos < len(b64):
        chunk = b64[pos:pos + max_b64_per_frame]
        if first:
            frames.append(FRAME_HDR_PKT + chunk + FRAME_NEWLINE)
            first = False
        else:
            frames.append(FRAME_HDR_FRAG + chunk + FRAME_NEWLINE)
        pos += max_b64_per_frame

    return b''.join(frames)


def decode_smp_serial_response(raw: bytes) -> bytes | None:
    """Decode SMP serial response frames back into the SMP packet."""
    lines = raw.split(b'\n')
    b64_data = b''
    for line in lines:
        line = line.strip()
        if len(line) < 2:
            continue
        if line[:2] == FRAME_HDR_PKT:
            b64_data = line[2:]
        elif line[:2] == FRAME_HDR_FRAG:
            b64_data += line[2:]

    if not b64_data:
        return None

    try:
        decoded = base64.b64decode(b64_data)
    except Exception:
        return None

    if len(decoded) < 4:
        return None

    pkt_len = struct.unpack('>H', decoded[:2])[0]
    body = decoded[2:2 + pkt_len]
    # Verify CRC
    expected_crc = struct.unpack('>H', decoded[2 + pkt_len:4 + pkt_len])[0]
    actual_crc = crc16_mcumgr(decoded[:2 + pkt_len])
    if actual_crc != expected_crc:
        return None

    return body


def parse_upload_response(smp_packet: bytes) -> dict | None:
    """Parse SMP upload response to get the next offset."""
    if len(smp_packet) < 8:
        return None
    header = smp_packet[:8]
    cbor_data = smp_packet[8:]
    try:
        response = cbor2.loads(cbor_data)
        return response
    except Exception:
        return None


def progress_bar(current, total, width=40):
    """Generate a text progress bar."""
    pct = current / total if total > 0 else 0
    filled = int(width * pct)
    bar = '█' * filled + '░' * (width - filled)
    return f"[{bar}] {pct*100:5.1f}%  ({current:,}/{total:,} bytes)"


def upload(port_path: str, image_path: str):
    """Main upload function with per-chunk retry and progress tracking."""
    with open(image_path, 'rb') as f:
        image_data = f.read()
    image_len = len(image_data)

    print(f"  Image: {os.path.basename(image_path)}")
    print(f"  Size:  {image_len:,} bytes")
    print(f"  Chunk: {CHUNK_SIZE} bytes")
    print(f"  Port:  {port_path}")
    print()

    ser = serial.Serial(port_path, 115200, timeout=1)
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    time.sleep(0.5)

    offset = 0
    seq = 0
    total_stalls = 0
    best_offset = 0

    while offset < image_len:
        # Build and send request
        request = build_upload_request(image_data, offset, image_len, seq)
        frames = encode_smp_serial(request)

        retries = 0
        success = False

        while retries < MAX_RETRIES_PER_CHUNK:
            ser.reset_input_buffer()
            ser.write(frames)
            ser.flush()

            # Wait for response
            response_raw = b''
            deadline = time.time() + TIMEOUT_SEC
            while time.time() < deadline:
                chunk = ser.read(256)
                if chunk:
                    response_raw += chunk
                    if b'\n' in response_raw:
                        # Try to decode — might have full response
                        smp_resp = decode_smp_serial_response(response_raw)
                        if smp_resp is not None:
                            resp = parse_upload_response(smp_resp)
                            if resp is not None:
                                success = True
                                break
                time.sleep(0.05)

            if success:
                break

            retries += 1
            total_stalls += 1
            if retries < MAX_RETRIES_PER_CHUNK:
                time.sleep(0.5)

        if not success:
            print(f"\n  ✗ Chunk at offset {offset} failed after {MAX_RETRIES_PER_CHUNK} retries.")
            print(f"    Best progress: {progress_bar(best_offset, image_len)}")
            if total_stalls >= MAX_TOTAL_STALLS:
                print(f"  ✗ Too many stalls ({total_stalls}). Giving up.")
                ser.close()
                return False
            # Try to continue from where we were
            time.sleep(1)
            ser.reset_input_buffer()
            continue

        # Parse response for next offset
        if resp and "off" in resp:
            new_offset = resp["off"]
            if new_offset > offset:
                offset = new_offset
            elif new_offset == offset:
                # Device didn't advance — retry same chunk
                total_stalls += 1
                time.sleep(0.3)
                continue
            else:
                # Device wants us to go back?
                offset = new_offset
        else:
            # No offset in response — assume our chunk was accepted
            offset += CHUNK_SIZE

        if offset > best_offset:
            best_offset = offset

        seq = (seq + 1) & 0xFF

        # Print progress
        bar = progress_bar(offset, image_len)
        stall_indicator = f" (stalls: {total_stalls})" if total_stalls > 0 else ""
        sys.stdout.write(f"\r  {bar}{stall_indicator}")
        sys.stdout.flush()

        if total_stalls >= MAX_TOTAL_STALLS:
            print(f"\n  ✗ Too many total stalls ({total_stalls}).")
            ser.close()
            return False

    print(f"\n  ✓ Upload complete! {image_len:,} bytes transferred.")
    ser.close()
    return True


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <port> <image.bin>")
        sys.exit(1)

    port_path = sys.argv[1]
    image_path = sys.argv[2]

    if not os.path.exists(image_path):
        print(f"ERROR: Image not found: {image_path}")
        sys.exit(1)

    try:
        import cbor2  # noqa: F811
    except ImportError:
        print("  Installing cbor2...")
        os.system(f"{sys.executable} -m pip install cbor2 -q")
        import cbor2  # noqa: F811

    try:
        import serial  # noqa: F811
    except ImportError:
        print("  Installing pyserial...")
        os.system(f"{sys.executable} -m pip install pyserial -q")
        import serial  # noqa: F811

    ok = upload(port_path, image_path)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
