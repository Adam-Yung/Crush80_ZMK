# Crush 80 — Next Steps: Mac Mode + RGB Implementation Plan

## Current State (as of 2026-08-23)

The keyboard is running the confirmed-working firmware with:
- All 88 keys correctly mapped
- USB HID working
- BLE working
- MCUmgr DFU working
- No Mac mode (original HRM keymap)
- No RGB LEDs

The confirmed-working firmware hash is `49fe1ec8799a53debe9792be0f570773e1001943e9e0bebf40fe995100aea6bd`. It should be in slot 0 after the user does a cold boot (unplug/replug).

## CRITICAL LESSONS LEARNED

### 1. MCUboot Swap Requires Cold Boot
On the Telink B91, `mcumgr reset` (software reset) does NOT trigger MCUboot's image swap. Only a physical USB unplug/replug (full power cycle) causes MCUboot to check the pending flag and perform the swap. The flash procedure MUST include instructing the user to physically unplug and replug.

### 2. NEVER Enable &hspi in DTS
Enabling `&hspi { status = "okay"; }` with pinctrl entries for PE1/PE2 causes Zephyr's pinctrl system to configure PE1/PE2 as FUNC_C (SPI alternate function) at device init time. This makes the kscan GPIO driver unable to control these pins, causing a fatal kernel assertion that bricks the keyboard (no USB, no BLE, requires 10s power drain + recovery flash).

### 3. RGB Must Use GPIO Bit-Banging
The AW20216S LED communication MUST be done via raw GPIO register manipulation, NOT through Zephyr's SPI driver framework. The approach:
- Keep `&hspi { status = "disabled"; }` in DTS
- Keep PE0/PE1/PE2 in kscan col-gpios (they work as matrix columns)
- In the RGB driver code, manually toggle GPIO registers to bit-bang SPI:
  1. Pause kscan (`kscan_disable_callback`)
  2. Configure PE0/PE1/PE2 output enable via register writes
  3. Bit-bang the SPI protocol (toggle CLK, shift MOSI, assert/deassert CS)
  4. Restore PE0/PE1/PE2 to kscan column mode
  5. Resume kscan (`kscan_enable_callback`)

### 4. Dotfiles Sync Can Override Git Checkout
`build.sh` syncs keymap and app.conf from `~/.config/DOTFILES/keybindings/crush80-zmk/` BEFORE building. If you `git checkout` a file but don't update the dotfiles copy, build.sh will overwrite your checkout with the dotfiles version. Always update BOTH locations.

### 5. Backup Before Experimental Firmware
Always `cp dist/crush80-zmk-app.signed.bin dist/crush80-zmk-app.signed.BACKUP.bin` before flashing anything experimental.

---

## Plan: Mac Mode Implementation

### Requirements
- Fn+M toggles between Base layer and Mac layer
- Mac mode: Nav/ExtNav use Cmd+Arrow (line), Option+Arrow (word) instead of Home/End/Ctrl+Arrow
- Mac mode: Cut/Copy/Paste/Undo use Cmd instead of Ctrl

### Implementation
Add layers 6 (MAC base), 7 (MACNAV), 8 (MACEXTNAV) to the keymap. The MAC base layer is identical to BASE except the W-hold activates MACNAV instead of NAV. Add mac-specific macros for select-word and select-line.

### Approach (from the Cornix keyboard reference at /Users/adyung/Adam/zmk-keyboard-cornix)
- Cornix uses separate NavWin/NavMac layer pairs
- Same HRM timings: 280/175/150 (already matching)
- Mac shortcuts: Cmd+Z/X/C/V, Cmd+Left/Right for line, Opt+Left/Right for word

### Key Binding Changes (Fn layer)
- M position → `&tog MAC` (toggles Mac mode on/off)

### Testing
After implementing, build and flash using the CORRECT procedure (upload → test → UNPLUG/REPLUG → confirm). Verify all keys still work before and after toggling Mac mode.

---

## Plan: RGB LED Implementation

### Architecture: GPIO Bit-Bang SPI

```
┌─────────────────────────────────────────────────┐
│                  RGB Thread (30Hz)                │
│                                                   │
│  1. kscan_disable_callback()                     │
│  2. Set PE0/PE1/PE2 OEN (output enable)          │
│  3. Bit-bang SPI to AW20216S:                    │
│     - PE0 = CS (active low)                      │
│     - PE1 = CLK (toggle)                         │
│     - PE2 = MOSI (data)                          │
│  4. Restore PE0/PE1/PE2 to kscan mode            │
│  5. kscan_enable_callback()                      │
│                                                   │
│  Total pin-hold time: ~3-5ms per frame           │
│  Matrix scan pause: imperceptible for typing     │
└─────────────────────────────────────────────────┘
```

### B91 GPIO Register Addresses
```c
#define REG_GPIO_PE_OUT     (*(volatile uint8_t *)0x80140321)
#define REG_GPIO_PE_OEN     (*(volatile uint8_t *)0x80140322)
#define REG_GPIO_PE_IE      (*(volatile uint8_t *)0x80140323)
#define PE0_BIT  0x01  // CS
#define PE1_BIT  0x02  // CLK  
#define PE2_BIT  0x04  // MOSI
```

### SPI Bit-Bang Implementation
```c
static void spi_write_byte(uint8_t data) {
    for (int i = 7; i >= 0; i--) {
        // Set MOSI
        if (data & (1 << i))
            REG_GPIO_PE_OUT |= PE2_BIT;
        else
            REG_GPIO_PE_OUT &= ~PE2_BIT;
        // Clock pulse
        REG_GPIO_PE_OUT |= PE1_BIT;   // CLK high
        REG_GPIO_PE_OUT &= ~PE1_BIT;  // CLK low
    }
}

static void aw20216s_write(uint8_t chip, uint8_t addr, uint8_t *data, int len) {
    // Assert CS
    if (chip == 0)
        REG_GPIO_PE_OUT &= ~PE0_BIT;  // PE0 low
    else
        REG_GPIO_PC_OUT &= ~PC0_BIT;  // PC0 low (chip 1)
    
    spi_write_byte(addr);  // Address (bit 7 = 0 for write)
    for (int i = 0; i < len; i++)
        spi_write_byte(data[i]);
    
    // Deassert CS
    REG_GPIO_PE_OUT |= PE0_BIT;
    REG_GPIO_PC_OUT |= PC0_BIT;
}
```

### LED Effects by Layer

| Layer | Logo LED | Per-Key LEDs |
|-------|----------|--------------|
| BASE (0) | Warm white (255,200,100) | All OFF |
| FN (1) | Red | F-row=red, BT keys=blue, RGB controls=white |
| NAV (2) | Blue | W=green, IJKL=cool blue, U=purple, O=pink, Home/End=teal, Cut/Copy/Paste=orange, Shift=yellow |
| EXTNAV (3) | Blue (brighter) | Same as NAV, word-jump keys brighter blue |
| SYM (4) | Purple | Numbers=purple, brackets=magenta, operators=cyan, macros=green |
| NATIVE (5) | Dim white | All keys dim white (30,30,30) |
| MAC (6) | Cyan (0,200,220) | All OFF |
| MACNAV (7) | Cyan | Same as NAV colors |
| MACEXTNAV (8) | Cyan | Same as EXTNAV colors |

### HRM Reactive (on hold)
| Position | Key | Modifier | Color |
|----------|-----|----------|-------|
| 51 | A | LCTRL | Red (200,0,0) |
| 52 | S | LALT | Green (0,200,0) |
| 53 | D | LGUI | Blue (0,100,255) |
| 54 | F | LSHFT | Yellow (255,200,0) |
| 57 | J | RSHFT | Yellow |
| 58 | K | RGUI | Blue |
| 59 | L | RALT | Green |
| 60 | ; | RCTRL | Red |

### Special Keys
- **Fn+Backspace**: Toggle all LEDs on/off (persists across layer changes)
- Keys with `&none` binding: Always OFF (no LED)
- Keys with `&trans`: Inherit from lower layer color

### Underglow / Bottom LEDs
- 63 additional LEDs on AW20216S chip 1 (indices 91-153)
- These are the bottom/side underglow LEDs
- Follow the logo LED color for the current layer
- Brightness slightly lower than logo (70% of per-key brightness)
- When LED toggle is OFF, underglow is also OFF

### LED Channel Mapping
- LED-to-key position mapping at firmware offset 0x1C8F4 (91 entries)
- For initial implementation, use position=LED index (0-87 for per-key)
- Logo LED: index 88 (tentative — needs hardware validation)
- Underglow: indices 91-153 on chip 1
- Full channel map (SW/CS) needs validation via `CONFIG_AW20216S_CHANNEL_SCAN=y` mode

### Files to Create/Modify
1. `zmk/src/crush80_rgb.c` — Complete RGB engine with bit-bang SPI + layer effects + HRM reactive
2. `zmk/src/crush80_rgb.h` — Public API header
3. `zmk/CMakeLists.txt` — Add crush80_rgb build (conditional on new CONFIG_CRUSH80_RGB)
4. `zmk/Kconfig` — Add CONFIG_CRUSH80_RGB option
5. `conf/app.conf` — Enable CONFIG_CRUSH80_RGB=y
6. `zmk/boards/crush80/crush80.keymap` — Add Fn+Backspace → RGB toggle behavior

### Safety
- The bit-bang approach keeps `&hspi { status = "disabled"; }` — NO pinctrl conflict
- PE0/PE1/PE2 stay in kscan col-gpios — matrix always works
- RGB thread only temporarily borrows pins (3-5ms every 33ms)
- If RGB code crashes, matrix still works (worst case: LEDs stay off)
- PC2 (LED power MOSFET) stays as GPIO output — can be enabled/disabled independently

---

## Implementation Order

1. **Mac Mode** — keymap-only change, no driver code, low risk
2. **RGB Basic** — bit-bang SPI init + solid color test (prove SPI works without breaking matrix)
3. **RGB Layer Colors** — add layer-aware effects
4. **RGB HRM Reactive** — add position state listener
5. **RGB Underglow** — extend to chip 1 bottom LEDs
6. **LED Toggle** — Fn+Backspace behavior
7. **Channel Map Validation** — channel scan mode to verify LED positions

Each step should be tested independently. ALWAYS backup before flashing. ALWAYS verify keys work after each flash via physical unplug/replug.

---

## Reference

- Original firmware: github.com/Desz01ate/Wobkey_Crush_80_Patched_Firmware (cloned to /tmp/crush80_fw/)
- Rainy 75 ZMK: github.com/scholzri/rainy75-zmk
- Cornix ZMK (HRM reference): /Users/adyung/Adam/zmk-keyboard-cornix
- LED init function: firmware offset 0xF2B4
- LED channel map: firmware offset 0x1C8F4
- AW20216S datasheet: 9 rows (SW) x 24 columns (CS) = 216 channels per chip
