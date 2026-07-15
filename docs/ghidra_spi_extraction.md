# Extracting AW20216S SPI Pins with Ghidra (Windows)

## STATUS: COMPLETE — Pins confirmed

All three SPI pins have been identified from Ghidra analysis of
`FUN_ram_0000f2b4` (LED init function at firmware offset `0xF2B4`).

| Pin | Function | Confidence |
|-----|----------|------------|
| **PE0** | AW20216S chip 0 CS# (active-low) | **CONFIRMED** |
| **PE1** | HSPI CLK (FUNC_C alternate function) | **CONFIRMED** |
| **PE2** | HSPI MOSI (FUNC_C alternate function) | **CONFIRMED** |
| **PC0** | AW20216S chip 1 CS# (active-low) | **CONFIRMED** |
| **PC2** | LED power MOSFET gate (active-high) | **CONFIRMED** (same as Rainy 75) |

These are already written into `zmk/boards/crush80/crush80.dts`.

---

## How we found them

The decompiled output of `FUN_ram_0000f2b4` showed:

```c
// GPIO init: PE pins 0,1,2,4,5,6 all configured as outputs
FUN_ram_0001a140(0x477, 2);  // 0x77 = bits 0,1,2,4,5,6 → PE0,PE1,PE2 + matrix cols

// Second chip CS: PC0 as output
FUN_ram_0001a140(0x201, 2);  // PC0 → output

// LED power: PC2 as output (same as Rainy 75)
FUN_ram_0001a140(0x204, 2);  // PC2 → output
```

PE4, PE5, PE6 are confirmed matrix columns (same as Rainy 75). The only
new outputs on port E were PE0, PE1, PE2 — the SPI lines.

The B91 HSPI hardware SPI controller (`&hspi` in Zephyr DTS) uses PE1=CLK,
PE2=MOSI as its default alternate function (FUNC_C). PE0 is used as
manual GPIO CS (not hardware HSPI CS).

154 LEDs × 3 channels = 462 total. AW20216S max = 216 channels.
Two chips required: chip 0 on PE0 (CS), chip 1 on PC0 (CS), shared CLK/MOSI.

---

## What remains: channel map validation

The only thing left for RGB is knowing which LED index (0–153) maps to
which physical key. This is a bring-up exercise:

1. Flash ZMK with RGB enabled
2. Add a test mode that sets LED 0 = solid white, all others off
3. Note which key glows
4. Increment to LED 1, repeat
5. Update `crush80_led_sw[]` and `crush80_led_cs[]` tables in `zmk/drivers/led/aw20216s.c`

The stock firmware's LED index table at `firmware/v2_patched.bin` offset
`0x1C260` (91 entries) gives the matrix→LED mapping from the original
firmware as a cross-reference.

---

## For future reference: Ghidra method

This is documented for anyone wanting to verify or extend the analysis.

**Key function:** `FUN_ram_0000f2b4` at address `0x0000F2B4`
(navigate: Press `G`, type `f2b4`)

**Search pattern used:** `B7 07 14 80` = `LUI a5, 0x80140` (GPIO base load)

**Argument encoding for GPIO init helper `FUN_ram_0001a140(arg, dir)`:**
- `arg >> 8` = port index (0=PA, 1=PB, 2=PC, 3=PD, 4=PE)
- `arg & 0xFF` = pin bitmask (bit N = pin N)
- `dir = 2` = output, `dir = 0` = input

**B91 HSPI alternate function:** FUNC_C (`B91_FUNC_C = 0x02`) on PE1/PE2
Reference: `zephyr/boards/telink/tlsr9518adk80d/tlsr9518adk80d-pinctrl.dtsi`

**Zephyr SPI node:** `&hspi` (`spi@81FFFFC0`, `peripheral-id = "HSPI_MODULE"`)
