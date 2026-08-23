                                        # OTA Flash Debug Context
                                          
## Goal
Flash custom ZMK firmware (OTA bridge) to Crush 80 keyboard via Telink B91 USB HID OTA protocol.

## Current Status: BLOCKED
The OTA data transfer completes successfully (all 2045 packets ACKed with report ID 0x05), but after power cycle the keyboard still boots stock firmware. Bank 1 is either not being written correctly, or the boot ROM still rejects it.

## What Works
- Keyboard detected: RDR Crush 80, VID=0x320F, PID=0x5055
- OTA protocol communication works (report ID 5, usage page 0xFFEF)
- START command gets proper ACK (echo back): `05 02 02 00 01 ff...`
- DATA packets all get report ID 0x05 ACKs at 15.6 KB/s
- END command gets response: `05 02 3c 00 d9 17 83 c7 14 10 93 f7`
- macOS hidapi access works via Interface 1 (usage page 0xFF60), device routes report ID 5 internally

## What Doesn't Work
- After OTA + power cycle, keyboard boots stock firmware (same HID device, 9 interfaces)
- No CDC-ACM serial device appears (expected if bridge firmware booted)
- Boot ROM at bank 0 does not swap to bank 1

## Key Files
- `scripts/flash_ota.py` — OTA flasher (cross-platform, hidapi-based)
- `dist/crush80-ota-bridge.bin` — raw bridge binary (98,116 bytes, unpatched)
- `dist/crush80-ota-bridge_ota.bin` — OTA-ready binary (98,132 bytes, patched header+CRC)
- `scripts/flash_stage2.py` — SMP serial client for stage 2 (not yet used)

## OTA Image Preparation (from Rainy75 reference)
Based on `/tmp/rainy75-zmk/reverse/tools/prepare_ota.py`:
1. Verify TLNK magic at offset 0x20 ✓
2. Patch CRC type at offset 0x06 to `5d 02` ✓
3. Pad body to 16-byte alignment ✓ (12 bytes added)
4. Set OTA size at offset 0x18 = total_size including CRC trailer ✓ (98132 = 0x17F54)
5. Append Telink CRC32 (no final XOR) ✓ (0x15CBACCC)
6. Verified: `binascii.crc32(data[:fw_size]) == 0xFFFFFFFF` (correct for Telink CRC)

## Patched Binary Header (first 48 bytes)
```
0000: 25 a0 00 00 00 00 5d 02 00 00 00 00 00 00 00 00
0010: 00 00 00 00 00 00 00 00 54 7f 01 00 00 00 00 00
0020: 4b 4e 4c 54 00 00 3b 17 f3 22 a0 7c 93 e2 12 00
```
- 0x00: `25 a0 00 00` — RISC-V jump instruction
- 0x06: `5d 02` — CRC type (patched)
- 0x18: `54 7f 01 00` — OTA size = 0x17F54 = 98132 (patched)
- 0x20: `4b 4e 4c 54` — TLNK magic ("KNLT")

## OTA Protocol Details (Crush 80 variant)
Interface: macOS opens Interface 1 (usage page 0xFF60), report ID 5 is routed internally.

### Packet Format
- Report size: 64 bytes + 1 byte report ID = 65 bytes per write
- Padding: 0xFF

### START: `[05] 02 02 00 01 FF FF...`
- ACK: echo back of start packet

### DATA: `[05] 02 <len> 00 [seg0][seg1][seg2]`
- Each segment: `[idx_lo idx_hi] [16 bytes data] [crc16_lo crc16_hi]` = 20 bytes
- Up to 3 segments per packet (len = 0x3C for 3 segments)
- CRC16: polynomial 0xA001, init 0xFFFF, over [index(2) + data(16)]
- ACK: report ID 0x05 response for each packet

### END: `[05] 02 06 00 02 FF [count_lo count_hi] [neg_lo neg_hi] FF...`
- count = last segment index (0-based) = 6133
- neg = two's complement = (0x10000 - count) & 0xFFFF = 59403
- Response received: `05 02 3c 00 d9 17 83 c7 14 10 93 f7`
  - NOT the expected success format (`02 03 00 xx FF 00`)
  - `d9 17` = 0x17D9 = 6105 (NOT matching our 6133 count — possible error indicator?)

## Hypotheses for Failure

### 1. END response indicates error (MOST LIKELY)
The end response `05 02 3c 00 d9 17...` doesn't match success format. The value `0x17D9 = 6105` at bytes [4:6] might be the last segment the device actually received/wrote before encountering an error. If the device only wrote 6105 of 6134 segments, the image on flash is truncated/corrupt.

Possible causes:
- The device's internal flash write buffer is overflowing because we send data too fast
- The OTA handler has a maximum image size smaller than 98KB
- A CRC16 mismatch occurred silently at segment ~6105

### 2. The Crush 80 OTA handler writes to a different address
The Rainy75 uses bank 1 at 0x40000. The Crush 80 (same SoC but different vendor firmware) might use a different flash layout. The stock firmware might write OTA data somewhere the boot ROM doesn't check.

### 3. Boot ROM validation differs from Rainy75
The Crush 80's stock firmware might have a modified boot ROM or multi-stage bootloader that checks additional fields beyond offset 0x06/0x18/0x20.

### 4. The OTA handler requires a different END command format
The Crush 80 might need additional fields in the END command, or a different finalization sequence (e.g., a separate "commit" command after END).

## Debugging Next Steps

### Priority 1: Decode the END response
- The response `05 02 3c 00 d9 17 83 c7 14 10 93 f7` needs to be understood
- `0x17D9 = 6105` segments × 16 bytes = 97,680 bytes — this is less than our 98,132
- Theory: device reports how many segments it actually wrote. If 6105 < 6134, data was lost
- Try: slow down the transfer (add delays between packets) to see if count improves
- Try: read back flash after OTA to verify data was written

### Priority 2: Try the Rainy75 flasher directly
- The Rainy75 repo has `reverse/tools/ota_flasher.py` at `/tmp/rainy75-zmk/`
- It was written for Linux (hidraw) but the protocol is the same
- Compare its exact packet timing and format — it reads and validates each ACK

### Priority 3: Check if per-packet ACK content reveals errors
- Our script accepts any report ID 5 response as ACK but doesn't check the content
- Log the first few ACK payloads to see if they contain error codes or segment confirmations
- The Rainy75 flasher checks: `resp[2]==0x03 and resp[5]==0xFF and resp[6]==error_code`

### Priority 4: Investigate flash layout
- The stock firmware's OTA handler might write to an offset other than 0x40000
- Try: use the Rainy75's `mem_reader.py` or similar tool to read flash after OTA
- The wob_probe.py tool might have commands to query the device state

### Priority 5: Try smaller test image
- Flash a tiny test binary (e.g., 1KB) that just has the boot header + NOPs
- If a small image boots, the issue is size-related (buffer overflow, flash boundary)
- If even a small image doesn't boot, the issue is with boot ROM validation

## Reference Implementation
The Rainy75 ZMK repo is cloned at `/tmp/rainy75-zmk/` (GitHub: https://github.com/scholzri/rainy75-zmk)

Key files:
- `reverse/tools/prepare_ota.py` — header patching (we replicated this)
- `reverse/tools/ota_flasher.py` — Linux-only OTA flasher with proper ACK validation
- `reverse/tools/wob_probe.py` — device probing/query tool
- `reverse/tools/mem_reader.py` — flash memory reader
- `build.sh` lines 179-207 — bridge build and OTA preparation

## Environment
- macOS (darwin 25.5.0)
- Python 3 with `hidapi` package installed
- Workspace: `/Users/adyung/Adam/Crush80_ZMK`
