# Wobkey Crush 80 — ZMK Firmware

Open-source ZMK firmware for the Wobkey Crush 80 mechanical keyboard (Telink TLSR9518/B91, RISC-V).

**Status:** USB HID (1000 Hz) · Bluetooth LE (3 profiles: Crush80_ZMK 1/2/3) · ZMK Studio live keymap editing · battery gauge · deep sleep · MCUboot OTA with watchdog auto-revert.

**Pending:** Per-key RGB (AW20216S driver written, channel map needs bring-up) · 2.4 GHz dongle (needs nRF24 sniffer session — see `docs/hardware_guide_2g_and_diy.md`).

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| macOS or Linux | macOS 13+ / Ubuntu 22.04+ | WSL2 works fine on Windows |
| Python | 3.10+ | For west and helper scripts |
| CMake | 3.20+ | `brew install cmake` or from package manager |
| Ninja | 1.10+ | `brew install ninja` |
| dtc | 1.4.6+ | `brew install dtc` |
| Zephyr SDK | 0.17.0 | Downloaded by `setup.sh` |
| Go | 1.20+ | Only for `mcumgr` (firmware flashing tool) |

---

## Quick Start

### 1. One-time setup

```bash
bash setup.sh
```

Installs all dependencies, downloads the Zephyr SDK, initialises the west workspace at `~/Projects/crush80-workspace`, fetches the Telink BLE blob, and applies patches. Takes 10–15 min on first run.

### 2. Build

```bash
bash build.sh
```

Outputs land in `dist/` (gitignored):

| File | Size | Purpose |
|------|------|---------|
| `crush80-mcuboot.bin` | ~54 KB | Bootloader (hardware recovery only) |
| `crush80-ota-bridge.bin` | ~98 KB | OTA bridge — enables DFU via serial recovery |
| `crush80-zmk-app.signed.bin` | ~331 KB | Main ZMK firmware (MCUboot signed) |

Build options:

```bash
bash build.sh --build-mcuboot   # Include MCUboot (not built by default)
bash build.sh --skip-bridge     # Only rebuild ZMK app (fast iteration)
```

### 3. First-time flash (factory keyboard)

Plug the keyboard in via USB-C and switch it to USB mode, then:

```bash
bash flash.sh
```

This writes the OTA bridge and ZMK firmware. `flash.sh stage1` or `flash.sh stage2` for individual stages.

### 4. Subsequent firmware updates

After the initial flash, you never need `flash.sh` again. Use the one-command updater:

```bash
bash update.sh
```

Steps:
1. Press **Fn+Esc** on the keyboard (enters MCUboot serial recovery mode)
2. Run `bash update.sh` (or `bash update.sh --build` to rebuild first)
3. Keyboard reboots with new firmware in ~2 seconds

If something goes wrong, MCUboot's watchdog auto-reverts to the previous firmware within 30 seconds.

---

## Firmware Update — Detailed Guide

### Install mcumgr (one time)

```bash
go install github.com/apache/mynewt-mcumgr-cli/mcumgr@latest
```

Make sure `~/go/bin` is in your PATH, or the script will find it automatically.

### How the update process works

1. **Fn+Esc** triggers the `&bootloader` behavior in ZMK, which writes a retention flag to RAM and reboots
2. MCUboot detects the flag and enters **serial recovery mode** (USB CDC-ACM)
3. `update.sh` detects the serial device (e.g., `/dev/cu.usbmodemXXXX` on macOS)
4. `mcumgr` uploads the new firmware image over serial
5. MCUboot validates the image signature and boots the new firmware
6. If the new firmware crashes, MCUboot reverts after ~30 seconds (watchdog safety)

### Manual mcumgr commands (if not using update.sh)

```bash
# After pressing Fn+Esc on the keyboard:
SERIAL=/dev/cu.usbmodem*    # macOS (use /dev/ttyACM0 on Linux)

# Upload firmware
mcumgr --conntype serial --connstring "dev=$SERIAL,baud=115200" image upload dist/crush80-zmk-app.signed.bin

# Confirm and reset
mcumgr --conntype serial --connstring "dev=$SERIAL,baud=115200" image confirm ""
mcumgr --conntype serial --connstring "dev=$SERIAL,baud=115200" reset
```

---

## Bluetooth

The keyboard advertises as **Crush80_ZMK 1**, **Crush80_ZMK 2**, or **Crush80_ZMK 3** depending on the active profile. Up to 5 paired devices are supported (3 dedicated profiles + 2 spare slots).

| Key combo | Action |
|-----------|--------|
| `Fn + F1` | Switch to BT profile 1 |
| `Fn + F2` | Switch to BT profile 2 |
| `Fn + F3` | Switch to BT profile 3 |
| `Fn + F4` | Switch to USB output |
| `Fn + F5` | Toggle USB / Bluetooth |
| `Fn + Ins` | Clear current BT profile (unpair) |

### Pairing a new device

1. Press `Fn + F1/F2/F3` to select an empty profile
2. The keyboard starts advertising (LED flashes if RGB is enabled)
3. On your device, look for "Crush80_ZMK N" in Bluetooth settings
4. Pair — no PIN required

---

## USB Wired Mode

USB HID works at 1000 Hz polling rate. Press `Fn + F4` to force USB output, or just plug in a USB-C cable (ZMK auto-detects and prefers USB when connected).

---

## Layers & Key Bindings

The default keymap has 6 layers:

| Layer | Trigger | Purpose |
|-------|---------|---------|
| Base | Default | Home row mods (CAGS), media F-row, thumb Shift/Tab |
| Fn | Hold Fn key | F1-F12, BT profiles, RGB, USB/BT toggle, bootloader |
| Nav | Hold W | IJKL arrows, Bspc/Del, Home/End, editing shortcuts |
| ExtNav | Hold Space (in Nav) | Word-jump, PgUp/PgDn, word delete |
| Sym | Hold Caps or ' | Numbers left (4-5-6/7-8-9/0), brackets/punctuation right |
| Native | Toggle ScrLk | Full passthrough (all remapping off) |

### Important combos

| Combo | Action |
|-------|--------|
| `Fn + Esc` | Enter bootloader (MCUboot serial recovery) |
| `Fn + Bspc` | RGB toggle |
| `Fn + \` / `Fn + Enter` | RGB effect cycle |
| `Fn + Up` / `Fn + Down` | RGB brightness up/down |
| `ScrLk` | Toggle Native layer (disable all remapping) |

### Home Row Mods (CAGS)

- Left: A=Ctrl, S=Alt, D=Gui, F=Shift
- Right: J=Shift, K=Gui, L=Alt, ;=Ctrl

---

## Customising the Keymap

### Option A: Edit and rebuild

1. Edit `zmk/boards/crush80/crush80.keymap`
2. Build: `bash build.sh --skip-bridge`
3. Flash: press `Fn+Esc`, then `bash update.sh`

### Option B: Live editing (no rebuild)

1. Connect over Bluetooth
2. Open [zmk.studio](https://zmk.studio) in Chrome or Edge
3. Changes apply immediately and persist across reboots

---

## Recovery

| Situation | Fix |
|-----------|-----|
| App crashes on boot | MCUboot watchdog auto-reverts in ~30s — do nothing |
| Force bootloader entry | Hold `Fn+Esc` (or if firmware is bricked, see SWS below) |
| Revert to stock firmware | `bash flash.sh restore` |
| Keyboard fully unresponsive | `python3 scripts/flash_ota.py firmware/code_2M_v2_patched.bin` |
| Total brick (rare) | Telink Burning Board via SWS pads — see `docs/ghidra_spi_extraction.md` |

---

## Repository Layout

```
setup.sh              One-time environment setup
build.sh              Build all firmware targets → dist/
update.sh             One-command firmware update (Fn+Esc → upload → reboot)
flash.sh              First-time flash / restore to stock
requirements.txt      Python dependencies

zmk/
  boards/crush80/     Board definition (DTS, keymap, Kconfig)
  drivers/led/        AW20216S driver + RGB engine
  drivers/radio/      2.4G TPLL placeholder
  include/            Shared dt-bindings headers
  src/                Board-specific sources (BLE naming, boot diag, etc.)
  CMakeLists.txt      Module build rules
  zephyr/module.yml   Zephyr module descriptor
  west.yml            Dependency manifest

conf/                 Build configuration overlays
  app.conf            ZMK application Kconfig
  mcuboot.conf        MCUboot Kconfig
  mcuboot.overlay     MCUboot DTS overlay (disables unneeded peripherals)

firmware/             Critical binaries (stock restore images)
scripts/              Operational scripts (OTA, 2.4G config, sniffer)
docs/                 Hardware analysis and guides
dist/                 Build outputs (gitignored)
```

---

## Building from Scratch (New Contributor Guide)

If you've cloned this repo and want to build firmware for your own Crush 80:

```bash
# 1. Clone
git clone https://github.com/your-user/Crush80_ZMK.git
cd Crush80_ZMK

# 2. Setup (installs SDK, west workspace, Telink blob)
bash setup.sh

# 3. Build everything (first time, include MCUboot)
bash build.sh --build-mcuboot

# 4. Flash to keyboard (USB-C connected, USB mode)
bash flash.sh

# 5. Done! For subsequent keymap changes:
#    Edit zmk/boards/crush80/crush80.keymap
bash build.sh --skip-bridge
# Press Fn+Esc on keyboard, then:
bash update.sh
```

### What the build system does

1. `setup.sh` creates `~/Projects/crush80-workspace/` with the Zephyr RTOS, MCUboot, ZMK source, and Telink HAL
2. `build.sh` syncs your local board/config files into the workspace, then builds:
   - MCUboot bootloader (optional, usually only needed once)
   - OTA bridge firmware (handles DFU protocol)
   - ZMK application firmware (the keyboard logic)
3. Built binaries land in `dist/` with MCUboot image signing applied

### Toolchain notes

- The Zephyr SDK (`~/zephyr-sdk-0.17.0`) provides the RISC-V cross-compiler
- West is Zephyr's meta-tool for managing multi-repo projects
- The Telink BLE blob (`liblt_9518_zephyr.a`) is proprietary and fetched at build time

---

## Hardware

| Component | Details |
|-----------|---------|
| MCU | TLSR9518 (B91, RISC-V, 1 MB flash, 128 KB SRAM) |
| LED driver | AW20216S × 2 (HSPI SPI) |
| Matrix | 6 rows × 16 columns |
| Connectivity | USB 2.0, BLE 5.2, 2.4 GHz (TPLL) |
| Battery | Li-Po with ADC gauge |

---

## Acknowledgments

This project is an independent firmware for the Wobkey Crush 80 keyboard.
Original community analysis from [Desz01ate/Wobkey_Crush_80_Patched_Firmware](https://github.com/Desz01ate/Wobkey_Crush_80_Patched_Firmware).
ZMK platform drivers adapted from [scholzri/rainy75-zmk](https://github.com/scholzri/rainy75-zmk).

---

## License

Apache 2.0. Telink BLE blob: proprietary (fetched at build time, not redistributed).
