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

## Hardware Details

- **MCU**: Telink TLSR9518 (B91, RISC-V), 48MHz
- **Matrix**: 6 rows x 16 columns, col2row diodes, 88 keys (ANSI TKL)
- **Column GPIOs** (in order): PE0, PE1, PE2, PE4, PE5, PE6, PB0, PB1, PB2, PB3, PB4, PB5, PB6, PC0, PC1, PC4
- **Row GPIOs** (in order): PD7, PD2, PD3, PD4, PD5, PD6
- **LED driver**: 2x AW20216S via HSPI (DISABLED — PE0/PE1/PE2 are shared with matrix columns)
- **Battery**: ADC on PD1 (channel 0x0A, half-divider)

**CRITICAL**: PE0, PE1, PE2 serve as BOTH matrix columns AND SPI pins for LEDs. HSPI must remain disabled in DTS while keyboard matrix is active. Future RGB implementation needs time-multiplexing.

## Build

```bash
cd /Users/adyung/Adam/Crush80_ZMK
bash build.sh --skip-bridge --skip-mcuboot
```

Output: `dist/crush80-zmk-app.signed.bin`

## Flash (normal — SMP working)

```bash
~/go/bin/mcumgr --conntype serial --connstring "dev=/dev/cu.usbmodem1101,baud=115200" image upload dist/crush80-zmk-app.signed.bin

# Get slot 1 hash:
~/go/bin/mcumgr --conntype serial --connstring "dev=/dev/cu.usbmodem1101,baud=115200" image list

# Mark pending (replace HASH):
~/go/bin/mcumgr --conntype serial --connstring "dev=/dev/cu.usbmodem1101,baud=115200" image test HASH

# Reset:
~/go/bin/mcumgr --conntype serial --connstring "dev=/dev/cu.usbmodem1101,baud=115200" reset

# Wait 12s for MCUboot swap, then confirm:
~/go/bin/mcumgr --conntype serial --connstring "dev=/dev/cu.usbmodem1101,baud=115200" image confirm ""
```

## Flash (recovery — SMP blocked by log flood or bad firmware)

If SMP is unresponsive (NMP timeout), use the unplug/replug race:

```bash
cd /Users/adyung/Adam/Crush80_ZMK && python3 -c "
import glob, time, subprocess, sys
print('Waiting for keyboard... plug it in now')
found_at = None
for i in range(120):
    ports = glob.glob('/dev/cu.usbmodem*')
    if ports:
        if found_at is None:
            found_at = time.time()
            print('Port appeared, waiting for stability...')
        elif time.time() - found_at > 2.5:
            print(f'Port stable! Uploading...')
            r = subprocess.run(['/Users/adyung/go/bin/mcumgr', '--conntype', 'serial',
                '--connstring', f'dev={ports[0]},baud=115200',
                'image', 'upload', 'dist/crush80-zmk-app.signed.bin'], timeout=300)
            sys.exit(r.returncode)
    else:
        found_at = None
    time.sleep(0.5)
print('Timeout')
"
```

Then unplug keyboard, run the script, plug keyboard back in.

## CRITICAL: Never enable CONFIG_LOG_DEFAULT_LEVEL=4

Setting `CONFIG_LOG_DEFAULT_LEVEL=4` floods the CDC-ACM serial port with USB/BLE/OS debug logs, completely blocking SMP protocol communication. This makes the keyboard unflashable via normal means (requires physical unplug/replug race to recover). Only use `CONFIG_ZMK_LOGGING_MINIMAL=y` or at most `CONFIG_ZMK_LOG_LEVEL_DBG=y` WITHOUT changing `LOG_DEFAULT_LEVEL`.

## Key Files

| File | Purpose |
|------|---------|
| `zmk/boards/crush80/crush80.dts` | Board DTS with GPIO assignments and matrix transform |
| `zmk/boards/crush80/crush80.keymap` | Key bindings |
| `conf/app.conf` | ZMK application Kconfig |
| `build.sh` | Build script |
| `scripts/smp_flash/` | Go-based custom SMP flasher (backup, uses flash_mgmt group 64) |

## GPIO Pin Source

Column and row GPIO assignments were extracted from the original Crush 80 firmware binary (github.com/Desz01ate/Wobkey_Crush_80_Patched_Firmware) by analyzing GPIO init calls at firmware offset 0xF078–0xF188. The Ghidra helper `FUN_ram_0001a140(arg, dir)` encodes pins as: `arg>>8 = port` (0=A, 1=B, 2=C, 3=D, 4=E), `arg&0xFF = pin bitmask`.

## VIA Config Note

The VIA JSON config reports "rows: 8, cols: 16" but the actual hardware uses 6 rows. The original firmware's scan function reads PD_INPUT 5 times and PE_INPUT once (not used in ZMK because PE pins are columns). The VIA "8 rows" includes 2 phantom rows for padding.
