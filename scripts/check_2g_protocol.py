#!/usr/bin/env python3
"""
Check Crush 80 firmware for Telink 2.4GHz TPLL/GenFSK access codes
and pairing data, to assess 2.4G dongle feasibility.
"""
import struct

FW_PATH = "../firmware/v2_patched.bin"
OTA_PATH = "../firmware/code_2M_v2_patched.bin"

with open(FW_PATH, 'rb') as f:
    fw = bytearray(f.read())

# Known Telink TPLL access codes from official SDK demos
access_codes = {
    0x29417671: "Default Telink TPLL demo code",
    0x71764129: "Default reversed",
    0xd6be898e: "Telink demo code 2",
    0x8e89bed6: "Telink demo code 2 reversed",
    0xAAAAAAAA: "Simple alternating",
    0x55555555: "Simple alternating 2",
}

print("=== Searching for Telink access codes in firmware ===")
for code, name in access_codes.items():
    hits = []
    for i in range(len(fw) - 3):
        if struct.unpack_from('<I', fw, i)[0] == code:
            hits.append(f"0x{i:05X}")
    if hits:
        print(f"  0x{code:08X} ({name}): {hits}")

print()
print("=== Searching for RF channel table patterns ===")
# Telink keyboard 2.4G typically hops among 4-8 channels
# Common channel sets: [5, 17, 35, 72], [10, 30, 50, 70], etc
# Store as single bytes in a small table
channel_sets = [
    bytes([5, 17, 35, 72]),
    bytes([10, 30, 50, 70]),
    bytes([0x05, 0x11, 0x23, 0x48]),
    bytes([0x11]),  # channel 17 alone
]
for cset in channel_sets:
    for i in range(len(fw) - len(cset)):
        if fw[i:i+len(cset)] == cset:
            ctx = fw[max(0, i-4):i+len(cset)+8].hex()
            print(f"  Channel pattern {cset.hex()} at 0x{i:05X}: context {ctx}")

print()
print("=== Checking OTA image calibration and MAC regions ===")
with open(OTA_PATH, 'rb') as f:
    ota = bytearray(f.read())
print(f"OTA image size: {len(ota)}")

# Flash at 0xFF000 = BLE MAC in Telink chips (6 bytes)
# OTA image has 256-byte header at start
mac_flash_addr = 0xFF000
mac_ota_offset = 0x100 + mac_flash_addr
if mac_ota_offset + 8 <= len(ota):
    mac_bytes = ota[mac_ota_offset:mac_ota_offset+8]
    mac_str = ':'.join(f'{b:02x}' for b in reversed(mac_bytes[:6]))
    print(f"BLE MAC region at flash 0x{mac_flash_addr:X} (OTA 0x{mac_ota_offset:X}): {mac_bytes.hex()} => {mac_str}")

# RF calibration at 0xFE000
cal_flash_addr = 0xFE000
cal_ota_offset = 0x100 + cal_flash_addr
if cal_ota_offset + 32 <= len(ota):
    cal = ota[cal_ota_offset:cal_ota_offset+32]
    print(f"RF cal at flash 0x{cal_flash_addr:X} (OTA 0x{cal_ota_offset:X}): {cal.hex()}")

print()
print("=== TPLL Protocol Analysis Summary ===")
print("""
The Evision/Wobkey 2.4G protocol is almost certainly Telink TPLL (Telink Primary Link Layer).
This is the standard Telink proprietary 2.4G HID protocol used across all their keyboard/dongle solutions.

Key facts about TPLL:
- Physical layer: B91 RF hardware in RF_PRIVATE_1M or RF_PRIVATE_2M mode
- RF drivers: OPEN SOURCE (Apache 2.0) in tl_platform_sdk / libdriver.a
- Link layer: NOT a blob — it's a documented state machine (PTX/PRX with ACK)
- Pairing: access code + device address, negotiated on a fixed pairing channel
- Frequency hopping: typically 4-8 channels, programmed into the keyboard at manufacture

What needs to be reverse-engineered from the dongle:
1. Access code (4 bytes) — may be the default 0x29417671 or per-device
2. Channel table (4-8 bytes)
3. Packet format: header length bits, payload layout (should be standard TPLL)
4. Pairing handshake if not using fixed access code

What does NOT need a blob:
- The RF physical layer is fully open-source in libdriver.a / rf.h
- The TPLL protocol logic is a simple state machine (PTX sends, PRX acks)
- No proprietary stack is required — just the open-source RF driver + state machine

Compare with BLE:
- BLE blob = full Bluetooth LE link layer + HCI (complex, ~2.8 MB compiled)
- TPLL = ~2 KB of state machine code on top of open-source RF driver
""")
