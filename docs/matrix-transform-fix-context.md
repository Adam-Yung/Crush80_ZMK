# Crush 80 ZMK — Matrix Transform Fix Context

## Current State: FULLY FUNCTIONAL (RESOLVED)

All 88 keys scan correctly. The GPIO pin assignments have been corrected based on
reverse engineering of the original Crush 80 firmware binary.

### Resolution Summary
The original DTS copied GPIO assignments from the Rainy 75 Pro, but the Crush 80
uses DIFFERENT pins for 8 of 22 GPIOs:
- Columns: PE0,PE1,PE2,PE4,PE5,PE6,PB0,PB1,PB2,PB3,PB4,PB5,PB6,PC0,PC1,PC4
  (was: PE4-PE7,PA0-PA4,PB1-PB6,PC1 — PA0-PA4 and PE7 don't exist on this PCB)
- Rows: PD7,PD2,PD3,PD4,PD5,PD6
  (was: PE0,PD2-PD6 — PE0 is actually a column, PD7 is the first row)
- HSPI must be disabled because PE0/PE1/PE2 are shared with matrix columns

### How It Was Fixed
1. Cloned original firmware from github.com/Desz01ate/Wobkey_Crush_80_Patched_Firmware
2. Found GPIO init calls at firmware offset 0xF078-0xF188
3. Decoded using: FUN_ram_0001a140(arg,dir) where arg>>8=port, arg&0xFF=pin_mask
4. Updated crush80.dts col-gpios and row-gpios to match

## What Works

- MCUboot at flash 0x0, boots ZMK app at 0x10000
- USB HID keyboard (VID=1d50, PID=615e, "Crush 80")
- All keys physically scan and produce HID reports
- CDC-ACM serial port (`/dev/cu.usbmodem1101`) with mcumgr SMP
- `mcumgr echo` and `mcumgr reset` work over serial
- Rebuild + re-flash is easy: `bash build.sh --skip-bridge --skip-mcuboot` then use smp_flash tool



## The Problem

The `default_transform` in `zmk/boards/crush80/crush80.dts` maps `RC(row, col)` positions to logical key indices consumed by the keymap. The GPIO column/row assignments don't match the actual PCB traces, so pressing physical key X triggers the wrong `RC()` position.

### Observed Symptoms

- Physical T key → outputs W
- Physical U → O, I → P, O → [, P → ]
- Physical D → Esc (logical position 0)
- Physical E → Tab
- Physical Super/Win → Left Arrow
- The scramble is NOT a simple uniform offset — different regions of the board have different offsets



### Root Cause

The column and/or row GPIO pin order in the DTS doesn't match how the PCB actually routes traces to the key switch matrix. This is common when porting ZMK to a new board without full schematic access.

## Hardware Details

- MCU: Telink TLSR9518 (B91, RISC-V)
- Matrix: 6 rows × 16 columns, col2row diodes
- 88 keys total (ANSI TKL layout)



### Current GPIO Assignments (likely wrong order)

```dts
col-gpios  (columns 0-15):
  PE4, PE5, PE6, PE7, PA0, PA1, PA2, PA3, PA4, PB1, PB2, PB3, PB4, PB5, PB6, PC1

row-gpios  (rows 0-5):
  PE0, PD2, PD3, PD4, PD5, PD6
```



### Matrix Transform (current, incorrect)

```
Row 0: RC(0,0) RC(0,1) ... RC(0,15)     — F-row
Row 1: RC(1,0) RC(1,1) ... RC(1,13) RC(1,14) RC(1,15) RC(3,14)  — number + nav
Row 2: RC(2,0) RC(2,1) ... RC(2,13) RC(2,14) RC(2,15) RC(3,15)  — QWERTY + nav
Row 3: RC(3,0) RC(3,1) ... RC(3,11) RC(3,13)  — home row
Row 4: RC(4,0) RC(4,2) ... RC(4,11) RC(4,13) RC(4,14)  — shift row
Row 5: RC(5,0) RC(5,1) RC(5,2) RC(5,5) RC(5,9) RC(5,10) RC(5,11) RC(5,13) RC(5,14) RC(5,15)
```



## How to Fix



### Option A: Diagnostic Firmware (Recommended)

Build a firmware that logs the raw `(row, col)` for each keypress to the serial console. Then press every key systematically to build the correct mapping.

1. Add a debug overlay or modify the kscan driver to print scan events
2. Connect to `/dev/cu.usbmodem1101` at 115200 baud
3. Press each physical key, note which `(row, col)` it reports
4. Build the correct transform from the data

Alternatively, use ZMK's existing kscan debug logging:

```
CONFIG_ZMK_KSCAN_EVENT_LOG=y
CONFIG_LOG=y
CONFIG_LOG_PROCESS_THREAD_SLEEP_MS=50
```



### Option B: Systematic Key Testing

1. Open a key tester (e.g., [https://keyboard-test.space](https://keyboard-test.space))
2. Press every key on the board one at a time, left-to-right, top-to-bottom
3. Record what each physical key outputs
4. From the output → keymap → logical position → RC() mapping, compute the actual GPIO↔column correspondence
5. Reorder `col-gpios` (and possibly `row-gpios`) to match



### Option C: Compare with Rainy 75

The Rainy 75 (same MCU, same vendor Wobkey/RDR) likely shares similar matrix wiring. The Rainy 75 repo is at `/tmp/rainy75-zmk/` (if still cloned) or [https://github.com/scholzri/rainy75-zmk](https://github.com/scholzri/rainy75-zmk). Compare its GPIO assignments.

## Re-flash Procedure (now trivial)

After fixing the DTS and rebuilding:

```bash
# 1. Rebuild (only ZMK app, MCUboot unchanged)
cd /Users/adyung/Adam/Crush80_ZMK
bash build.sh --skip-bridge --skip-mcuboot

# 2. Flash via mcumgr (MCUboot handles it)
~/go/bin/mcumgr --conntype serial \
  --connstring "dev=/dev/cu.usbmodem1101,baud=115200" \
  image upload dist/crush80-zmk-app.signed.bin

# 3. Confirm and reset
~/go/bin/mcumgr --conntype serial \
  --connstring "dev=/dev/cu.usbmodem1101,baud=115200" \
  image confirm

~/go/bin/mcumgr --conntype serial \
  --connstring "dev=/dev/cu.usbmodem1101,baud=115200" \
  reset
```

**Note:** The `image upload`/`confirm` commands use the standard MCUboot image management group. If they return "Error: 8" (not supported), use the custom Go tool instead:

```bash
cd scripts/smp_flash
./smp_flash -port /dev/cu.usbmodem1101 -dist ../../dist -commit=true
```

This erases staging, writes the combined MCUboot+app, then commits (erases bank 0, copies, resets).

## Key Files


| File                               | Purpose                                              |
| ----------------------------------- | ---------------------------------------------------- |
| `zmk/boards/crush80/crush80.dts`    | Board definition with matrix transform + kscan GPIOs |
| `zmk/boards/crush80/crush80.keymap` | Key bindings (correct, assuming transform is fixed)  |
| `conf/app.conf`                     | ZMK application config                               |
| `build.sh`                          | Build script                                         |
| `scripts/smp_flash/smp_flash`       | Go-based SMP flasher for custom flash_mgmt commands  |
| `dist/crush80-zmk-app.signed.bin`   | Built ZMK app (re-generated by build.sh)             |




## Build Environment

- macOS (darwin 25.5.0, arm64)
- West workspace: `/Users/adyung/Projects/crush80-workspace`
- Zephyr SDK: `/Users/adyung/zephyr-sdk-0.17.0`
- Python: `/Users/adyung/miniforge3/bin/python3`
- Go: `go1.26.5`, mcumgr at `~/go/bin/mcumgr`



## What Was Accomplished in This Session

1. Fixed OTA flash script (Linux hidraw support, proper ACK validation)
2. Successfully OTA-flashed bridge firmware to bank 1 via Linux
3. Discovered mcumgr SMP serial works via Go CLI (Python framing was wrong)
4. Built custom Go SMP flasher (`scripts/smp_flash/`) using newtmgr serial protocol
5. Wrote MCUboot + ZMK app to staging area via flash_mgmt commands
6. Committed: RAM trampoline erased bank 0, copied firmware, reset MCU
7. Keyboard now boots MCUboot → ZMK successfully



## Session History Reference

Previous debug context: `docs/ota-flash-debug-context.md`
This session's chat is in the agent-transcripts folder.