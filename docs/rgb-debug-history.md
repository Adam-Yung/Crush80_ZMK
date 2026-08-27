# RGB LED Debug History — Crush80 ZMK

## Recovery Procedure (PROVEN — 2026-08-27)

The RGB LED driver used `irq_lock()` with a busy-wait (`while (REG_HSPI_STATUS & HSPI_BUSY) {}`) that never completed. This caused the ENTIRE system to hang ~2 seconds after boot — USB died, BLE died, keyboard stopped typing. Normal `mcumgr image upload` couldn't complete because the system froze mid-transfer.

### How force_recovery.py Saved the Keyboard

1. Plugged in the bricked keyboard (system hangs after ~2s but USB enumerates briefly)
2. Ran `python3 scripts/force_recovery.py` within the 2-second window
3. Script sent ONE flash_mgmt erase command (group 64, cmd 0) to erase slot 0 header at 0x10000
4. Unplugged, waited 2 seconds, replugged
5. MCUboot found no valid app → entered serial recovery mode (CONFIG_BOOT_SERIAL_NO_APPLICATION=y)
6. Uploaded working firmware: `mcumgr image upload dist/crush80-zmk-app.signed.MACMODE-WORKING.bin`
7. Unplugged, replugged → keyboard booted normally with working firmware

### Why Normal Recovery Failed

- `mcumgr image upload` needs hundreds of SMP round-trips to upload a full image
- System hangs after ~2 seconds, killing SMP mid-transfer
- `force_recovery.py` only needs ONE command to land in that 2-second window
- After erasing the header, MCUboot recovery mode runs with NO application → no hang

---

## SAFETY RULES FOR DRIVER DEVELOPMENT

1. **NEVER** use unbounded busy-waits (`while(reg) {}`) inside `irq_lock()`.
   Always add a timeout: `for (int i = 0; i < 100000 && (REG & BIT); i++) {}`
   If timeout expires, log error and bail — don't hang the system.

2. **NEVER** flash firmware that uses `irq_lock` for >1ms without first verifying
   in a test build that the locked section actually completes.

3. **ALWAYS** keep `dist/crush80-zmk-app.signed.MACMODE-WORKING.bin` as a known-good backup.

4. If the keyboard hangs after flashing: run `python3 scripts/force_recovery.py`

---

## Status: BLOCKED — LEDs do not light up despite confirmed SPI hardware activity

This document captures all attempts to bring up the AW20216S RGB LED controller on the Wobkey Crush 80 keyboard running ZMK firmware on a Telink TLSR9518 (B91 RISC-V) MCU.

The keyboard matrix, USB, BLE, and all keymap features work perfectly. Only the LED subsystem refuses to respond.

---

## Hardware Facts (Confirmed)

| Item | Value | Source |
|------|-------|--------|
| LED controller | AW20216S (x2 chips, 154 LEDs total) | Ghidra analysis of original firmware |
| CS chip 0 | PE0 (GPIO, active low) | Ghidra `FUN_ram_0000f2b4` |
| SPI CLK | PE1 (HSPI FUNC_C alternate) | Ghidra + Telink SDK |
| SPI MOSI | PE2 (HSPI FUNC_C alternate) | Ghidra + Telink SDK |
| CS chip 1 | PC0 (GPIO, active low) | Ghidra |
| LED power MOSFET | PC2 (GPIO, active high) | Ghidra + Rainy 75 reference |
| HSPI base address | 0x81FFFFC0 | Telink B91 SDK `spi_reg.h` |
| PE GPIO function reg | 0x80140326 (bit1=PE1, bit2=PE2; 1=GPIO, 0=alt) | SDK `gpio_reg.h` |
| HSPI clock enable | 0x801401E4 bit 0 | SDK `soc.h` |
| Pin pad_mul_sel | 0x80140355 (bit 1 for PE alt functions) | SDK `gpio_reg.h` |

### Pin Sharing Constraint

PE0, PE1, PE2, and PC0 are also kscan matrix columns (col2row, active-low). The kscan driver configures them as GPIO outputs at boot. Any LED driver must share these pins without permanently breaking kscan.

---

## Attempt History

### Attempt 1: GPIO Bit-Bang, SPI Mode 0 (CPOL=0, CPHA=0)

**Approach:** Directly write to PE_OUT register to toggle CLK/MOSI under `irq_lock`. Used command bytes 0xC0/0xC1/0xC2 for page select.

**Result:** Keys on columns 0,1,2,13 stopped working. No LEDs.

**Root cause:** `spi_pins_release()` set OEN to input mode, breaking kscan permanently.

### Attempt 2: GPIO Bit-Bang, No OEN Changes

**Approach:** Same as #1 but never touch OEN. Just write OUT register.

**Result:** All keys work. No LEDs.

**Analysis:** Keys working proves OUT register writes drive the pins. SPI data was being sent but AW20216S didn't respond. Later discovered command bytes were wrong (0xC0 is not the AW20216S format).

### Attempt 3: GPIO Bit-Bang, OEN Toggle (Enable/Restore per frame)

**Approach:** Enable OEN before SPI, disable after.

**Result:** Same keys broken. Same as attempt 1.

**Root cause:** Kscan expects OEN in a specific state; toggling it breaks kscan.

### Attempt 4: GPIO Bit-Bang, Correct Command Bytes (0xA0/0xA2/0xA4)

**Approach:** Fixed to use AW20216S datasheet format: `0xA0 | (page << 1)`. No OEN changes.

**Result:** All keys work. No LEDs.

### Attempt 5: GPIO Bit-Bang, CPOL=1 (CLK idles HIGH)

**Approach:** Changed clock polarity after discovering firmware writes 0x45 to an RF register (initially mistaken for SPI control). CLK now idles HIGH, data on falling edge.

**Result:** All keys work. No LEDs.

**Later finding:** The 0x45 write was to the RF baseband registers (0x80140A00 = `REG_BB_LL_BASE_ADDR`), NOT SPI. This was a red herring.

### Attempt 6: HSPI Hardware, SPI Mode 0

**Approach:** Use the actual HSPI hardware peripheral at 0x81FFFFC0. Switch PE1/PE2 from GPIO to HSPI alt function (clear bits in 0x80140326) during transfers, restore after. Enable HSPI clock at 0x801401E4.

**Result:** All keys work. No LEDs. **HSPI status register confirms transfer completed (STATUS=0x40 = end-of-transfer flag, FIFOs empty).**

### Attempt 7: HSPI Hardware + gpio_input_en

**Approach:** Added `gpio_input_en(PE1/PE2)` before switching to HSPI mode, matching SDK's `hspi_set_pin_mux()` behavior.

**Result:** All keys work. No LEDs. HSPI still reports successful transfer.

### Attempt 8: HSPI Hardware + pad_mul_sel + diagnostics

**Approach:** Added `pad_mul_sel |= BIT(1)` at 0x80140355. Added diagnostic logging.

**Result:** All keys work. No LEDs. Logs confirm:
- `CLK_EN0=0xFF` (HSPI clock enabled)
- `MODE0=0x80` (master mode)
- `PAD_MUL=0x03` (pad_mul_sel set)
- `HSPI_STATUS=0x40` (transfer completed)
- `FIFO_ST=0xA0` (both FIFOs empty)
- `PE_FUNC=0x7F` (restored to GPIO after transfer)

### Attempt 9: HSPI Hardware, SPI Mode 3 (CPOL=1, CPHA=1)

**Approach:** Changed MODE0 to 0xE0 (master + CPOL + CPHA). The existing Zephyr AW20216S driver in this repo uses `SPI_MODE_CPOL | SPI_MODE_CPHA`.

**Result:** All keys work. No LEDs.

### Attempt 10: HSPI Hardware, Single Transaction + 50ms Power Delay

**Approach:** Ensured all bytes (command + register + data) are sent in one continuous HSPI transaction under one CS assertion. Increased PC2 power-on delay from 5ms to 50ms.

**Result:** All keys work. No LEDs.

---

## What We Know For Certain

1. **The HSPI hardware IS running.** Transfer-complete flag is set, FIFOs drain, no hang. The peripheral successfully clocks out bytes.
2. **Pin function switching works.** PE1/PE2 toggle between GPIO and HSPI alt mode without breaking kscan (keys always work after restore).
3. **PC2 is configured as output and driven HIGH.** OEN is cleared (output enabled), OUT bit is set.
4. **The AW20216S does NOT respond** to any SPI mode (0, 2, 3) or command format we've tried.
5. **The original firmware uses HSPI hardware** with PE1/PE2 in FUNC_C to drive the AW20216S successfully (LEDs work with stock firmware).

## What We DON'T Know

1. **Is the HSPI output actually reaching the PE1/PE2 pads?** The HSPI internal status says "done" but we haven't verified with a logic analyzer that signals appear on the physical pins.
2. **Is PC2 actually powering the LED rail?** We drive it HIGH but have no way to measure VLED without a multimeter.
3. **Is there additional pin configuration needed?** The original firmware writes to addresses we haven't fully decoded (0x80140828, other pin mux registers). There might be a "pin output enable" or "analog disable" register that needs to be set for HSPI to actually drive the pad.
4. **Does the AW20216S on this board variant use a non-standard protocol?** The existing Zephyr driver uses `0xFD` page register; the datasheet says command-byte method; QMK uses command-byte. We've tried the command-byte method but not the 0xFD method via HSPI hardware.
5. **Is there a chip enable pin or reset pin** (besides software reset) that needs to be toggled?

---

## Files of Interest

- `zmk/src/crush80_rgb.c` — Current RGB driver (HSPI hardware approach, Mode 3)
- `zmk/src/crush80_rgb.h` — Public API header
- `zmk/drivers/led/aw20216s.c` — Alternative Zephyr SPI-based driver (uses `spi_write_dt`, DTS approach)
- `zmk/drivers/led/aw20216s.h` — API for the DTS-based driver
- `zmk/boards/crush80/crush80.dts` — Board DTS (HSPI disabled, pin assignments documented)
- `docs/ghidra_spi_extraction.md` — How SPI pins were identified
- `docs/rgb-led-plan.md` — Original RGB implementation plan
- `firmware/Wobkey_Crush_80_Patched_Firmware/` — Original firmware binary + technical report
- `/Users/adyung/Projects/crush80-workspace/modules/hal/hal_telink/tlsr9/drivers/B91/spi.c` — Telink SDK SPI driver
- `/Users/adyung/Projects/crush80-workspace/modules/hal/hal_telink/tlsr9/drivers/B91/spi.h` — SDK SPI API + inline helpers
- `/Users/adyung/Projects/crush80-workspace/modules/hal/hal_telink/tlsr9/drivers/B91/reg_include/spi_reg.h` — HSPI/PSPI register definitions
- `/Users/adyung/Projects/crush80-workspace/modules/hal/hal_telink/tlsr9/drivers/B91/reg_include/gpio_reg.h` — GPIO + pin mux registers

---

## Suggestions for Fresh Investigation

The problem is solvable. The original firmware lights up LEDs on this exact hardware. The gap is in understanding what EXACTLY the original firmware does differently. Here are angles to pursue:

### 1. Deep Firmware Disassembly of the SPI Transaction Function

The function at firmware offset `0xE200` is the SPI transaction wrapper called from the LED init. It uses function pointers at RAM addresses `0xBC4` and `0xBC8` (initialized by the BLE blob at runtime). Disassemble this function AND the function it calls through the pointer to understand the exact register sequence for an HSPI transaction.

### 2. Trace ALL Register Writes During LED Init

The LED init at `0xF2B4` calls multiple sub-functions. Comprehensively decode EVERY register write from entry to exit, including the sub-calls to `0xD260`, `0xE200`, `0xF15C`, and `0x18280`. One of these likely configures a register we're missing.

### 3. Pin Output Enable vs GPIO Function

On B91, there might be ADDITIONAL registers controlling whether the HSPI peripheral can actually drive the physical pad. Check:
- Is there a "GPIO output enable" that overrides alternate function output?
- Is there an "analog disable" register that must be set for digital output?
- The register at `0x80140320` (PE "GPIO" register, offset +0x00 from port base) — what does it actually control?

### 4. Try the PSPI Peripheral Instead

PSPI (at 0x80140040) can also drive SPI. While its DEFAULT pins (PB5/PB7/PC4) aren't connected to the AW20216S, the pin mux system might allow routing PSPI to PE1/PE2 via a different function code. Check `reg_gpio_func_mux` for PE1/PE2 with different function values (0, 1, 2, 3).

### 5. Verify with Logic Analyzer

The definitive test: connect a logic analyzer to PE1 and PE2 (accessible on the keyboard PCB). Run the HSPI code and see if signals appear. If yes, the problem is protocol/AW20216S. If no, the problem is pin routing/output driver.

### 6. Use the Original Firmware as a Known-Good Reference

The stock firmware binary is at `firmware/Wobkey_Crush_80_Patched_Firmware/firmware/v2_patched.bin`. Flash it temporarily and verify LEDs work, then examine what's different at the hardware register level.

### 7. Check if HSPI Needs an External Clock Source

The HSPI peripheral might derive its clock from a specific PLL or clock source that needs to be enabled separately from just `CLK_EN0`. Check the B91 clock tree documentation.

### 8. Read Back HSPI Registers After Init

After calling `hspi_init()`, read back ALL HSPI registers (0x81FFFFC0 through 0x81FFFFCF) and log them. Compare against what the SDK's `spi_master_init(HSPI_MODULE, ...)` produces. Any discrepancy indicates a missing setup step.

---

## Build & Test Commands

```bash
# Build with RGB enabled:
# Set CONFIG_CRUSH80_RGB=y in conf/app.conf
bash build.sh --skip-bridge --skip-mcuboot

# Flash:
bash update.sh
# Then unplug/replug keyboard

# Read boot logs:
PORT=$(python3 -c "import glob; p=glob.glob('/dev/cu.usbmodem*'); print(p[0])")
python3 -c "import serial,time; s=serial.Serial('$PORT',115200,timeout=2); s.dtr=True; time.sleep(0.5); print(s.read(8192).decode(errors='replace')); s.close()"

# Revert to working Mac mode (no RGB):
# Upload dist/crush80-zmk-app.signed.MACMODE-WORKING.bin
```

---

## Key Insight for the Next Investigator

The HSPI hardware reports "transfer complete" — but we have NO confirmation that signals actually appear on the PE1/PE2 physical pads. The most likely missing piece is a **pad driver enable register** or **output mux configuration** that routes the HSPI peripheral's internal CLK/MOSI signals to the external PE1/PE2 pads. The `gpio_function_dis()` call (clearing bit in 0x80140326) might not be sufficient — there may be an additional step in the HSPI pin routing that the SDK's `hspi_set_pin_mux()` doesn't explicitly show because it relies on power-on defaults or earlier initialization.

The original firmware's LED init function at `0xF2B4` calls `0xD260` before ANY SPI transaction. That function writes to `0x80140313` (PC_IE), does some waiting, and calls other setup functions. It might be configuring the HSPI pin routing that we're missing. **Start there.**
