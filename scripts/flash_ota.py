#!/usr/bin/env python3
"""
Wobkey Crush 80 OTA Firmware Flasher (Cross-Platform)

Flashes firmware via the Telink USB OTA interface (usage page 0xFFEF).
Works on Linux, macOS, and Windows via the hidapi library.

Protocol (reverse-engineered from .NET OTA flasher):
  - Start packet: triggers OTA mode
  - Data packets: 3x [2B index][16B data][2B CRC16] per packet
  - End packet: final chunk count + complement
  - Flow control: device ACKs each packet before next is sent

Requirements:
    pip install hidapi

Usage:
    python3 flash_ota.py firmware_patched.bin
    python3 flash_ota.py code_2M_patched.bin
    python3 flash_ota.py --dry-run firmware_patched.bin
    python3 flash_ota.py --force --yes firmware_patched.bin
"""

import argparse
import binascii
import struct
import sys
import time

try:
    import hid
except ImportError:
    print("ERROR: hidapi library not installed.")
    print("  Install with: pip install hidapi")
    print("  On Linux, you may also need: sudo apt install libhidapi-dev")
    sys.exit(1)

VID = 0x320F
PID = 0x5055
OTA_USAGE_PAGE = 0xFFEF
REPORT_ID_OTA = 5
CHUNK_DATA_SIZE = 16
CHUNKS_PER_PACKET = 3
DEFAULT_REPORT_SIZE = 64


def crc16(data: bytes) -> int:
    """Telink OTA CRC16 (polynomial 0xA001)."""
    crc = 0xFFFF
    for b in data:
        for _ in range(8):
            if (crc ^ b) & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
            b >>= 1
    return crc


def find_ota_device() -> dict | None:
    """Find the OTA HID device by VID/PID and usage page 0xFFEF.
    Returns the hidapi device info dict or None."""
    devices = hid.enumerate(VID, PID)
    for dev in devices:
        if dev.get('usage_page') == OTA_USAGE_PAGE:
            return dev
    # Fallback: some platforms don't report usage_page in enumerate.
    # Accept first device with matching VID/PID if only one exists.
    if len(devices) == 1:
        return devices[0]
    return None


def load_firmware(path: str) -> tuple[bytearray, int]:
    """Load firmware file. Supports both code_2M.bin (OTA image) and raw firmware.bin.
    Returns (padded_data, firmware_size)."""
    with open(path, 'rb') as f:
        raw = f.read()

    if len(raw) > 1_000_000:
        fw_size = (raw[48] << 24) | (raw[49] << 16) | (raw[50] << 8) | raw[51]
        if fw_size == 0 or fw_size > len(raw) - 256:
            raise ValueError(f"Invalid firmware size in OTA header: {fw_size} "
                             f"(file is {len(raw)} bytes)")
        fw_data = raw[256:256 + fw_size]
        fmt = "code_2M"
    else:
        fw_size = struct.unpack_from('<I', raw, 24)[0]
        if fw_size == 0 or fw_size > len(raw):
            fw_size = len(raw)
        fw_data = raw[:fw_size]
        fmt = "firmware"

    print(f"  Format: {fmt}")
    print(f"  Firmware size: {fw_size} bytes (0x{fw_size:X})")

    if fw_size >= 4:
        crc_check = binascii.crc32(fw_data[:fw_size]) & 0xFFFFFFFF
        crc_stored = struct.unpack_from('<I', fw_data, fw_size - 4)[0]
        if crc_check == 0xFFFFFFFF:
            print(f"  CRC: OK (0x{crc_stored:08X})")
        else:
            print(f"  WARNING: CRC mismatch (stored=0x{crc_stored:08X}, "
                  f"computed=0x{crc_check:08X})")

    num_chunks = (fw_size + 15) // 16
    buf = bytearray(num_chunks * CHUNK_DATA_SIZE)
    buf[:fw_size] = fw_data[:fw_size]
    tail = fw_size % CHUNK_DATA_SIZE
    if tail != 0:
        for i in range(fw_size, fw_size + CHUNK_DATA_SIZE - tail):
            if i < len(buf):
                buf[i] = 0xFF

    return buf, fw_size


class OTADevice:
    """Cross-platform HID device wrapper using hidapi."""

    def __init__(self, device_info: dict):
        self.info = device_info
        self.path = device_info['path']
        self.report_size = DEFAULT_REPORT_SIZE
        self.dev = hid.device()

    def open(self):
        self.dev.open_path(self.path)
        self.dev.set_nonblocking(True)

    def close(self):
        self.dev.close()

    def write(self, data: bytes) -> int:
        """Write data to device. First byte must be the report ID."""
        return self.dev.write(data)

    def read(self, timeout_ms: int = 5000) -> bytes | None:
        """Read from device with timeout. Returns None on timeout."""
        result = self.dev.read(512, timeout_ms)
        if result:
            return bytes(result)
        return None

    def drain(self):
        """Discard any pending data."""
        while True:
            data = self.dev.read(512, 50)
            if not data:
                break

    @property
    def packet_size(self) -> int:
        return 1 + self.report_size

    @property
    def display_name(self) -> str:
        mfr = self.info.get('manufacturer_string', '') or ''
        prod = self.info.get('product_string', '') or ''
        path = self.path.decode() if isinstance(self.path, bytes) else self.path
        if mfr or prod:
            return f"{mfr} {prod}".strip() + f" [{path}]"
        return path


def probe_device(ota_dev: OTADevice):
    """Probe the OTA device: try reading and sending a start command."""
    packet_size = ota_dev.packet_size
    print(f"\nProbing {ota_dev.display_name} (report size {ota_dev.report_size})...")

    try:
        ota_dev.open()
    except Exception as e:
        print(f"  Cannot open: {e}")
        return

    try:
        print("  Checking for pending data...")
        resp = ota_dev.read(timeout_ms=1000)
        if resp:
            print(f"  Pending data: {resp.hex(' ')}")
        else:
            print("  No pending data")

        print(f"  Sending start command ({packet_size} bytes)...")
        start = bytearray(packet_size)
        start[0] = REPORT_ID_OTA
        for i in range(1, packet_size):
            start[i] = 0xFF
        start[1] = 0x02
        start[2] = 0x02
        start[3] = 0x00
        start[4] = 0x01
        start[5] = 0xFF
        print(f"  TX: {bytes(start[:12]).hex(' ')} ...")
        try:
            written = ota_dev.write(bytes(start))
            print(f"  Written: {written} bytes")
        except Exception as e:
            print(f"  Write error: {e}")
            return

        print("  Waiting for response (10s timeout)...")
        for attempt in range(10):
            resp = ota_dev.read(timeout_ms=1000)
            if resp:
                print(f"  RX ({len(resp)} bytes): {resp.hex(' ')}")
                return
            print(f"  ... {attempt + 1}s")
        print("  No response received")

    finally:
        ota_dev.close()


def flash(ota_dev: OTADevice, fw_buf: bytearray, fw_size: int,
          dry_run: bool = False) -> bool:
    """Flash firmware via Telink OTA protocol."""
    num_chunks = len(fw_buf) // CHUNK_DATA_SIZE
    total_packets = (num_chunks + CHUNKS_PER_PACKET - 1) // CHUNKS_PER_PACKET
    packet_size = ota_dev.packet_size

    print(f"\n  Device:       {ota_dev.display_name}")
    print(f"  Chunks:       {num_chunks} ({CHUNK_DATA_SIZE} bytes each)")
    print(f"  Packets:      ~{total_packets}")
    print(f"  Report size:  {ota_dev.report_size} + 1 (report ID) = {packet_size} bytes")

    if dry_run:
        print("\n[DRY RUN] Packet examples:")
        pkt = bytearray(packet_size)
        pkt[0] = REPORT_ID_OTA
        for i in range(1, packet_size):
            pkt[i] = 0xFF
        pkt[1] = 0x02; pkt[2] = 0x02; pkt[3] = 0x00; pkt[4] = 0x01; pkt[5] = 0xFF
        print(f"  Start: {bytes(pkt[:12]).hex(' ')} ...")

        pkt2 = bytearray(packet_size)
        pkt2[0] = REPORT_ID_OTA
        for i in range(1, packet_size):
            pkt2[i] = 0xFF
        pkt2[1] = 0x02; pkt2[2] = 0x00; pkt2[3] = 0x00
        idx = 0
        for j in range(min(3, num_chunks)):
            chunk = bytearray(18)
            chunk[0:2] = struct.pack('<H', idx)
            chunk[2:18] = fw_buf[idx * 16:idx * 16 + 16]
            c = crc16(bytes(chunk))
            base = 4 + 20 * j
            pkt2[base:base + 18] = chunk
            pkt2[base + 18:base + 20] = struct.pack('<H', c)
            idx += 1
            pkt2[2] = 20 * (j + 1)
        print(f"  Data:  {bytes(pkt2[:32]).hex(' ')} ...")
        return True

    try:
        ota_dev.open()
    except Exception as e:
        print(f"\nERROR: Cannot open device: {e}")
        if sys.platform == 'linux':
            print("  Check udev rules or run with sudo")
        return False

    try:
        # --- START ---
        print("\nSending OTA start...")
        start = bytearray(packet_size)
        start[0] = REPORT_ID_OTA
        for i in range(1, packet_size):
            start[i] = 0xFF
        start[1] = 0x02
        start[2] = 0x02
        start[3] = 0x00
        start[4] = 0x01
        start[5] = 0xFF
        ota_dev.write(bytes(start))

        resp = ota_dev.read(timeout_ms=5000)
        if resp is None:
            print("ERROR: No response to start command (is keyboard in OTA mode?)")
            return False
        print(f"  ACK received ({len(resp)} bytes)")

        # --- DATA ---
        ota_index = 0
        pkt_count = 0
        start_time = time.monotonic()

        while True:
            pkt = bytearray(packet_size)
            pkt[0] = REPORT_ID_OTA
            for i in range(1, packet_size):
                pkt[i] = 0xFF
            pkt[1] = 0x02
            pkt[2] = 0x00
            pkt[3] = 0x00

            chunks_in_pkt = 0
            saved_index = ota_index

            for j in range(CHUNKS_PER_PACKET):
                chunk = bytearray(18)
                chunk[0] = ota_index & 0xFF
                chunk[1] = (ota_index >> 8) & 0xFF
                offset = ota_index * CHUNK_DATA_SIZE
                for k in range(CHUNK_DATA_SIZE):
                    if offset + k < len(fw_buf):
                        chunk[2 + k] = fw_buf[offset + k]
                    else:
                        chunk[2 + k] = 0xFF

                c = crc16(bytes(chunk))

                base = 4 + 20 * j
                pkt[base:base + 18] = chunk
                pkt[base + 18] = c & 0xFF
                pkt[base + 19] = (c >> 8) & 0xFF

                ota_index += 1

                if ota_index * CHUNK_DATA_SIZE >= fw_size + CHUNK_DATA_SIZE:
                    ota_index -= 1
                    break

                chunks_in_pkt = j + 1
                pkt[2] = 20 * (j + 1)

            if chunks_in_pkt == 0:
                ota_index = saved_index
                break

            ota_dev.write(bytes(pkt))
            pkt_count += 1

            resp = ota_dev.read(timeout_ms=10000)
            if resp is None:
                print(f"\nERROR: No ACK for packet {pkt_count} "
                      f"(chunks {saved_index}-{ota_index - 1})")
                return False

            progress = min(100, ota_index * CHUNK_DATA_SIZE * 100 // fw_size)
            elapsed = time.monotonic() - start_time
            rate = (ota_index * CHUNK_DATA_SIZE / 1024) / elapsed if elapsed > 0 else 0
            sys.stdout.write(
                f"\r  [{progress:3d}%] {pkt_count}/{total_packets} packets | "
                f"{elapsed:.1f}s | {rate:.1f} KB/s")
            sys.stdout.flush()

        elapsed = time.monotonic() - start_time
        print(f"\n  Data transfer complete: {pkt_count} packets in {elapsed:.1f}s")

        # --- END ---
        print("Sending OTA end...")
        end = bytearray(packet_size)
        end[0] = REPORT_ID_OTA
        for i in range(1, packet_size):
            end[i] = 0xFF
        end[1] = 0x02
        end[2] = 0x06
        end[3] = 0x00
        end[4] = 0x02
        end[5] = 0xFF
        count = (ota_index - 1) & 0xFFFF
        neg_count = (0x10000 - count) & 0xFFFF
        end[6] = count & 0xFF
        end[7] = (count >> 8) & 0xFF
        end[8] = neg_count & 0xFF
        end[9] = (neg_count >> 8) & 0xFF
        ota_dev.write(bytes(end))

        resp = ota_dev.read(timeout_ms=10000)
        if resp is None:
            print("  No final response (device likely rebooted with new firmware)")
            return True

        if (len(resp) >= 7 and resp[0] == REPORT_ID_OTA
                and resp[1] == 0x02 and resp[4] == 0x06):
            if resp[6] == 0x00:
                print("  OTA SUCCESS!")
                return True
            else:
                print(f"  OTA FAILED (error code: {resp[6]})")
                return False
        else:
            print(f"  Response: {resp[:12].hex(' ')}")
            print("  (unrecognized format, device may have rebooted successfully)")
            return True

    finally:
        ota_dev.close()


def main():
    parser = argparse.ArgumentParser(
        description='Wobkey Crush 80 OTA Firmware Flasher (Cross-Platform)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Examples:\n'
               '  %(prog)s firmware_patched.bin\n'
               '  %(prog)s code_2M_patched.bin\n'
               '  %(prog)s --dry-run firmware_patched.bin\n'
               '  %(prog)s --force --yes firmware_patched.bin\n'
               '\n'
               'Supported platforms: Linux, macOS, Windows (via hidapi)')
    parser.add_argument('firmware', nargs='?',
                        help='Firmware file (firmware_patched.bin or code_2M_patched.bin)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be sent without actually flashing')
    parser.add_argument('--force', action='store_true',
                        help='Skip firmware size sanity checks')
    parser.add_argument('--yes', '-y', action='store_true',
                        help='Skip confirmation prompt')
    parser.add_argument('--probe', action='store_true',
                        help='Probe the OTA device without flashing')
    parser.add_argument('--list', action='store_true',
                        help='List all HID devices matching VID/PID')
    args = parser.parse_args()

    # List mode
    if args.list:
        print(f"HID devices matching VID=0x{VID:04X} PID=0x{PID:04X}:")
        devices = hid.enumerate(VID, PID)
        if not devices:
            print("  None found.")
            print("\n  Is the keyboard connected and in USB mode?")
        for i, dev in enumerate(devices):
            path = dev['path'].decode() if isinstance(dev['path'], bytes) else dev['path']
            print(f"\n  [{i}] {path}")
            print(f"      Manufacturer: {dev.get('manufacturer_string', 'N/A')}")
            print(f"      Product:      {dev.get('product_string', 'N/A')}")
            print(f"      Usage Page:   0x{dev.get('usage_page', 0):04X}")
            print(f"      Usage:        0x{dev.get('usage', 0):04X}")
            print(f"      Interface:    {dev.get('interface_number', -1)}")
        sys.exit(0)

    # Probe mode
    if args.probe:
        print("Searching for OTA device...")
        dev_info = find_ota_device()
        if dev_info is None:
            print("ERROR: OTA device not found")
            print("  Use --list to see all matching HID devices")
            sys.exit(1)
        ota_dev = OTADevice(dev_info)
        print(f"  Found: {ota_dev.display_name}")
        probe_device(ota_dev)
        sys.exit(0)

    if not args.firmware:
        parser.error("firmware file is required (unless using --probe or --list)")
    if not __import__('os').path.exists(args.firmware):
        print(f"ERROR: File not found: {args.firmware}")
        sys.exit(1)

    # Load firmware
    print(f"Loading {args.firmware}...")
    try:
        fw_buf, fw_size = load_firmware(args.firmware)
    except (ValueError, struct.error) as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    num_chunks = len(fw_buf) // CHUNK_DATA_SIZE
    print(f"  Send buffer: {len(fw_buf)} bytes ({num_chunks} chunks)")

    # Find device
    print(f"\nSearching for OTA device (VID=0x{VID:04X} PID=0x{PID:04X})...")
    dev_info = find_ota_device()
    if dev_info is None:
        print("ERROR: Wobkey Crush 80 OTA interface not found")
        print("  - Is the keyboard connected via USB?")
        print("  - Is it in USB mode (not Bluetooth/2.4G)?")
        print("  - Use --list to see available HID devices")
        if sys.platform == 'linux':
            print("  - Check udev rules: sudo cp docs/99-wobkey-crush80.rules /etc/udev/rules.d/")
        sys.exit(1)

    ota_dev = OTADevice(dev_info)
    print(f"  Found: {ota_dev.display_name}")

    # Confirm before flashing
    if not args.dry_run and not args.yes:
        print(f"\n{'=' * 54}")
        print("  FIRMWARE FLASH — THIS WILL OVERWRITE THE FIRMWARE")
        print(f"  Device:   {ota_dev.display_name}")
        print(f"  File:     {args.firmware}")
        print(f"  Size:     {fw_size} bytes")
        print(f"{'=' * 54}")
        print("\nIf the flash fails, the OTA bootloader should still")
        print("allow recovery by re-flashing the original firmware.")
        try:
            resp = input("\nProceed? [y/N] ")
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(0)
        if resp.strip().lower() != 'y':
            print("Aborted.")
            sys.exit(0)

    success = flash(ota_dev, fw_buf, fw_size, args.dry_run)

    if success and not args.dry_run:
        print("\nFlash complete. The keyboard should reboot automatically.")
        print("If it doesn't respond, unplug and replug the USB cable.")

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
