# Extracting AW20216S SPI Pins with Ghidra (Windows)

The Crush 80's AW20216S LED driver communicates with the TLSR9511 over SPI. The exact
CS, CLK, and MOSI pin assignments are not documented and must be extracted from the stock
firmware binary. This guide explains how to do that on Windows using Ghidra.

Without these pin numbers, RGB will not work — but USB HID and BLE work regardless.

---

## What You Need

- [Ghidra](https://ghidra-sre.org/) — free, from NSA/GitHub (Windows download)
- The firmware binary: `firmware/v2_patched.bin` (already in this repo)
- **Andes V5 processor module for Ghidra** — this is the critical piece

### Why Andes V5 Matters

The TLSR9511 uses the Andes D25F CPU core, which extends RISC-V with custom instructions
(Andes V5 extension set). Standard Ghidra `RISCV:LE:32:RV32IC` will fail to decode about
40% of instructions. You must use `RISCV:LE:32:AndeStar_v5` or equivalent.

The Rainy 75 Pro project solved this exact problem. Their CLAUDE.md documents:
> "Ghidra: 211 functions, 211 named (100%), project uses RISCV:LE:32:AndeStar_v5"

---

## Step-by-Step

### Step 1: Install Ghidra

1. Download Ghidra from https://github.com/NationalSecurityAgency/ghidra/releases
   - Pick the latest stable release: `ghidra_11.x.x_PUBLIC_YYYYMMDD.zip`
2. Extract to `C:\Tools\ghidra\` (or any path without spaces)
3. Install Java 17+ if not present: https://adoptium.net/
4. Launch: double-click `ghidraRun.bat`

### Step 2: Add the Andes V5 Processor Module

The official Ghidra distribution does not include the Andes V5 processor.
You need to add it from the `hal_telink` repository (the same HAL the ZMK firmware uses).

1. In WSL or Git Bash, clone the HAL:
   ```bash
   git clone --depth=1 https://github.com/zephyrproject-rtos/hal_telink
   ```
2. Look for the Ghidra processor definition:
   ```
   hal_telink/tlsr9/tools/ghidra/
   ```
   If it exists, copy the processor folder into:
   ```
   C:\Tools\ghidra\Ghidra\Processors\
   ```
3. Restart Ghidra.

**Alternative if the processor folder is absent:**  
Use `RISCV:LE:32:RV32IMC` (standard RISC-V) — it will decode most instructions.
The SPI GPIO writes use standard `LUI + ADDI + SB` instructions which decode correctly
even without Andes extensions. You'll just see some `??` entries mixed in.

### Step 3: Create a Ghidra Project

1. File → New Project → Non-Shared Project
2. Name: `crush80_fw` — save anywhere
3. File → Import File → navigate to `firmware/v2_patched.bin`
4. In the import dialog:
   - **Language**: `RISCV:LE:32:AndeStar_v5` (or `RISCV:LE:32:RV32IMC` fallback)
   - **Base address**: `0x00000000`
     (The Telink B91 copies firmware from flash to ILM RAM at address 0, then executes from there)
5. Click OK → accept defaults → click OK again

### Step 4: Run Auto-Analysis

1. The CodeBrowser opens — click "Yes" when asked to analyze
2. In the Analysis Options dialog, accept defaults and click "Analyze"
3. Wait 2–5 minutes for analysis to complete (watch the bottom progress bar)

### Step 5: Find the LED Init Function

The LED initialization function is at firmware offset **0xEF88** (v1) or approximately
**0xF2B0** (v2, shifted +864 bytes). The function is 768 bytes and contains the most
GPIO register writes in any function in the firmware.

**Method A — Navigate by address:**
1. Press `G` (Go to address)
2. Type `ef88` — press Enter
3. If you see a long function with many `sb` (store byte) instructions, you're in the right place
4. If it just shows `ret` at that address, try `f288` (v2 offset)

**Method B — Find by GPIO density (recommended):**
1. Window → Script Manager → Run `GhidraHSV.java` from `scripts/GhidraHSV.java` in this repo
   (Copy it to `C:\Tools\ghidra\ghidra_scripts\` first)
2. The script decompiles the region `0xC000–0xE000` and prints all GPIO accesses to the console

**Method C — Symbol search:**
1. Search → Search Memory (Ctrl+M)
2. Search for the byte pattern: `B7 07 40 80` (this is `LUI a5, 0x80140` in little-endian RV32I,
   the instruction that loads the GPIO base address `0x80140000`)
3. Look for clusters of this pattern — the LED init will have 5+ in a row

### Step 6: Read the GPIO Accesses

Once you're in the LED init function, look for the **AW20216S SPI init pattern**.
The AW20216S is initialized by:
1. Setting CS pin as output (GPIO_OE write)
2. Asserting CS HIGH (GPIO_OUT write)
3. Configuring CLK and MOSI pins
4. Toggling CS LOW → sending bytes → CS HIGH (page select 0xFD, then register writes)

In the decompiler view (Window → Decompiler), look for sequences like:

```c
// GPIO_OE (output enable) at 0x80140120:
*(byte *)(0x80140120 + port_offset) = (old_val | pin_mask);

// GPIO_OUT (output value) at 0x80140100:
*(byte *)(0x80140100 + port_offset) &= ~cs_pin;   // CS LOW
*(byte *)(0x80140100 + port_offset) |=  cs_pin;   // CS HIGH
```

In the listing view, look for sequences like:
```asm
lui   a5, 0x80140         ; load GPIO base
sb    a4, 0x120(a5)       ; write GPIO_OE[port]    ← set pin as output
sb    a3, 0x100(a5)       ; write GPIO_OUT[port]   ← set pin HIGH
```

### Step 7: Decode Port and Pin

The GPIO register layout on the B91:
```
Offset from 0x80140000:
  +0x000  — GPIO_IE[port]   input enable   (PA=0, PB=1, PC=2, PD=3, PE=4)
  +0x100  — GPIO_OUT[port]  output data
  +0x120  — GPIO_OE[port]   output enable (0=output, 1=hi-Z)
  +0x140  — GPIO_IN[port]   input read
  +0x160  — GPIO_PU[port]   pull-up/down
  +0x300  — GPIO_FEN[port]  function enable (GPIO mode vs peripheral)
```

The offset within the `sb` instruction tells you the port:
- `sb ..., 0x100(a5)` → PA (offset 0 from GPIO_OUT base)
- `sb ..., 0x101(a5)` → PB
- `sb ..., 0x102(a5)` → PC
- etc.

The value being written tells you the pin (each bit = one GPIO):
- `0x01` = pin 0 (e.g., PC0)
- `0x02` = pin 1 (PC1)
- `0x04` = pin 2 (PC2)
- `0x80` = pin 7 (PC7)

**Example interpretation:**
```asm
lui   a5, 0x80140
li    a4, 0x04           ; bit 2
sb    a4, 0x122(a5)      ; GPIO_OE[PC] |= 0x04  → PC2 as output = likely CS pin
sb    a4, 0x102(a5)      ; GPIO_OUT[PC] |= 0x04 → PC2 HIGH     = CS deassert
```
This tells you CS = PC2 (GPIO Port C, pin 2).

### Step 8: Record the Three Pins

Write down:
| Function | Pin | How identified |
|---|---|---|
| CS (chip select) | `P?` | Toggled LOW then HIGH around each SPI transaction |
| CLK (clock) | `P?` | Toggles rapidly during data transfer |
| MOSI (data out) | `P?` | Changes with each bit, driven from a data register or bit-bang |

**Hint from firmware analysis:** The AW20216S is likely wired to the GSPI peripheral
(Telink's general SPI). GSPI on the B91 uses:
- Default: PD0=CS, PD2=CLK, PD3=MOSI, PD4=MISO
- Alternate: PC0=CS, PC1=CLK, PC2=MOSI, PC3=MISO

Check whether the LED init configures `GPIO_FEN` to 0 for these pins (sets GPIO mode,
meaning bit-bang) or sets them to alternate function (peripheral SPI). If alternate
function, the GSPI registers at `0x801401C0` will be used — look for writes to those.

### Step 9: Update the Board DTS

Once you have the three pins, open `zmk/boards/crush80/crush80.dts` and find the
AW20216S SPI node (currently a placeholder). Update the `pinctrl` and `cs-gpios` entries:

```dts
/* Example — replace with your actual pins */
&spi1 {
    status = "okay";
    cs-gpios = <&gpioc 0 GPIO_ACTIVE_LOW>;  /* CS = PC0 */
    pinctrl-0 = <&spi1_default>;
    pinctrl-names = "default";

    aw20216s0: aw20216s@0 {
        compatible = "wobkey,aw20216s";
        reg = <0>;
        spi-max-frequency = <1000000>;  /* 1 MHz — conservative start */
        num-leds = <154>;
        global-current = <32>;
        status = "okay";
    };
};
```

Then rebuild and flash. RGB will light up on boot if the pins are correct.

**Debugging RGB bring-up:**
- If no LEDs light: wrong SPI interface or CS pin
- If LEDs show garbage/flicker: correct interface but wrong CLK polarity/phase — try `SPI_MODE_CPOL | SPI_MODE_CPHA` variants in `aw20216s.c`
- If only some LEDs work: LED channel mapping in `crush80_led_sw[]`/`crush80_led_cs[]` needs calibration
- If first LED is correct but rest are wrong: channel ordering is offset — adjust by 1-3

---

## Quick Reference: GPIO Register Addresses

| Register | Address | Notes |
|---|---|---|
| `GPIO_IE` (input enable) | `0x80140000` + port | Port: PA=0, PB=1, PC=2… |
| `GPIO_OUT` (output) | `0x80140100` + port | Write pin HIGH/LOW |
| `GPIO_OE` (output enable) | `0x80140120` + port | 0=output, 1=hi-Z input |
| `GPIO_IN` (input read) | `0x80140140` + port | Read current pin state |
| `GPIO_PU` (pull up/down) | `0x80140160` + port | Pull configuration |
| `GPIO_FEN` (function enable) | `0x80140300` + port | 1=GPIO mode, 0=peripheral |
| `GSPI_DATA` | `0x801401C0` | SPI data register |
| `GSPI_STATUS` | `0x801401CC` | SPI status |
