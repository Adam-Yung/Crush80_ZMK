#!/usr/bin/env python3
"""
Crush80 Stage 2 Flasher — writes MCUboot + ZMK app via SMP flash_mgmt.

Communicates with the OTA bridge's custom mcumgr group 64 (flash_mgmt)
over CDC-ACM serial to stage firmware in flash, then triggers the RAM
trampoline to copy it to address 0x0 and reboot.

Protocol: SMP (Simple Management Protocol) over UART with base64 framing.

Requirements:
    pip install pyserial cbor2

Usage:
    python3 scripts/flash_stage2.py /dev/cu.usbmodemXXXX
    python3 scripts/flash_stage2.py --auto   (auto-detect serial port)
"""

import argparse
import base64
import struct
import sys
import time
import os

try:
    import serial
except ImportError:
    print("ERROR: pyserial not installed. Run: pip install pyserial")
    sys.exit(1)

try:
    import cbor2
except ImportError:
    print("ERROR: cbor2 not installed. Run: pip install cbor2")
    sys.exit(1)

MCUBOOT_PAD_SIZE = 0x10000  # 64 KB — MCUboot partition size
STAGING_OFFSET = 0x80000     # Write combined binary here (slot1 area)
PROTECTED_START = 0xFE000    # RF cal + MAC — never touch

SMP_HEADER_SIZE = 8
SMP_OP_WRITE = 2
SMP_OP_READ = 0
MGMT_GROUP_FLASH = 64  # MGMT_GROUP_ID_PERUSER

FLASH_MGMT_ERASE = 0
FLASH_MGMT_WRITE = 1
FLASH_MGMT_READ = 2
FLASH_MGMT_COMMIT = 3

CHUNK_SIZE = 200  # bytes per SMP write (must fit in SMP netbuf)
ERASE_SECTOR = 4096


def smp_frame(op, group, cmd_id, seq, payload_cbor):
    """Build an SMP frame: header + CBOR payload, base64-encoded with newline framing."""
    flags = 0
    hdr = struct.pack('>BBHHBBH',
                      op,           # nh_op
                      flags,        # nh_flags
                      len(payload_cbor),  # nh_len
                      group,        # nh_group
                      seq,          # nh_seq
                      cmd_id,       # nh_id
                      0)            # reserved (nh_version << 8 | 0)
    # SMP over serial uses base64 with \x06...\n framing
    raw = hdr + payload_cbor
    encoded = base64.b64encode(raw)
    # Frame: 0x06 0x09 <base64 data> \n
    frame = b'\x06\x09' + encoded + b'\n'
    return frame


def smp_parse_response(data):
    """Parse SMP response from base64-framed serial data."""
    # Strip framing bytes
    if data.startswith(b'\x06\x09'):
        data = data[2:]
    if data.endswith(b'\n'):
        data = data[:-1]
    raw = base64.b64decode(data)
    if len(raw) < SMP_HEADER_SIZE:
        raise ValueError(f"Response too short: {len(raw)} bytes")
    hdr = raw[:SMP_HEADER_SIZE]
    payload = raw[SMP_HEADER_SIZE:]
    op, flags, length, group, seq, cmd_id, _ = struct.unpack('>BBHHBBH', hdr)
    body = cbor2.loads(payload) if payload else {}
    return {'op': op, 'group': group, 'seq': seq, 'cmd_id': cmd_id, 'body': body}


class SMPClient:
    """SMP client over serial (CDC-ACM)."""

    def __init__(self, port, baud=115200, timeout=5.0):
        self.ser = serial.Serial(port, baud, timeout=timeout)
        self.seq = 0
        time.sleep(0.1)
        self.ser.reset_input_buffer()

    def close(self):
        self.ser.close()

    def _next_seq(self):
        s = self.seq
        self.seq = (self.seq + 1) & 0xFF
        return s

    def transact(self, op, cmd_id, payload_dict, timeout=10.0):
        """Send SMP command and wait for response."""
        payload_cbor = cbor2.dumps(payload_dict)
        seq = self._next_seq()
        frame = smp_frame(op, MGMT_GROUP_FLASH, cmd_id, seq, payload_cbor)

        self.ser.reset_input_buffer()
        self.ser.write(frame)
        self.ser.flush()

        # Read response (newline-terminated)
        deadline = time.monotonic() + timeout
        buf = b''
        while time.monotonic() < deadline:
            chunk = self.ser.read(1024)
            if chunk:
                buf += chunk
                if b'\n' in buf:
                    # Take first complete frame
                    line = buf.split(b'\n')[0]
                    return smp_parse_response(line)
            else:
                time.sleep(0.01)

        raise TimeoutError(f"No SMP response within {timeout}s (got {len(buf)} bytes)")

    def flash_erase(self, offset, length):
        """Erase flash region (must be sector-aligned)."""
        resp = self.transact(SMP_OP_WRITE, FLASH_MGMT_ERASE,
                             {"off": offset, "len": length})
        rc = resp['body'].get('rc', -1)
        if rc != 0:
            raise RuntimeError(f"flash_erase(0x{offset:X}, 0x{length:X}) failed: rc={rc}")
        return rc

    def flash_write(self, offset, data):
        """Write data to flash (max CHUNK_SIZE bytes)."""
        resp = self.transact(SMP_OP_WRITE, FLASH_MGMT_WRITE,
                             {"off": offset, "data": data})
        rc = resp['body'].get('rc', -1)
        if rc != 0:
            raise RuntimeError(f"flash_write(0x{offset:X}, {len(data)}B) failed: rc={rc}")
        return rc

    def flash_read(self, offset, length):
        """Read data from flash."""
        resp = self.transact(SMP_OP_READ, FLASH_MGMT_READ,
                             {"off": offset, "len": length})
        rc = resp['body'].get('rc', -1)
        if rc != 0:
            raise RuntimeError(f"flash_read(0x{offset:X}, {length}B) failed: rc={rc}")
        return resp['body'].get('data', b'')

    def flash_commit(self, staging_offset, firmware_length):
        """Trigger RAM trampoline: copy staging → 0x0 and reset."""
        resp = self.transact(SMP_OP_WRITE, FLASH_MGMT_COMMIT,
                             {"stg": staging_offset, "len": firmware_length},
                             timeout=5.0)
        rc = resp['body'].get('rc', -1)
        if rc != 0:
            raise RuntimeError(f"flash_commit(stg=0x{staging_offset:X}, "
                               f"len=0x{firmware_length:X}) failed: rc={rc}")
        return rc


def build_combined_binary(mcuboot_path, app_path):
    """Build combined MCUboot + signed app binary."""
    mcuboot = open(mcuboot_path, 'rb').read()
    app = open(app_path, 'rb').read()

    if len(mcuboot) > MCUBOOT_PAD_SIZE:
        raise ValueError(f"MCUboot too large: {len(mcuboot)} > {MCUBOOT_PAD_SIZE}")

    # Pad MCUboot to exactly 64 KB (boot_partition size)
    combined = bytearray(MCUBOOT_PAD_SIZE)
    combined[:len(mcuboot)] = mcuboot
    # Fill padding with 0xFF (erased flash value)
    for i in range(len(mcuboot), MCUBOOT_PAD_SIZE):
        combined[i] = 0xFF
    # Append signed app at offset 0x10000 (slot0 start)
    combined += app

    return bytes(combined)


def find_serial_port():
    """Auto-detect CDC-ACM serial port."""
    import glob
    if sys.platform == 'darwin':
        ports = glob.glob('/dev/cu.usbmodem*')
    else:
        ports = glob.glob('/dev/ttyACM*')
    if ports:
        return ports[0]
    return None


def main():
    parser = argparse.ArgumentParser(description='Crush80 Stage 2 Flasher')
    parser.add_argument('port', nargs='?', help='Serial port (e.g., /dev/cu.usbmodem1234)')
    parser.add_argument('--auto', action='store_true', help='Auto-detect serial port')
    parser.add_argument('--dist', default=None,
                        help='Path to dist/ directory (default: ./dist)')
    parser.add_argument('--verify', action='store_true',
                        help='Read back and verify after writing')
    parser.add_argument('--skip-erase', action='store_true',
                        help='Skip erase (staging already clean)')
    args = parser.parse_args()

    # Find serial port
    port = args.port
    if not port or args.auto:
        port = find_serial_port()
        if not port:
            print("ERROR: No serial port found.")
            print("  The OTA bridge should appear as /dev/cu.usbmodem* (macOS)")
            print("  or /dev/ttyACM* (Linux) after Stage 1.")
            sys.exit(1)
    print(f"Serial port: {port}")

    # Find firmware files
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dist_dir = args.dist or os.path.join(repo_dir, 'dist')
    mcuboot_path = os.path.join(dist_dir, 'crush80-mcuboot.bin')
    app_path = os.path.join(dist_dir, 'crush80-zmk-app.signed.bin')

    for p in [mcuboot_path, app_path]:
        if not os.path.exists(p):
            print(f"ERROR: {p} not found. Run 'bash build.sh --build-mcuboot' first.")
            sys.exit(1)

    # Build combined binary
    print("\nBuilding combined binary...")
    print(f"  MCUboot: {mcuboot_path} ({os.path.getsize(mcuboot_path)} bytes)")
    print(f"  App:     {app_path} ({os.path.getsize(app_path)} bytes)")
    combined = build_combined_binary(mcuboot_path, app_path)
    print(f"  Combined: {len(combined)} bytes (0x{len(combined):X})")

    # Validate fit
    if STAGING_OFFSET + len(combined) > PROTECTED_START:
        print(f"ERROR: Combined binary too large for staging area!")
        print(f"  Staging 0x{STAGING_OFFSET:X} + 0x{len(combined):X} = "
              f"0x{STAGING_OFFSET + len(combined):X} > 0x{PROTECTED_START:X}")
        sys.exit(1)

    # Compute erase size (sector-aligned)
    erase_size = ((len(combined) + ERASE_SECTOR - 1) // ERASE_SECTOR) * ERASE_SECTOR
    print(f"  Erase size: {erase_size} bytes (0x{erase_size:X})")
    print(f"  Staging at: 0x{STAGING_OFFSET:X}")
    print(f"  Staging end: 0x{STAGING_OFFSET + erase_size:X}")

    # Connect
    print(f"\nConnecting to {port}...")
    try:
        client = SMPClient(port)
    except Exception as e:
        print(f"ERROR: Cannot open {port}: {e}")
        sys.exit(1)

    # Quick connectivity test: try reading 4 bytes from flash offset 0
    print("  Testing SMP connectivity...")
    try:
        test_data = client.flash_read(0, 4)
        print(f"  OK — flash[0:4] = {test_data.hex()}")
    except Exception as e:
        print(f"  ERROR: SMP communication failed: {e}")
        client.close()
        sys.exit(1)

    # Phase 1: Erase staging area
    if not args.skip_erase:
        print(f"\nPhase 1: Erasing staging area (0x{STAGING_OFFSET:X}, "
              f"{erase_size // 1024} KB)...")
        sectors = erase_size // ERASE_SECTOR
        for i in range(0, erase_size, ERASE_SECTOR):
            sector_off = STAGING_OFFSET + i
            try:
                client.flash_erase(sector_off, ERASE_SECTOR)
            except Exception as e:
                print(f"\n  ERROR at sector 0x{sector_off:X}: {e}")
                client.close()
                sys.exit(1)
            progress = (i + ERASE_SECTOR) * 100 // erase_size
            sys.stdout.write(f"\r  [{progress:3d}%] Erased {(i + ERASE_SECTOR) // 1024} / "
                             f"{erase_size // 1024} KB")
            sys.stdout.flush()
        print("\n  Erase complete.")
    else:
        print("\nPhase 1: Skipping erase (--skip-erase).")

    # Phase 2: Write combined binary to staging area
    print(f"\nPhase 2: Writing {len(combined)} bytes to staging area...")
    start_time = time.monotonic()
    bytes_written = 0

    for offset in range(0, len(combined), CHUNK_SIZE):
        chunk = combined[offset:offset + CHUNK_SIZE]
        flash_off = STAGING_OFFSET + offset
        try:
            client.flash_write(flash_off, chunk)
        except Exception as e:
            print(f"\n  ERROR at offset 0x{flash_off:X}: {e}")
            client.close()
            sys.exit(1)

        bytes_written += len(chunk)
        elapsed = time.monotonic() - start_time
        rate = bytes_written / elapsed if elapsed > 0 else 0
        progress = bytes_written * 100 // len(combined)
        sys.stdout.write(f"\r  [{progress:3d}%] {bytes_written // 1024} / "
                         f"{len(combined) // 1024} KB | {rate / 1024:.1f} KB/s")
        sys.stdout.flush()

    elapsed = time.monotonic() - start_time
    print(f"\n  Write complete: {bytes_written} bytes in {elapsed:.1f}s "
          f"({bytes_written / elapsed / 1024:.1f} KB/s)")

    # Optional: verify
    if args.verify:
        print("\nVerifying (reading back first 1 KB)...")
        verify_len = min(1024, len(combined))
        readback = b''
        for off in range(0, verify_len, 256):
            chunk_len = min(256, verify_len - off)
            data = client.flash_read(STAGING_OFFSET + off, chunk_len)
            readback += data
        if readback == combined[:verify_len]:
            print("  Verify OK — first 1 KB matches.")
        else:
            mismatch = -1
            for i in range(len(readback)):
                if readback[i] != combined[i]:
                    mismatch = i
                    break
            print(f"  VERIFY FAILED at byte {mismatch}!")
            print(f"    Expected: {combined[mismatch:mismatch+8].hex()}")
            print(f"    Got:      {readback[mismatch:mismatch+8].hex()}")
            client.close()
            sys.exit(1)

    # Phase 3: Commit — triggers RAM trampoline
    print(f"\nPhase 3: Committing (stg=0x{STAGING_OFFSET:X}, len=0x{len(combined):X})...")
    print("  This erases flash 0x0, copies firmware, and resets the MCU.")
    print("  The keyboard will be unresponsive for ~5 seconds...")
    try:
        client.flash_commit(STAGING_OFFSET, len(combined))
        print("  Commit acknowledged. Trampoline executing in 500ms...")
    except TimeoutError:
        print("  Response timeout (expected — device is rebooting).")
    except Exception as e:
        print(f"  Commit response: {e}")
        print("  (May still be OK if device rebooted during response)")

    client.close()

    print("\n" + "=" * 50)
    print("  Stage 2 complete!")
    print("  The keyboard should reboot into MCUboot → ZMK in ~5 seconds.")
    print("  If it doesn't come back, wait 30s (MCUboot watchdog recovery).")
    print("=" * 50)


if __name__ == '__main__':
    main()
