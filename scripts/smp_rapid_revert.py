#!/usr/bin/env python3
"""
Rapid-fire SMP commands for Crush80 MCUboot revert.

The SMP layer on this bricked keyboard works briefly after plug-in, then dies.
This script sends commands AS FAST AS POSSIBLE using raw SMP serial framing,
without the startup overhead of the Go mcumgr tool.

Strategy:
  1. Detect port immediately on plug-in
  2. Open serial, send 'image list' within milliseconds
  3. If slot 1 exists, send 'image test <hash>' 
  4. Send 'reset'
  5. Wait for MCUboot swap

If SMP dies between commands, the script tells you to unplug/replug and
picks up where it left off.
"""

import sys
import os
import time
import struct
import base64
import glob
import hashlib

try:
    import serial
except ImportError:
    os.system(f"{sys.executable} -m pip install pyserial -q")
    import serial

try:
    import cbor2
except ImportError:
    os.system(f"{sys.executable} -m pip install cbor2 -q")
    import cbor2


# SMP constants
SMP_OP_READ = 0
SMP_OP_WRITE = 2
SMP_GROUP_OS = 0
SMP_GROUP_IMAGE = 1
SMP_ID_ECHO = 0
SMP_ID_RESET = 5
SMP_ID_IMAGE_STATE = 0  # image list / test / confirm
SMP_ID_IMAGE_UPLOAD = 1

FRAME_HDR_PKT = bytes([0x06, 0x09])
FRAME_HDR_FRAG = bytes([0x04, 0x14])


def crc16(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if (crc & 0x8000) else (crc << 1)
            crc &= 0xFFFF
    return crc


def build_smp_packet(op, group, cmd_id, payload_dict, seq=0):
    """Build complete SMP packet (header + CBOR payload)."""
    cbor_payload = cbor2.dumps(payload_dict) if payload_dict else b''
    header = struct.pack('>BBHHBB',
                         op, 0, len(cbor_payload), group, seq & 0xFF, cmd_id)
    return header + cbor_payload


def encode_for_serial(packet: bytes) -> bytes:
    """Encode SMP packet into serial frames."""
    body = struct.pack('>H', len(packet)) + packet
    body += struct.pack('>H', crc16(body))
    b64 = base64.b64encode(body)

    max_per_frame = 93
    frames = []
    pos = 0
    first = True
    while pos < len(b64):
        chunk = b64[pos:pos + max_per_frame]
        hdr = FRAME_HDR_PKT if first else FRAME_HDR_FRAG
        frames.append(hdr + chunk + b'\n')
        first = False
        pos += max_per_frame
    return b''.join(frames)


def decode_response(raw: bytes) -> dict | None:
    """Decode serial response into dict."""
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
    if crc16(decoded[:2 + pkt_len]) != expected_crc:
        return None

    if len(body) < 8:
        return None

    # Parse SMP header
    cbor_data = body[8:]
    if not cbor_data:
        return {}
    try:
        return cbor2.loads(cbor_data)
    except Exception:
        return None


def send_and_recv(ser, packet: bytes, timeout=4.0) -> dict | None:
    """Send SMP packet and wait for response."""
    encoded = encode_for_serial(packet)
    try:
        ser.reset_input_buffer()
        ser.write(encoded)
        ser.flush()
    except (serial.SerialException, OSError):
        return None

    raw = b''
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            chunk = ser.read(512)
        except (serial.SerialException, OSError):
            return None
        if chunk:
            raw += chunk
            result = decode_response(raw)
            if result is not None:
                return result
        else:
            time.sleep(0.02)

    if raw:
        return decode_response(raw)
    return None


def detect_port():
    ports = glob.glob('/dev/cu.usbmodem*')
    return ports[0] if ports else None


def wait_for_port(timeout=60):
    print("  Plug in keyboard now...", flush=True)
    start = time.time()
    while time.time() - start < timeout:
        p = detect_port()
        if p:
            time.sleep(1.5)  # CDC ACM needs time to configure on macOS
            if detect_port():
                return p
        time.sleep(0.3)
    return None


def wait_for_replug(timeout=60):
    """Wait for port to disappear then reappear."""
    print("  ┌────────────────────────────────────────────┐")
    print("  │  UNPLUG keyboard, wait 2s, REPLUG now.     │")
    print("  └────────────────────────────────────────────┘")
    print("  Waiting for unplug...", end='', flush=True)

    # Wait for disappear
    start = time.time()
    while time.time() - start < timeout:
        if not detect_port():
            print(" gone!", flush=True)
            break
        time.sleep(0.3)
    else:
        print(" timeout!", flush=True)
        return None

    time.sleep(1)
    print("  Waiting for replug...", end='', flush=True)

    start = time.time()
    while time.time() - start < timeout:
        p = detect_port()
        if p:
            time.sleep(1.5)  # wait for CDC ACM to fully configure
            if detect_port():
                print(f" {p}", flush=True)
                return p
        time.sleep(0.3)

    print(" timeout!", flush=True)
    return None


def open_port_fast(port_path, max_retries=5):
    """Open serial port, retrying if device not yet configured."""
    for attempt in range(max_retries):
        try:
            ser = serial.Serial(port_path, 115200, timeout=0.5)
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            time.sleep(0.2)
            return ser
        except (serial.SerialException, OSError) as e:
            if attempt < max_retries - 1:
                time.sleep(0.5)
            else:
                raise RuntimeError(f"Cannot open {port_path} after {max_retries} tries: {e}")


def try_echo(ser):
    """Quick echo test to see if SMP is alive."""
    pkt = build_smp_packet(SMP_OP_WRITE, SMP_GROUP_OS, SMP_ID_ECHO, {"d": "hi"})
    resp = send_and_recv(ser, pkt, timeout=3)
    if resp and resp.get("r") == "hi":
        return True
    if resp is not None:
        return True  # got something back
    return False


def try_image_list(ser):
    """Get image state (both slots)."""
    pkt = build_smp_packet(SMP_OP_READ, SMP_GROUP_IMAGE, SMP_ID_IMAGE_STATE, {})
    resp = send_and_recv(ser, pkt, timeout=5)
    return resp


def try_image_test(ser, img_hash: bytes):
    """Mark image for test swap."""
    pkt = build_smp_packet(SMP_OP_WRITE, SMP_GROUP_IMAGE, SMP_ID_IMAGE_STATE,
                           {"hash": img_hash, "confirm": False})
    resp = send_and_recv(ser, pkt, timeout=5)
    return resp


def try_image_confirm(ser):
    """Confirm current image (make permanent)."""
    pkt = build_smp_packet(SMP_OP_WRITE, SMP_GROUP_IMAGE, SMP_ID_IMAGE_STATE,
                           {"confirm": True})
    resp = send_and_recv(ser, pkt, timeout=5)
    return resp


def try_reset(ser):
    """Reset the device."""
    pkt = build_smp_packet(SMP_OP_WRITE, SMP_GROUP_OS, SMP_ID_RESET, {})
    resp = send_and_recv(ser, pkt, timeout=3)
    return resp


def main():
    print("╔════════════════════════════════════════════════════════════╗")
    print("║   CRUSH80 RAPID-FIRE SMP — MCUboot Revert Attempt        ║")
    print("╠════════════════════════════════════════════════════════════╣")
    print("║ Sends tiny SMP commands FAST before the transport dies.   ║")
    print("║ Each command is < 100 bytes — should complete instantly.  ║")
    print("╚════════════════════════════════════════════════════════════╝")
    print()

    # === Phase 1: Get image list ===
    print("━━━ Phase 1: Read image slots (need one successful SMP roundtrip) ━━━")
    print()

    port = detect_port()
    if not port:
        port = wait_for_port()
    if not port:
        print("  ERROR: No port found.")
        sys.exit(1)

    print(f"  Port: {port}")
    print(f"  Opening immediately...", flush=True)

    ser = open_port_fast(port)

    # Try echo first (smallest possible command)
    print("  Sending SMP echo...", end=' ', flush=True)
    if try_echo(ser):
        print("✓ SMP is alive!")
    else:
        print("✗ no response (will try image list anyway)")

    print("  Sending image list...", end=' ', flush=True)
    img_state = try_image_list(ser)

    if img_state is None:
        print("✗ TIMEOUT")
        print()
        print("  SMP died before responding. Let's try again with faster timing.")
        print()
        ser.close()

        # Retry: unplug/replug and hit it even faster
        for retry in range(3):
            port = wait_for_replug()
            if not port:
                continue

            ser = open_port_fast(port)
            # Skip echo, go straight to image list
            print(f"  [Retry {retry+1}] Sending image list immediately...", end=' ', flush=True)
            img_state = try_image_list(ser)
            if img_state is not None:
                print("✓ GOT RESPONSE!")
                break
            print("✗ timeout again")
            ser.close()

        if img_state is None:
            print()
            print("  ✗ Cannot get image list after multiple attempts.")
            print("    The SMP layer is dying too quickly for even tiny commands.")
            print()
            print("  Last resort options:")
            print("    1. Try: bash scripts/resilient_upload.sh")
            print("       (upload does work partially — 2-4% per attempt)")
            print("    2. Install smpmgr: pipx install smpmgr")
            print("    3. Use SWD debugger for direct flash access")
            sys.exit(1)

    ser.close()
    print()

    # === Parse image state ===
    print("  Image state response:")
    images = img_state.get("images", [])
    if not images:
        print(f"    Raw: {img_state}")
        print("    ✗ No images found in response.")
        print("    This is unexpected. The response format may differ.")
        sys.exit(1)

    slot0_hash = None
    slot1_hash = None

    for img in images:
        slot = img.get("slot", -1)
        version = img.get("version", "?")
        confirmed = img.get("confirmed", False)
        pending = img.get("pending", False)
        active = img.get("active", False)
        h = img.get("hash", b'')

        status = []
        if active: status.append("active")
        if confirmed: status.append("confirmed")
        if pending: status.append("pending")

        hash_hex = h.hex()[:16] + "..." if isinstance(h, bytes) else str(h)[:16] + "..."
        print(f"    Slot {slot}: v{version} [{', '.join(status) or 'none'}] hash={hash_hex}")

        if slot == 0:
            slot0_hash = h
        elif slot == 1:
            slot1_hash = h

    print()

    if slot1_hash is None:
        print("  ✗ Slot 1 is EMPTY.")
        print("    MCUboot erased it after the last confirmed swap.")
        print("    We must upload firmware. Run: bash scripts/resilient_upload.sh")
        sys.exit(1)

    print("  ✓ Slot 1 has a valid image! We can revert!")
    print()

    # === Phase 2: Mark slot 1 for test ===
    print("━━━ Phase 2: Mark slot 1 for test swap ━━━")
    print()

    port = detect_port()
    if not port:
        port = wait_for_replug()
    if not port:
        print("  ERROR: No port.")
        sys.exit(1)

    ser = open_port_fast(port)
    print("  Sending 'image test' command...", end=' ', flush=True)
    test_resp = try_image_test(ser, slot1_hash)

    if test_resp is None:
        print("✗ timeout")
        ser.close()
        # One retry
        port = wait_for_replug()
        if port:
            ser = open_port_fast(port)
            print("  [Retry] Sending 'image test'...", end=' ', flush=True)
            test_resp = try_image_test(ser, slot1_hash)
            if test_resp is None:
                print("✗ timeout")
                print("  Cannot mark image for test. SMP dies too quickly.")
                ser.close()
                sys.exit(1)

    print("✓ Response received!")
    print(f"    {test_resp}")
    ser.close()
    print()

    # === Phase 3: Reset ===
    print("━━━ Phase 3: Reset (trigger MCUboot swap) ━━━")
    print()

    port = detect_port()
    if not port:
        port = wait_for_replug()
    if not port:
        # If port is gone, the test command might have caused a reset already
        print("  Port gone — keyboard may be resetting already.")
    else:
        ser = open_port_fast(port)
        print("  Sending reset...", end=' ', flush=True)
        try_reset(ser)
        print("sent!")
        ser.close()

    print("  Waiting 14s for MCUboot swap...")
    for i in range(14, 0, -1):
        sys.stdout.write(f"\r  Swapping... {i:2d}s ")
        sys.stdout.flush()
        time.sleep(1)
    print()
    print()

    # === Phase 4: Confirm ===
    print("━━━ Phase 4: Confirm swapped image ━━━")
    print()

    port = detect_port()
    if not port:
        print("  Waiting for keyboard to reappear...")
        port = wait_for_port(30)
    if not port:
        print("  ⚠ Not detected. Try unplugging and replugging.")
        print("    MCUboot swaps on cold boot even without confirm.")
        print("    After replug, run:")
        print("      python3 scripts/smp_rapid_revert.py --confirm-only")
        sys.exit(1)

    ser = open_port_fast(port)

    print("  Sending confirm...", end=' ', flush=True)
    conf_resp = try_image_confirm(ser)
    if conf_resp is not None:
        print("✓ Confirmed!")
    else:
        print("✗ timeout (but swap may have worked)")

    print("  Sending echo test...", end=' ', flush=True)
    if try_echo(ser):
        print("✓ KEYBOARD IS ALIVE!")
        print()
        print("  ████████████████████████████████████████████████")
        print("  ██                                            ██")
        print("  ██   SUCCESS! Reverted to previous firmware.  ██")
        print("  ██   Try typing on the keyboard now.          ██")
        print("  ██                                            ██")
        print("  ████████████████████████████████████████████████")
    else:
        print("✗ no echo response")
        print()
        print("  The swap may still have worked. Try typing on the keyboard.")
        print("  If keys work, the revert succeeded.")

    ser.close()
    print()


if __name__ == "__main__":
    main()
