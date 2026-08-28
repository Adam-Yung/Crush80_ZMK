# Crush80 ZMK — Complete LED Investigation Record

## Document Purpose

This document captures the COMPLETE history of attempts to enable RGB LED support on the Wobkey Crush 80 keyboard running ZMK firmware. It is intended for future AI agents or developers who may attempt to solve this problem. Everything that was tried is documented here so work is not repeated.

---

## Board Specifications

| Property | Value |
|----------|-------|
| Keyboard | Wobkey Crush 80 (80% ANSI layout, 88 keys) |
| MCU | Telink TLSR9518 (B91 RISC-V), 48 MHz, 128KB ILM + 128KB DLM |
| Flash | 1 MB SPI NOR |
| LED Controller | AW20216S × 2 chips (154 LEDs total: 91 per-key + 63 underglow) |
| LED Power | MOSFET gate on PC2 (suspected active-HIGH) |
| SPI Pins (from Ghidra) | PE0=CS0, PE1=CLK, PE2=MOSI, PC0=CS1 |
| Matrix | 6 rows × 16 columns, col2row diode direction |
| Matrix Columns on PE | PE0 (col0), PE1 (col1), PE2 (col2) — SHARED with SPI! |
| BLE | Telink proprietary blob (liblt_9518_zephyr.a) |
| USB | B91 USB device at 0x80100800 |
| Bootloader | MCUboot at 0x0, app at 0x10000, slot1 at 0x80000 |
| Original Firmware | Evision/Telink-based, VIA-compatible, RGB working |
| Reference Board | Rainy 75 Pro (same B91 platform, but uses WS2812 LEDs not AW20216S) |

## How ZMK Was Installed

1. OTA bridge firmware flashed via stock Telink USB HID OTA protocol (usage page 0xFFEF)
2. Bridge provides MCUmgr SMP over USB CDC-ACM
3. ZMK application uploaded via `mcumgr image upload`
4. MCUboot handles swap-on-cold-boot (requires physical USB unplug/replug)
5. Auto-confirm via `mcuboot_confirm.c` after successful boot

## Current ZMK Status (Working)

- All 88 keys mapped correctly with Home Row Mods
- USB HID working
- BLE working (5 profiles)
- MCUmgr DFU working (upload, test, confirm)
- Mac mode (Fn+M toggle, layers 6-8)
- Deep sleep (15 min)
- ZMK Studio over BLE
- Battery ADC reporting
- **NO RGB LEDs** (all attempts failed)

---

## Pin Sharing Problem

The critical hardware constraint: **PE0, PE1, PE2 are used for BOTH the key matrix columns AND the AW20216S SPI bus.** The original firmware time-multiplexes these pins between matrix scanning and LED SPI communication. In ZMK, the kscan driver configures these as GPIO outputs at boot.

Any LED driver must:
1. Temporarily reconfigure PE1/PE2 for SPI output
2. Perform the SPI transaction
3. Restore PE1/PE2 to GPIO mode for kscan
4. Do this under `irq_lock()` to prevent kscan from scanning during SPI

---

## Ghidra Analysis of Original Firmware

Source: `firmware/Wobkey_Crush_80_Patched_Firmware/firmware/v2_patched.bin`

### LED Init Function (offset 0xF2B4)

The original firmware's LED initialization:
1. Configures PC2 as output HIGH (LED power MOSFET)
2. Configures PE0/PE1/PE2 as outputs
3. Writes to RF baseband registers (0x80140A00 area — initially mistaken for SPI config)
4. Calls GPIO init helper for all matrix column pins
5. Calls SPI transaction function at 0xE200 via function pointers at RAM 0xBC4/0xBC8
6. Calls AW20216S chip init at 0x18280

### HSPI Configuration (offset 0xF9D8)

Found ONE reference to HSPI registers (0x81FFFFC0) in the entire firmware:
```
0x81FFFFC2 |= 0x02  — Set bit 1 (quad mode / SCK output enable?)
0x81FFFFC0 &= 0xEF  — Clear bit 4 (master mode)
0x81FFFFC0 &= 0xFB  — Clear bit 2
```

### Pin Mux Registers (from firmware disassembly)

| Register | Value Written | Purpose |
|----------|--------------|---------|
| 0xE4002000 | \|= 0x00800000 | System clock gate |
| 0x80140333 | = (old & 0x3F) \| 0x40 | Pin mux: route HSPI to PE (bits[7:6]=01) |
| 0x8014030E | &= 0x7F | Enable alternate function routing |
| 0x81FFFFC2 | \|= 0x02 | HSPI mode2 bit 1 (SCK output? quad mode?) |
| 0x80140045 | = (old & 0xF0) \| (div & 0x0F) | Clock prescaler |

### Key Finding from SDK Analysis

The Telink B91 SDK's `hspi_set_pin_mux()` function only supports HSPI on:
- Port B: PB4=CLK, PB3=MOSI (function 0)
- Port A: PA2=CLK, PA4=MOSI (function 2)

**PE1/PE2 are NOT documented HSPI pins.** The original firmware uses an undocumented routing path via register 0x80140333. Whether this actually works is unconfirmed — we set all these registers and HSPI reports "transfer complete" but no LEDs respond.

---

## Complete Attempt History

### Attempt 1: GPIO Bit-Bang, Mode 0, Wrong Command Bytes (0xC0/0xC1/0xC2)
- **Result:** Keys broken on columns 0,1,2,13. No LEDs.
- **Cause:** `spi_pins_release()` set OEN to input mode, breaking kscan.

### Attempt 2: GPIO Bit-Bang, No OEN Changes
- **Result:** Keys work. No LEDs.
- **Analysis:** Correct approach for pin safety. Command bytes 0xC0/0xC1/0xC2 are wrong.

### Attempt 3: GPIO Bit-Bang, OEN Toggle
- **Result:** Keys broken again.
- **Cause:** Same OEN issue as attempt 1.

### Attempt 4: GPIO Bit-Bang, Correct Command Bytes (0xA0/0xA2/0xA4), Mode 0
- **Result:** Keys work. No LEDs.

### Attempt 5: GPIO Bit-Bang, CPOL=1 (CLK idles HIGH)
- **Result:** Keys work. No LEDs.
- **Note:** Based on misidentified register (RF register, not SPI).

### Attempt 6: HSPI Hardware, Mode 0, Basic Clock Enable
- **Result:** Keys work. No LEDs. HSPI status=0x40 (transfer complete), FIFOs empty.
- **Significance:** Proves HSPI hardware runs its state machine. But signals may not reach pins.

### Attempt 7: HSPI Hardware + gpio_input_en
- **Result:** Keys work. No LEDs.

### Attempt 8: HSPI Hardware + pad_mul_sel (0x80140355) + diagnostics
- **Result:** Keys work. No LEDs. All registers confirmed correct via readback.

### Attempt 9: HSPI Hardware, Mode 3 (CPOL=1, CPHA=1)
- **Result:** Keys work. No LEDs.

### Attempt 10: HSPI Hardware, Single Transaction + 50ms Power Delay
- **Result:** Keys work. No LEDs.
- **Note:** This attempt bricked the keyboard (HSPI busy-wait hung under irq_lock). Recovered via `force_recovery.py`.

### Attempt 11: HSPI with 5 Firmware-Disassembly Registers (0xE4002000, 0x80140333, 0x8014030E, 0x81FFFFC2, 0x80140045)
- **Result:** Keys work. No LEDs. SCK_OE initially read back as 0x00.
- **Cause:** `REG_HSPI_MODE2 = 0x00` was overwriting the SCK_OE bit set on the previous line (same register!).

### Attempt 12: HSPI with SCK_OE Fix (MODE2 = 0x02 to preserve bit 1)
- **Result:** Keys work. No LEDs. SCK_OE correctly reads back as 0x02 now.
- **Also:** Init used bit-bang while frames used HSPI — init never worked.

### Attempt 13: HSPI for BOTH Init and Frames
- **Result:** Keys work. No LEDs. All register values confirmed correct. No timeouts.

### Attempt 14: DIAGNOSTIC — GPIO Bit-Bang Cycling ALL 4 SPI Modes + Swapped Pins + Inverted PC2
- **Modes tested:**
  - Mode 0 (CPOL=0, CPHA=0), normal pins, PC2 HIGH → No LEDs
  - Mode 1 (CPOL=0, CPHA=1), normal pins, PC2 HIGH → No LEDs
  - Mode 2 (CPOL=1, CPHA=0), normal pins, PC2 HIGH → No LEDs
  - Mode 3 (CPOL=1, CPHA=1), normal pins, PC2 HIGH → No LEDs
  - Mode 0, SWAPPED pins (PE2=CLK, PE1=MOSI), PC2 HIGH → No LEDs
  - Mode 0, normal pins, PC2 LOW (inverted) → No LEDs
  - Mode 3, normal pins, PC2 LOW (inverted) → No LEDs
- **Result:** ZERO LED response to ANY configuration.

---

## What Was Definitively Proven

1. **GPIO CAN drive PE0/PE1/PE2** — kscan works on these columns (proven by typing)
2. **HSPI hardware "completes" transfers** — STATUS register shows end-of-transfer, FIFOs drain
3. **All register configurations match firmware disassembly** — verified via readback
4. **Safety timeouts prevent bricking** — no more infinite busy-waits
5. **No SPI mode works with bit-bang** — all 4 modes tested, normal and swapped pins
6. **PC2 polarity doesn't matter** — tried both HIGH and LOW
7. **The AW20216S does not respond** to any signal combination we can generate

---

## Remaining Hypotheses (Untested)

1. **Wrong pin assignment on this PCB revision** — The Ghidra analysis was done on the firmware binary which may target a different hardware revision. This specific Crush 80 unit might have the AW20216S connected to different pins entirely.

2. **AW20216S not populated** — The chip might physically not be on the board (cost-reduced variant?). Some keyboard manufacturers sell "RGB-ready" PCBs without the LED controller chips.

3. **PC2 is not the power pin** — Or the power MOSFET circuit has additional requirements (enable signal, voltage threshold).

4. **Physical damage** — Broken PCB trace, cold solder joint, ESD damage to the AW20216S.

5. **The HSPI-to-PE routing doesn't actually work** — Despite the firmware disassembly showing those register writes, the undocumented 0x80140333 routing might not function as assumed. The HSPI might generate signals internally but never connect to PE pads.

6. **Different AW20216S variant** — Some variants use I2C instead of SPI, or have a different slave address/protocol.

---

## What Would Resolve This

1. **Logic analyzer on PE1/PE2** (~$10 USB device) — Would definitively show if ANY signals appear on the physical pins during our SPI operations.

2. **Multimeter on PC2 and VLED** — Would confirm if LED power rail is active.

3. **Opening the keyboard** — Visual inspection to confirm AW20216S chips are populated and trace PE0/PE1/PE2 routing on the PCB.

4. **Testing with original firmware** — Flash the stock firmware back temporarily to confirm LEDs actually work on this specific unit.

---

## Key Files

| File | Purpose |
|------|---------|
| `zmk/src/crush80_rgb.c` | RGB driver (currently diagnostic mode, disabled in build) |
| `zmk/src/crush80_rgb.h` | Public API header |
| `zmk/drivers/led/aw20216s.c` | Alternative Zephyr SPI-based driver (unused) |
| `conf/app.conf` | `CONFIG_CRUSH80_RGB=n` (disabled) |
| `docs/ghidra_spi_extraction.md` | How SPI pins were identified |
| `scripts/force_recovery.py` | Emergency recovery if firmware hangs |
| `firmware/Wobkey_Crush_80_Patched_Firmware/` | Original firmware for analysis |

## Telink B91 SDK Source (Local)

```
/Users/adyung/Projects/crush80-workspace/modules/hal/hal_telink/tlsr9/drivers/B91/
  spi.c / spi.h          — SPI driver + hspi_set_pin_mux()
  gpio.h / gpio.c        — GPIO functions
  reg_include/spi_reg.h  — HSPI/PSPI register definitions
  reg_include/gpio_reg.h — GPIO register map + reg_gpio_func_mux
  reg_include/soc.h      — Clock enable registers
```

## Recovery Procedure (If Future LED Attempts Brick the Keyboard)

```bash
# 1. Plug in keyboard (within 2s window before hang)
python3 scripts/force_recovery.py
# 2. Unplug, wait 2s, replug (MCUboot enters serial recovery)
# 3. Upload working firmware:
~/go/bin/mcumgr --conntype serial --connstring "dev=$(python3 -c \"import glob; p=glob.glob('/dev/cu.usbmodem*') or glob.glob('/dev/ttyACM*'); print(p[0])\")),baud=115200" image upload dist/crush80-zmk-app.signed.MACMODE-WORKING.bin
# 4. Unplug/replug to boot new firmware
```

## CRITICAL Safety Rule

**NEVER use unbounded busy-waits inside irq_lock().** Always use:
```c
for (int t = 0; t < 10000 && (REG & BIT); t++) {}
if (t >= 10000) { /* timeout — bail out, don't hang */ }
```
