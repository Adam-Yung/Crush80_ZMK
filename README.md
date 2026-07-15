# Wobkey Crush 80 — ZMK Firmware

Open-source ZMK firmware for the Wobkey Crush 80 (Telink TLSR9511, B91, RISC-V).

**What works:** USB HID (1000 Hz) · Bluetooth LE (3 profiles) · ZMK Studio live keymap editing · battery gauge · deep sleep · MCUboot with safe one-command revert.

**What's pending:** Per-key RGB (AW20216S driver written, channel map needs bring-up) · 2.4 GHz dongle (needs nRF24 sniffer session — see `docs/hardware_guide_2g_and_diy.md`).

---

## Quick Start

### 1. One-time setup (WSL Ubuntu 24.04, needs sudo)

```bash
bash setup.sh
```

This installs all dependencies, downloads the Zephyr SDK, initialises the west workspace, fetches the Telink BLE blob, and applies the required patches. Takes 10–15 min on first run; subsequent runs are fast.

### 2. Build

```bash
bash build.sh
```

Outputs land in `dist/` (gitignored):

| File | Purpose |
|------|---------|
| `dist/crush80-ota-bridge.bin` | Flash first — enables DFU |
| `dist/crush80-zmk-app.signed.bin` | Flash second — the actual ZMK firmware |
| `dist/crush80-mcuboot.bin` | Hardware recovery only (SWS/Burning Board) |

### 3. Flash

Plug the keyboard in via USB-C and switch it to USB mode, then:

```bash
bash flash.sh
```

That's it. `flash.sh stage1` or `flash.sh stage2` to run individual stages. See `flash.sh --help` comments for details.

### 4. Revert to stock

```bash
bash flash.sh restore
```

---

## Customising the Keymap

Edit `zmk/boards/crush80/crush80.keymap` and run `bash build.sh --skip-bridge --skip-mcuboot`, then `bash flash.sh stage2`.

**Live editing without rebuilding:** Connect over Bluetooth, open [zmk.studio](https://zmk.studio) in Chrome or Edge. Unlock with `Fn + ESC`.

**Adding home row mods (balanced flavor):**
```dts
hml: home_row_mod_left {
    compatible = "zmk,behavior-hold-tap";
    #binding-cells = <2>;
    flavor = "balanced";
    tapping-term-ms = <280>;
    quick-tap-ms = <175>;
    require-prior-idle-ms = <150>;
    bindings = <&kp>, <&kp>;
    hold-trigger-key-positions = <KEYS_R THUMBS>;
    hold-trigger-on-release;
};
```

---

## Key Bindings

| Combo | Action |
|-------|--------|
| `Fn + F1/F2/F3` | BT profile 1/2/3 |
| `Fn + F4` | Switch to USB output |
| `Fn + F5` | Toggle USB / Bluetooth |
| `Fn + Delete` | Clear current BT profile |
| `Fn + ESC` | Unlock ZMK Studio |

---

## Wireless: 2.4 GHz Dongle

The 2.4 GHz access code must be captured from your keyboard+dongle pair with a cheap nRF24L01+ module on a Raspberry Pi. Full hardware guide including wiring, script, and other DIY projects: **`docs/hardware_guide_2g_and_diy.md`**.

Once you have the code, edit two lines in `scripts/crush80_2g_config.py` and rebuild.

---

## Recovery

| Situation | Fix |
|-----------|-----|
| App crashes on boot | MCUboot watchdog auto-reverts in ~30s — do nothing |
| Revert to stock | `bash flash.sh restore` |
| Keyboard unresponsive | `python3 scripts/flash_ota.py firmware/code_2M_v2_patched.bin` |
| Total brick (rare) | Telink Burning Board via SWS pads — see `docs/ghidra_spi_extraction.md` |

---

## Repository Layout

```
setup.sh              One-time WSL environment setup
build.sh              Build all firmware targets → dist/
flash.sh              Flash keyboard / restore to stock
requirements.txt      Python dependencies

zmk/
  boards/crush80/     Board definition (DTS, keymap, Kconfig)
  drivers/led/        AW20216S driver + RGB engine (solid + echo)
  drivers/radio/      2.4G TPLL placeholder (fill in access code)
  west.yml            Dependency manifest

conf/                 Build configuration overlays
firmware/             Critical binaries
  code_2M_v2_patched.bin  ← stock restore image — keep this safe
  v2_patched.bin           ← stock firmware (for analysis)
scripts/              Operational scripts
  flash_ota.py              Stage 1 OTA flasher (Linux)
  crush80_2g_config.py      2.4G access code config
  sniff_2g_access_code.py   nRF24 sniffer for RPi
docs/
  implementation_plan.md    Current status and next steps
  ghidra_spi_extraction.md  Hardware analysis findings
  hardware_guide_2g_and_diy.md  2.4G sniffer + LG TV + DIY projects
dist/                 Build outputs (gitignored)
.backup/              Archived reverse-engineering artifacts
.claude/              AI analysis notes
```

---

## Hardware Confirmed

| Component | Finding | Source |
|-----------|---------|--------|
| MCU | TLSR9511 (B91, RISC-V, 1 MB flash) | USB descriptor string |
| LED driver | AW20216S (2× chips, HSPI SPI) | Ghidra firmware analysis |
| SPI CS chip 0 | PE0 | Confirmed |
| SPI CLK | PE1 (HSPI FUNC_C) | Confirmed |
| SPI MOSI | PE2 (HSPI FUNC_C) | Confirmed |
| SPI CS chip 1 | PC0 | Confirmed |
| LED power gate | PC2 (active-high) | Confirmed |
| Matrix | 6 rows × 16 cols (same as Rainy 75 Pro) | v2_update.md |
| GPIO assignments | Same as Rainy 75 Pro | v2_update.md |

---

## Acknowledgments

This project is an independent firmware for the Wobkey Crush 80 keyboard.  
Original community analysis and reference material from [Desz01ate/Wobkey_Crush_80_Patched_Firmware](https://github.com/Desz01ate/Wobkey_Crush_80_Patched_Firmware).

---

## License

Apache 2.0. Telink BLE blob: proprietary (fetched at build time, not redistributed).
