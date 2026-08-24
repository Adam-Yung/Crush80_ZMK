---
name: crush80-firmware
description: >-
  Build, flash, and debug the Wobkey Crush 80 ZMK firmware (Telink TLSR9518 B91).
  Use when working on Crush 80 keyboard firmware, flashing via mcumgr/SMP,
  debugging matrix issues, or modifying the board DTS/keymap.
disable-model-invocation: true
---

# Crush 80 ZMK Firmware

## Overview

- Wobkey Crush 80 keyboard running custom ZMK firmware on Telink TLSR9518 (B91, RISC-V)
- West workspace at `/Users/adyung/Projects/crush80-workspace`
- Repo at `/Users/adyung/Adam/Crush80_ZMK`
- Serial port: `/dev/cu.usbmodem1101` (USB CDC-ACM)
- Keymap config source of truth: `~/.config/DOTFILES/keybindings/crush80-zmk/`
- `build.sh` syncs from dotfiles before building — always edit config THERE

## Hardware Details

- **MCU**: Telink TLSR9518 (B91, RISC-V), 48MHz
- **Matrix**: 6 rows x 16 columns, col2row diodes, 88 keys (ANSI TKL)
- **Column GPIOs** (in order): PE0, PE1, PE2, PE4, PE5, PE6, PB0, PB1, PB2, PB3, PB4, PB5, PB6, PC0, PC1, PC4
- **Row GPIOs** (in order): PD7, PD2, PD3, PD4, PD5, PD6
- **LED driver**: 2x AW20216S via HSPI SPI bus
  - PE0 = CS chip 0, PE1 = CLK, PE2 = MOSI, PC0 = CS chip 1, PC2 = LED power
  - 91 per-key RGB LEDs + 63 underglow/side LEDs = 154 total
- **Battery**: ADC on PD1 (channel 0x0A, half-divider)
- **BLE**: Telink proprietary controller (liblt_9518_zephyr.a)

## CRITICAL SAFETY RULES

1. **PE0/PE1/PE2 are shared** between matrix columns AND LED SPI. NEVER enable Zephyr's `&hspi` device (`status = "okay"`) — it causes a fatal pinctrl conflict at boot that bricks the keyboard with no USB recovery. RGB must use GPIO bit-banging only.

2. **MCUboot swap requires PHYSICAL unplug/replug** (cold boot). Software `mcumgr reset` does NOT trigger the swap on B91. After uploading + marking pending, the user MUST unplug and replug.

3. **Never set `CONFIG_LOG_DEFAULT_LEVEL=4`** — floods serial, bricks SMP.

4. **Always keep a backup**: `cp dist/crush80-zmk-app.signed.bin dist/crush80-zmk-app.signed.BACKUP.bin` before flashing experimental firmware.

5. **If keyboard is completely dead** (no USB): drain power fully (unplug 10+ seconds), then use recovery flash script with immediate replug.

## Build

```bash
cd /Users/adyung/Adam/Crush80_ZMK
bash build.sh --skip-bridge --skip-mcuboot
```

Output: `dist/crush80-zmk-app.signed.bin`

## Flash (CORRECT PROCEDURE)

The B91 MCUboot requires a COLD BOOT (physical power cycle) to perform image swap. Software reset is NOT sufficient.

```bash
# 1. Upload to slot 1
~/go/bin/mcumgr --conntype serial --connstring "dev=/dev/cu.usbmodem1101,baud=115200" \
  image upload dist/crush80-zmk-app.signed.bin

# 2. Get slot 1 hash
~/go/bin/mcumgr --conntype serial --connstring "dev=/dev/cu.usbmodem1101,baud=115200" image list

# 3. Mark pending (replace HASH with slot 1 hash from step 2)
~/go/bin/mcumgr --conntype serial --connstring "dev=/dev/cu.usbmodem1101,baud=115200" \
  image test HASH

# 4. PHYSICALLY UNPLUG the keyboard, wait 3 seconds, plug back in
#    (This triggers MCUboot to perform the swap)

# 5. Wait 15 seconds for MCUboot swap + app boot, then confirm:
~/go/bin/mcumgr --conntype serial --connstring "dev=/dev/cu.usbmodem1101,baud=115200" \
  image confirm ""
```

**IMPORTANT**: If step 5 times out, the keyboard might need another unplug/replug. If you don't confirm, the NEXT cold boot will revert to the old image.

## Flash (alternative: direct write via smp_flash)

The Go `smp_flash` tool writes MCUboot+app directly to staging area then commits (erases bank 0, copies, resets). This bypasses the swap mechanism entirely:

```bash
cd scripts/smp_flash
./smp_flash -port /dev/cu.usbmodem1101 -dist ../../dist -commit=true
```

Note: This tool sometimes has verify errors. If it fails, try again or use the mcumgr approach above.

## Flash (recovery — keyboard completely dead)

```bash
bash scripts/flash_bin.sh --recovery dist/crush80-zmk-app.signed.BACKUP.bin
# Then unplug keyboard, run script, plug back in when prompted
```

If the keyboard doesn't enumerate at all: drain power completely (unplug for 10+ seconds), then try the recovery script.

## Key Files

| File | Purpose |
|------|---------|
| `zmk/boards/crush80/crush80.dts` | Board DTS with GPIO assignments and matrix transform |
| `zmk/boards/crush80/crush80.keymap` | Key bindings (synced from dotfiles) |
| `conf/app.conf` | ZMK application Kconfig (synced from dotfiles) |
| `build.sh` | Build script (syncs from dotfiles first) |
| `flash.sh` | Flash script (uses mcumgr) |
| `scripts/flash_bin.sh` | Flash any .bin with --recovery support |
| `scripts/smp_flash/` | Go-based custom SMP flasher (flash_mgmt group 64) |
| `dist/crush80-zmk-app.signed.BACKUP.bin` | Known-good firmware backup |

## GPIO Pin Source

Extracted from original Crush 80 firmware binary (github.com/Desz01ate/Wobkey_Crush_80_Patched_Firmware) by analyzing GPIO init calls at firmware offset 0xF078-0xF188. The helper `FUN_ram_0001a140(arg, dir)` encodes: `arg>>8 = port` (0=A,1=B,2=C,3=D,4=E), `arg&0xFF = pin bitmask`.

## LED/RGB Notes

- HSPI CANNOT be enabled as a Zephyr device (pinctrl conflict bricks keyboard)
- RGB must be implemented using manual GPIO bit-banging of PE0(CS), PE1(CLK), PE2(MOSI)
- The bit-bang code must: pause kscan → configure PE0/PE1/PE2 as GPIO outputs → bit-bang SPI → restore PE0/PE1/PE2 for kscan → resume kscan
- AW20216S protocol: SPI Mode 0/3, 1MHz, MSB first, address+data bytes
- LED channel mapping table at firmware offset 0x1C8F4 (91 entries)
- Stock firmware does the same pin-sharing via time-multiplexing

## Known Issues

1. MCUboot swap requires cold boot (unplug/replug), not software reset
2. `mcumgr echo` may timeout if firmware has debug logging enabled
3. SMP timeouts sometimes require multiple retries or unplug/replug
