#!/usr/bin/env python3
"""
Resilient SMP firmware uploader for Crush 80.
Handles log-flooded serial ports by continuously draining all data
and filtering for SMP response frames.
"""

import serial
import struct
import base64
import hashlib
import threading
import time
import sys
import os

try:
    import cbor2
except ImportError:
    print("Installing cbor2...")
    os.system("pip install cbor2")
    import cbor2

PORT = sys.argv[1] if len(sys.argv) > 1 else None
if not PORT:
    import glob as _glob
    _ports = _glob.glob('/dev/cu.usbmodem*')
    PORT = _ports[0] if _ports else None
    if not PORT:
        print("ERROR: No keyboard found. Plug in and retry, or pass port as argument.")
        sys.exit(1)
    print(f"Auto-detected port: {PORT}")
IMAGE = sys.argv[2] if len(sys.argv) > 2 else "dist/crush80-zmk-app.signed.bin"
CHUNK_SIZE = 128
MAX_RETRIES = 15
TIMEOUT = 10


def crc16_ccitt(data):
    crc = 0x0000
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


class FloodTolerantSMP:
    def __init__(self, port_path):
        self.seq = 0
        self.responses = {}
        self.lock = threading.Lock()
        self.running = True
        self.bytes_drained = 0

        # Open port with retries
        for attempt in range(10):
            try:
                self.ser = serial.Serial(port_path, 115200, timeout=0.01)
                self.ser.dtr = True
                self.ser.rts = True
                break
            except (serial.SerialException, OSError) as e:
                if attempt < 9:
                    time.sleep(1)
                else:
                    raise RuntimeError(f"Cannot open {port_path}: {e}")

        # Start reader thread immediately
        self.reader = threading.Thread(target=self._drain_and_filter, daemon=True)
        self.reader.start()
        time.sleep(1)  # Let reader drain initial burst

    def _drain_and_filter(self):
        buf = b""
        while self.running:
            try:
                data = self.ser.read(4096)
                if data:
                    self.bytes_drained += len(data)
                    buf += data

                    # Scan for SMP frames: \x06\x09 ... \n
                    while b"\x06\x09" in buf:
                        idx = buf.index(b"\x06\x09")
                        nl = buf.find(b"\n", idx)
                        if nl == -1:
                            buf = buf[idx:]
                            break
                        frame_b64 = buf[idx + 2:nl]
                        buf = buf[nl + 1:]

                        try:
                            raw = base64.b64decode(frame_b64)
                            if len(raw) < 12:
                                continue
                            # Parse: [2-byte len][8-byte SMP header][CBOR payload][2-byte CRC]
                            pkt_len = struct.unpack(">H", raw[0:2])[0]
                            smp_msg = raw[2:2 + pkt_len - 2]  # exclude CRC
                            if len(smp_msg) < 8:
                                continue
                            seq = smp_msg[6]
                            cbor_data = smp_msg[8:]
                            resp = cbor2.loads(cbor_data)
                            with self.lock:
                                self.responses[seq] = resp
                        except Exception:
                            pass

                    # Prevent unbounded growth
                    if len(buf) > 65536:
                        buf = buf[-8192:]
            except (serial.SerialException, OSError):
                time.sleep(0.1)

    def _encode_frame(self, msg):
        crc = crc16_ccitt(msg)
        full_len = len(msg) + 2
        pkt = struct.pack(">H", full_len) + msg + struct.pack(">H", crc)
        b64 = base64.b64encode(pkt)

        frame = b""
        for i in range(0, len(b64), 124):
            chunk = b64[i:i + 124]
            if i == 0:
                frame += b"\x06\x09" + chunk + b"\n"
            else:
                frame += b"\x04\x14" + chunk + b"\n"
        return frame

    def send(self, op, group, cmd_id, payload_dict, timeout=TIMEOUT):
        self.seq = (self.seq + 1) % 256
        seq = self.seq

        cbor_data = cbor2.dumps(payload_dict)
        msg = bytearray(8 + len(cbor_data))
        msg[0] = op
        msg[1] = 0
        struct.pack_into(">H", msg, 2, len(cbor_data))
        struct.pack_into(">H", msg, 4, group)
        msg[6] = seq
        msg[7] = cmd_id
        msg[8:] = cbor_data

        frame = self._encode_frame(bytes(msg))

        # Clear old response for this seq
        with self.lock:
            self.responses.pop(seq, None)

        self.ser.write(frame)
        self.ser.flush()

        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                if seq in self.responses:
                    return self.responses.pop(seq)
            time.sleep(0.02)
        return None

    def close(self):
        self.running = False
        time.sleep(0.1)
        self.ser.close()


def upload(port_path, image_path):
    with open(image_path, "rb") as f:
        image_data = f.read()

    total = len(image_data)
    sha = hashlib.sha256(image_data).digest()

    print(f"  Image: {os.path.basename(image_path)}")
    print(f"  Size:  {total:,} bytes")
    print(f"  Port:  {port_path}")
    print(f"  Chunk: {CHUNK_SIZE} bytes")
    print()

    smp = FloodTolerantSMP(port_path)
    print(f"  Connected. Reader draining {smp.bytes_drained} bytes initial flood...")
    time.sleep(2)
    print(f"  Drained {smp.bytes_drained} bytes. Starting upload...")
    print()

    offset = 0
    retries_total = 0

    while offset < total:
        chunk = image_data[offset:offset + CHUNK_SIZE]
        payload = {"off": offset, "data": chunk, "len": total}
        if offset == 0:
            payload["sha"] = sha
            payload["image"] = 0

        success = False
        for retry in range(MAX_RETRIES):
            resp = smp.send(2, 1, 0, payload)  # op=write, group=img, cmd=upload
            if resp is not None:
                rc = resp.get("rc", 0)
                if rc != 0:
                    print(f"\n  ERROR at offset {offset}: rc={rc}")
                    smp.close()
                    return False
                new_off = resp.get("off", offset + len(chunk))
                offset = new_off
                success = True
                break
            else:
                retries_total += 1
                sys.stdout.write(".")
                sys.stdout.flush()

        if not success:
            print(f"\n  FAILED at offset {offset} after {MAX_RETRIES} retries")
            print(f"  (Drained {smp.bytes_drained:,} bytes of log data)")
            smp.close()
            return False

        pct = offset * 100 // total
        sys.stdout.write(f"\r  {offset // 1024}/{total // 1024} KB ({pct}%) "
                         f"[retries: {retries_total}, drained: {smp.bytes_drained // 1024}KB]")
        sys.stdout.flush()

    print(f"\n\n  Upload complete! ({retries_total} retries, "
          f"{smp.bytes_drained // 1024}KB log data drained)")
    smp.close()
    return True


def main():
    print("=== Crush 80 Resilient Firmware Upload ===")
    print()

    if not os.path.exists(IMAGE):
        print(f"  ERROR: {IMAGE} not found")
        sys.exit(1)

    if not upload(PORT, IMAGE):
        sys.exit(1)

    print()
    print("  Next steps:")
    print("  1. Run: ~/go/bin/mcumgr --conntype serial \\")
    print("       --connstring 'dev=/dev/cu.usbmodem1101,baud=115200' image list")
    print("  2. Mark pending: mcumgr image test <slot1_hash>")
    print("  3. UNPLUG keyboard for 10 seconds, then plug back in")
    print("  4. Wait 15s, then: mcumgr image confirm ''")


if __name__ == "__main__":
    main()
