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
    Returns the hidapi device info dict (with 'hidraw_path' on Linux) or None."""

    # On Linux, hidapi doesn't report usage_page reliably.
    # Find the correct hidraw device via /sys/class/hidraw.
    if sys.platform == 'linux':
        return _find_ota_linux()

    devices = hid.enumerate(VID, PID)
    for dev in devices:
        if dev.get('usage_page') == OTA_USAGE_PAGE:
            return dev
    # Fallback: some platforms don't report usage_page in enumerate.
    if len(devices) == 1:
        return devices[0]
    return None


def _find_ota_linux() -> dict | None:
    """Linux-specific: find the hidraw device for the OTA interface (input2).

    Searches /sys/class/hidraw/ for VID:PID match on the correct USB interface.
    The OTA endpoint lives on USB interface 2 (HID_PHYS contains 'input2').
    """
    import os
    import glob as globmod

    hid_id_match = f"{VID:08X}:{PID:08X}".upper()
    target_interface = 2

    for hid_dev in sorted(globmod.glob("/sys/bus/hid/devices/*")):
        uevent_path = os.path.join(hid_dev, "uevent")
        if not os.path.isfile(uevent_path):
            continue
        with open(uevent_path) as f:
            uevent = f.read()
        if hid_id_match not in uevent.upper():
            continue
        if f"input{target_interface}" not in uevent:
            continue

        # Found the right HID device — now find its hidraw node
        hidraw_dir = os.path.join(hid_dev, "hidraw")
        if os.path.isdir(hidraw_dir):
            nodes = os.listdir(hidraw_dir)
            if nodes:
                hidraw_path = f"/dev/{nodes[0]}"
                return {
                    'path': b'linux-hidraw',
                    'vendor_id': VID,
                    'product_id': PID,
                    'interface_number': target_interface,
                    'usage_page': OTA_USAGE_PAGE,
                    'hidraw_path': hidraw_path,
                    'product_string': 'Crush 80',
                }

    # Fallback: try hidapi enumerate and interface_number
    devices = hid.enumerate(VID, PID)
    for dev in devices:
        if dev.get('interface_number') == target_interface:
            return dev
    if devices:
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
    """Cross-platform HID device wrapper.

    On Linux: uses raw hidraw (os.open/read/write + select) because hidapi's
    open_path often fails with the bus-path format.
    On macOS/Windows: uses hidapi library.
    """

    def __init__(self, device_info: dict):
        self.info = device_info
        self.path = device_info['path']
        self.report_size = DEFAULT_REPORT_SIZE
        self._use_hidraw = (sys.platform == 'linux'
                            and 'hidraw_path' in device_info)
        self._fd = -1
        self._dev = None

    def open(self):
        if self._use_hidraw:
            import os as _os
            hidraw = self.info['hidraw_path']
            self._fd = _os.open(hidraw, _os.O_RDWR | _os.O_NONBLOCK)
            # Detect actual report size from a probe write
            self.report_size = 63  # Crush80: 1B report_id + 63B data = 64B total
            return

        self._dev = hid.device()
        try:
            self._dev.open_path(self.path)
        except Exception:
            self._dev = hid.device()
            devices = hid.enumerate(self.info['vendor_id'], self.info['product_id'])
            opened = False
            for d in devices:
                try:
                    self._dev.open_path(d['path'])
                    opened = True
                    break
                except Exception:
                    self._dev = hid.device()
                    continue
            if not opened:
                raise OSError("Cannot open any HID interface on this device")
        self._dev.set_nonblocking(True)

    def close(self):
        if self._use_hidraw and self._fd >= 0:
            import os as _os
            _os.close(self._fd)
            self._fd = -1
        elif self._dev:
            self._dev.close()
            self._dev = None

    def write(self, data: bytes) -> int:
        """Write data to device. First byte must be the report ID."""
        if self._use_hidraw:
            import os as _os
            return _os.write(self._fd, data)
        return self._dev.write(data)

    def read(self, timeout_ms: int = 5000) -> bytes | None:
        """Read from device with timeout. Returns None on timeout."""
        if self._use_hidraw:
            import select
            ready, _, _ = select.select([self._fd], [], [],
                                        timeout_ms / 1000.0)
            if ready:
                import os as _os
                return _os.read(self._fd, 256)
            return None
        result = self._dev.read(512, timeout_ms)
        if result:
            return bytes(result)
        return None

    def read_ota(self, timeout_ms: int = 5000) -> bytes | None:
        """Read OTA response (report ID 5), filtering out keyboard reports."""
        deadline = time.monotonic() + timeout_ms / 1000.0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            if self._use_hidraw:
                import select
                ready, _, _ = select.select([self._fd], [], [],
                                            min(remaining, 0.1))
                if not ready:
                    continue
                import os as _os
                data = _os.read(self._fd, 256)
            else:
                ms = int(min(remaining, 0.1) * 1000)
                result = self._dev.read(512, max(ms, 1))
                if not result:
                    continue
                data = bytes(result)
            if len(data) > 0 and data[0] == REPORT_ID_OTA:
                return data

    def drain(self):
        """Discard any pending data."""
        if self._use_hidraw:
            import select, os as _os
            while True:
                ready, _, _ = select.select([self._fd], [], [], 0.05)
                if not ready:
                    break
                _os.read(self._fd, 256)
        else:
            while True:
                data = self._dev.read(512, 50)
                if not data:
                    break

    @property
    def packet_size(self) -> int:
        return 1 + self.report_size

    @property
    def display_name(self) -> str:
        if self._use_hidraw:
            return f"hidraw [{self.info['hidraw_path']}]"
        mfr = self.info.get('manufacturer_string', '') or ''
        prod = self.info.get('product_string', '') or ''
        path = self.path.decode() if isinstance(self.path, bytes) else self.path
        if mfr or prod:
            return f"{mfr} {prod}".strip() + f" [{path}]"
        return path


def probe_device(ota_dev: OTADevice):
    """Probe the OTA device: try reading and sending a start command."""
    print(f"\nProbing {ota_dev.display_name} (report size {ota_dev.report_size})...")

    try:
        ota_dev.open()
    except Exception as e:
        print(f"  Cannot open: {e}")
        return

    packet_size = ota_dev.packet_size

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
          dry_run: bool = False, delay_ms: float = 0,
          verbose: bool = False) -> bool:
    """Flash firmware via Telink OTA protocol.

    Args:
        delay_ms: Inter-packet delay in milliseconds (0 = no delay).
                  Use 1-5ms if the device reports fewer segments than sent.
        verbose: Log first N ACK payloads for debugging.
    """
    last_seg_idx = (fw_size - 1) // CHUNK_DATA_SIZE
    total_segments = last_seg_idx + 1
    total_packets = (total_segments + CHUNKS_PER_PACKET - 1) // CHUNKS_PER_PACKET
    packet_size = ota_dev.packet_size

    print(f"\n  Device:       {ota_dev.display_name}")
    print(f"  Segments:     {total_segments} ({CHUNK_DATA_SIZE} bytes each)")
    print(f"  Packets:      ~{total_packets}")
    print(f"  Report size:  {ota_dev.report_size} + 1 (report ID) = {packet_size} bytes")
    if delay_ms > 0:
        print(f"  Inter-packet delay: {delay_ms:.1f}ms")

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
        for j in range(min(3, total_segments)):
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

        last_idx = last_seg_idx
        complement = (0xFFFF - last_idx + 1) & 0xFFFF
        print(f"  End:   last_idx={last_idx} (0x{last_idx:04X}), "
              f"complement=0x{complement:04X}")
        return True

    try:
        ota_dev.open()
    except Exception as e:
        print(f"\nERROR: Cannot open device: {e}")
        if sys.platform == 'linux':
            print("  Check udev rules or run with sudo")
        return False

    # Re-read packet_size after open() which may adjust report_size
    packet_size = ota_dev.packet_size
    print(f"  Actual packet size: {packet_size} bytes")

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
        ota_dev.drain()
        ota_dev.write(bytes(start))

        resp = ota_dev.read_ota(timeout_ms=5000)
        if resp is None:
            print("ERROR: No OTA response to start command (is keyboard in OTA mode?)")
            return False
        print(f"  ACK: {resp[:12].hex(' ')}")

        # --- DATA ---
        ota_index = 0
        pkt_count = 0
        error_count = 0
        start_time = time.monotonic()

        while ota_index <= last_seg_idx:
            pkt = bytearray(packet_size)
            pkt[0] = REPORT_ID_OTA
            for i in range(1, packet_size):
                pkt[i] = 0xFF
            pkt[1] = 0x02
            pkt[3] = 0x00

            seg_count = 0
            for j in range(CHUNKS_PER_PACKET):
                if ota_index > last_seg_idx:
                    break

                seg = bytearray(18)
                seg[0] = ota_index & 0xFF
                seg[1] = (ota_index >> 8) & 0xFF
                offset = ota_index * CHUNK_DATA_SIZE
                for k in range(CHUNK_DATA_SIZE):
                    if offset + k < fw_size:
                        seg[2 + k] = fw_buf[offset + k]
                    else:
                        seg[2 + k] = 0xFF

                c = crc16(bytes(seg))
                base = 4 + 20 * j
                pkt[base:base + 18] = seg
                pkt[base + 18] = c & 0xFF
                pkt[base + 19] = (c >> 8) & 0xFF

                seg_count += 1
                ota_index += 1

            pkt[2] = seg_count * 20

            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)

            ota_dev.write(bytes(pkt))
            pkt_count += 1

            resp = ota_dev.read_ota(timeout_ms=10000)
            if resp is None:
                print(f"\nERROR: No OTA ACK for packet {pkt_count} "
                      f"(segments {ota_index - seg_count}-{ota_index - 1})")
                return False

            # Validate ACK content (Rainy75 protocol: error in resp[6] when
            # resp[2]==0x03 and resp[5]==0xFF)
            if len(resp) > 6 and resp[1] == 0x02:
                if resp[2] == 0x03 and resp[5] == 0xFF and resp[6] != 0:
                    print(f"\nERROR: Device reported OTA error code {resp[6]} "
                          f"at packet {pkt_count} (segment ~{ota_index})")
                    return False

            if verbose and pkt_count <= 5:
                print(f"\n  ACK[{pkt_count}]: {resp[:12].hex(' ')}")

            progress = min(100, ota_index * CHUNK_DATA_SIZE * 100 // fw_size)
            elapsed = time.monotonic() - start_time
            rate = (ota_index * CHUNK_DATA_SIZE / 1024) / elapsed if elapsed > 0 else 0
            sys.stdout.write(
                f"\r  [{progress:3d}%] {pkt_count}/{total_packets} packets | "
                f"seg {ota_index}/{total_segments} | "
                f"{elapsed:.1f}s | {rate:.1f} KB/s")
            sys.stdout.flush()

        elapsed = time.monotonic() - start_time
        print(f"\n  Data transfer complete: {pkt_count} packets, "
              f"{ota_index} segments in {elapsed:.1f}s")

        # --- END ---
        # last_idx is the 0-based index of the last segment sent (same as Rainy75)
        last_idx = ota_index - 1
        complement = (0xFFFF - last_idx + 1) & 0xFFFF

        print(f"Sending OTA end (last_idx={last_idx}, complement=0x{complement:04X})...")
        end = bytearray(packet_size)
        end[0] = REPORT_ID_OTA
        for i in range(1, packet_size):
            end[i] = 0xFF
        end[1] = 0x02
        end[2] = 0x06
        end[3] = 0x00
        end[4] = 0x02
        end[5] = 0xFF
        end[6] = last_idx & 0xFF
        end[7] = (last_idx >> 8) & 0xFF
        end[8] = complement & 0xFF
        end[9] = (complement >> 8) & 0xFF
        ota_dev.write(bytes(end))

        resp = ota_dev.read_ota(timeout_ms=10000)
        if resp is None:
            print("  No response (device may have rebooted with new firmware)")
            return True

        print(f"  END response: {resp[:12].hex(' ')}")

        # Success format from Rainy75: resp[2]==0x03, resp[5]==0xFF, resp[6]==0x00
        if (len(resp) >= 7 and resp[1] == 0x02
                and resp[2] == 0x03 and resp[5] == 0xFF):
            if resp[6] == 0x00:
                print("  OTA SUCCESS!")
                return True
            else:
                print(f"  OTA FAILED (error code: {resp[6]})")
                return False

        # Alternative: device echoes segment count in response
        if len(resp) >= 6 and resp[1] == 0x02:
            resp_count = resp[4] | (resp[5] << 8) if len(resp) >= 6 else 0
            if resp_count > 0 and resp_count != last_idx + 1:
                print(f"  WARNING: Device reports {resp_count} segments written, "
                      f"we sent {last_idx + 1}")
                print("  Possible data loss — try with --delay 3")
                return False
            elif resp_count == last_idx + 1:
                print(f"  Device confirmed {resp_count} segments. SUCCESS!")
                return True

        print("  (unrecognized response format — device may have accepted the image)")
        return True

    finally:
        ota_dev.close()


def main():
    parser = argparse.ArgumentParser(
        description='Wobkey Crush 80 OTA Firmware Flasher (Cross-Platform)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Examples:\n'
               '  %(prog)s firmware_patched.bin\n'
               '  %(prog)s --delay 5 firmware_patched.bin   (slower, more reliable)\n'
               '  %(prog)s --verbose firmware_patched.bin   (log ACK payloads)\n'
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
    parser.add_argument('--delay', type=float, default=2.0,
                        help='Inter-packet delay in ms (default: 2.0, 0=none)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Log first few ACK payloads for debugging')
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

    success = flash(ota_dev, fw_buf, fw_size, args.dry_run,
                    delay_ms=args.delay, verbose=args.verbose)

    if success and not args.dry_run:
        print("\nFlash complete. The keyboard should reboot automatically.")
        print("If it doesn't respond, unplug and replug the USB cable.")

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
