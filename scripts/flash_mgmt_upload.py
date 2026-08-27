#!/usr/bin/env python3
"""
Flash Management Upload for Crush 80.

Uses the custom flash_mgmt MCUmgr group (ID 64) to write firmware
directly to flash in small chunks. Designed for recovery when the
running firmware hangs after ~2 seconds, making normal mcumgr image
upload impossible.

Each flash_mgmt command is tiny (<300 bytes on wire) and completes in
<50ms, so we can send ~40 commands per 2-second connectivity window.
"""

import serial
import struct
import base64
import threading
import time
import sys
import os
import glob as _glob

try:
    import cbor2
except ImportError:
    print("Installing cbor2...")
    os.system("pip install cbor2")
    import cbor2

FLASH_MGMT_GROUP = 64
CMD_ERASE = 0
CMD_WRITE = 1
CMD_READ = 2

SLOT1_OFFSET = 0x80000
SLOT1_END = 0xF0000
SECTOR_SIZE = 4096
WRITE_CHUNK = 256
COMMAND_TIMEOUT = 5
MAX_RETRIES = 3

DEFAULT_IMAGE = "dist/crush80-zmk-app.signed.MACMODE-WORKING.bin"


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


class FlashMgmtSMP:
    """SMP client that handles log-flooded serial and filters SMP responses."""

    def __init__(self, port_path):
        self.seq = 0
        self.responses = {}
        self.lock = threading.Lock()
        self.running = True
        self.bytes_drained = 0
        self.port_path = port_path
        self.ser = None
        self._open_port()
        self.reader = threading.Thread(target=self._drain_and_filter, daemon=True)
        self.reader.start()
        time.sleep(0.5)

    def _open_port(self):
        for attempt in range(10):
            try:
                self.ser = serial.Serial(self.port_path, 115200, timeout=0.01)
                self.ser.dtr = True
                self.ser.rts = True
                return
            except (serial.SerialException, OSError) as e:
                if attempt < 9:
                    time.sleep(1)
                else:
                    raise RuntimeError(f"Cannot open {self.port_path}: {e}")

    def _drain_and_filter(self):
        buf = b""
        while self.running:
            try:
                data = self.ser.read(4096)
                if data:
                    self.bytes_drained += len(data)
                    buf += data

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
                            pkt_len = struct.unpack(">H", raw[0:2])[0]
                            smp_msg = raw[2:2 + pkt_len - 2]
                            if len(smp_msg) < 8:
                                continue
                            seq = smp_msg[6]
                            cbor_data = smp_msg[8:]
                            resp = cbor2.loads(cbor_data)
                            with self.lock:
                                self.responses[seq] = resp
                        except Exception:
                            pass

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

    def send(self, op, group, cmd_id, payload_dict, timeout=COMMAND_TIMEOUT):
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

        with self.lock:
            self.responses.pop(seq, None)

        self.ser.write(frame)
        self.ser.flush()

        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                if seq in self.responses:
                    return self.responses.pop(seq)
            time.sleep(0.01)
        return None

    def reconnect(self):
        """Close and reopen the port after a replug."""
        try:
            self.ser.close()
        except Exception:
            pass
        time.sleep(0.5)
        self._open_port()

    def close(self):
        self.running = False
        time.sleep(0.1)
        try:
            self.ser.close()
        except Exception:
            pass


def wait_for_replug(smp):
    """Prompt user to unplug/replug and reconnect."""
    print("\n  *** TIMEOUT — device likely froze ***")
    print("  Unplug the keyboard, wait 2 seconds, then plug it back in.")
    input("  Press ENTER after replugging... ")
    time.sleep(1)

    port = detect_port()
    if port and port != smp.port_path:
        smp.port_path = port
        print(f"  Port changed to: {port}")
    smp.reconnect()
    time.sleep(1)
    print("  Reconnected. Resuming...\n")


def detect_port():
    ports = _glob.glob('/dev/cu.usbmodem*')
    return ports[0] if ports else None


def erase_slot(smp, image_size):
    """Erase enough sectors at slot 1 to fit the image."""
    num_sectors = (image_size + SECTOR_SIZE - 1) // SECTOR_SIZE
    total_erase = num_sectors * SECTOR_SIZE

    print(f"  Erasing {num_sectors} sectors ({total_erase // 1024} KB) at 0x{SLOT1_OFFSET:X}...")
    print()

    erased = 0
    sector_idx = 0

    while sector_idx < num_sectors:
        offset = SLOT1_OFFSET + sector_idx * SECTOR_SIZE
        payload = {"off": offset, "len": SECTOR_SIZE}

        success = False
        for retry in range(MAX_RETRIES):
            resp = smp.send(2, FLASH_MGMT_GROUP, CMD_ERASE, payload)
            if resp is not None:
                rc = resp.get("rc", resp.get("err", 0))
                if isinstance(rc, dict):
                    rc = rc.get("rc", 0)
                if rc != 0:
                    print(f"\n  ERROR: erase at 0x{offset:X} returned rc={rc}")
                    return False
                success = True
                break
            else:
                if retry < MAX_RETRIES - 1:
                    sys.stdout.write("T")
                    sys.stdout.flush()

        if not success:
            wait_for_replug(smp)
            continue

        sector_idx += 1
        erased += SECTOR_SIZE
        pct = sector_idx * 100 // num_sectors
        bar_len = 40
        filled = bar_len * sector_idx // num_sectors
        bar = "█" * filled + "░" * (bar_len - filled)
        sys.stdout.write(f"\r  Erase: [{bar}] {pct:3d}% ({sector_idx}/{num_sectors} sectors)")
        sys.stdout.flush()

    print("\n  Erase complete.\n")
    return True


def write_image(smp, image_data):
    """Write image data in 256-byte chunks to slot 1."""
    total = len(image_data)
    num_chunks = (total + WRITE_CHUNK - 1) // WRITE_CHUNK

    print(f"  Writing {total:,} bytes ({num_chunks} chunks of {WRITE_CHUNK}B) to 0x{SLOT1_OFFSET:X}...")
    print()

    chunk_idx = 0
    retries_total = 0

    while chunk_idx < num_chunks:
        data_offset = chunk_idx * WRITE_CHUNK
        chunk = image_data[data_offset:data_offset + WRITE_CHUNK]
        flash_offset = SLOT1_OFFSET + data_offset
        payload = {"off": flash_offset, "data": chunk}

        success = False
        for retry in range(MAX_RETRIES):
            resp = smp.send(2, FLASH_MGMT_GROUP, CMD_WRITE, payload)
            if resp is not None:
                rc = resp.get("rc", resp.get("err", 0))
                if isinstance(rc, dict):
                    rc = rc.get("rc", 0)
                if rc != 0:
                    print(f"\n  ERROR: write at 0x{flash_offset:X} returned rc={rc}")
                    return False
                success = True
                break
            else:
                retries_total += 1
                if retry < MAX_RETRIES - 1:
                    sys.stdout.write("T")
                    sys.stdout.flush()

        if not success:
            wait_for_replug(smp)
            continue

        chunk_idx += 1
        written = min(chunk_idx * WRITE_CHUNK, total)
        pct = written * 100 // total
        bar_len = 40
        filled = bar_len * written // total
        bar = "█" * filled + "░" * (bar_len - filled)
        sys.stdout.write(
            f"\r  Write: [{bar}] {pct:3d}% "
            f"({written // 1024}/{total // 1024} KB) "
            f"[retries: {retries_total}]"
        )
        sys.stdout.flush()

    print(f"\n  Write complete. ({retries_total} total retries)\n")
    return True


def verify_image(smp, image_data, num_checks=8):
    """Read back a few chunks and compare to the source image."""
    total = len(image_data)
    check_offsets = []

    step = total // (num_checks + 1)
    for i in range(num_checks):
        off = step * (i + 1)
        off = (off // WRITE_CHUNK) * WRITE_CHUNK
        check_offsets.append(off)

    print(f"  Verifying {num_checks} random chunks...")
    mismatches = 0

    for data_offset in check_offsets:
        flash_offset = SLOT1_OFFSET + data_offset
        read_len = min(WRITE_CHUNK, total - data_offset)
        payload = {"off": flash_offset, "len": read_len}

        resp = None
        for retry in range(MAX_RETRIES):
            resp = smp.send(0, FLASH_MGMT_GROUP, CMD_READ, payload)
            if resp is not None:
                break
            if retry == MAX_RETRIES - 1:
                wait_for_replug(smp)

        if resp is None:
            print(f"    0x{flash_offset:X}: TIMEOUT (skipped)")
            continue

        rc = resp.get("rc", resp.get("err", 0))
        if isinstance(rc, dict):
            rc = rc.get("rc", 0)
        if rc != 0:
            print(f"    0x{flash_offset:X}: ERROR rc={rc}")
            mismatches += 1
            continue

        read_data = resp.get("data", b"")
        expected = image_data[data_offset:data_offset + read_len]

        if read_data == expected:
            sys.stdout.write(".")
            sys.stdout.flush()
        else:
            print(f"\n    MISMATCH at 0x{flash_offset:X}!")
            mismatches += 1

    if mismatches == 0:
        print(f"\n  Verification PASSED ({num_checks} chunks OK)\n")
    else:
        print(f"\n  Verification FAILED ({mismatches}/{num_checks} mismatches)\n")
    return mismatches == 0


def main():
    print()
    print("=" * 60)
    print("  Crush 80 — Flash Management Direct Writer")
    print("  (Recovery tool for frozen firmware)")
    print("=" * 60)
    print()

    image_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_IMAGE
    if not os.path.exists(image_path):
        print(f"  ERROR: Image not found: {image_path}")
        print(f"  Usage: {sys.argv[0]} [firmware.signed.bin]")
        sys.exit(1)

    with open(image_path, "rb") as f:
        image_data = f.read()

    image_size = len(image_data)
    max_slot_size = SLOT1_END - SLOT1_OFFSET

    if image_size > max_slot_size:
        print(f"  ERROR: Image ({image_size:,} bytes) exceeds slot 1 "
              f"({max_slot_size:,} bytes)")
        sys.exit(1)

    num_sectors = (image_size + SECTOR_SIZE - 1) // SECTOR_SIZE
    num_chunks = (image_size + WRITE_CHUNK - 1) // WRITE_CHUNK

    port = detect_port()
    if not port:
        print("  ERROR: No keyboard found (/dev/cu.usbmodem*)")
        print("  Plug in the keyboard and try again.")
        sys.exit(1)

    print(f"  Image:   {os.path.basename(image_path)}")
    print(f"  Size:    {image_size:,} bytes")
    print(f"  Target:  Slot 1 @ 0x{SLOT1_OFFSET:X}")
    print(f"  Erase:   {num_sectors} sectors ({num_sectors * SECTOR_SIZE // 1024} KB)")
    print(f"  Write:   {num_chunks} chunks of {WRITE_CHUNK} bytes")
    print(f"  Port:    {port}")
    print()
    print("  Strategy: Each command is <300 bytes and completes in <50ms.")
    print(f"  With ~2s windows, expect ~{(num_sectors + num_chunks) // 40 + 1} "
          f"power cycles ({(num_sectors + num_chunks) // 40 * 15 // 60 + 1}-"
          f"{(num_sectors + num_chunks) // 40 * 30 // 60 + 2} min).")
    print()

    input("  Press ENTER to start (Ctrl+C to abort)... ")
    print()

    smp = FlashMgmtSMP(port)
    print(f"  Connected. Draining log flood ({smp.bytes_drained} bytes so far)...")
    time.sleep(1)
    print(f"  Drained {smp.bytes_drained:,} bytes. Starting operations...\n")

    if not erase_slot(smp, image_size):
        print("  ABORTED: Erase failed.")
        smp.close()
        sys.exit(1)

    if not write_image(smp, image_data):
        print("  ABORTED: Write failed.")
        smp.close()
        sys.exit(1)

    print("  --- Verification ---")
    verify_image(smp, image_data)

    smp.close()

    print("=" * 60)
    print("  DONE! Firmware written to slot 1.")
    print()
    print("  Next steps:")
    print("  1. Run:  ~/go/bin/mcumgr --conntype serial \\")
    print("       --connstring 'dev=/dev/cu.usbmodem1101,baud=115200' image list")
    print("  2. Copy the slot 1 hash, then run:")
    print("       mcumgr image test <hash>")
    print("  3. Unplug keyboard for 10 seconds, then plug back in.")
    print("  4. After it boots the new image, confirm:")
    print("       mcumgr image confirm ''")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
