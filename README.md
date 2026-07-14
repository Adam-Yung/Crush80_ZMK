# Wobkey Crush 80 — ZMK Firmware

Open-source ZMK firmware for the Wobkey Crush 80 (80% mechanical keyboard, Telink TLSR9511 RISC-V).

**Replaces the proprietary stock firmware with full programmability:**
- USB HID (1000 Hz wired)
- Bluetooth LE HID-over-GATT (3 profiles)
- Home row mods, layers, combos, macros — all ZMK behaviors
- Live keymap editing via [ZMK Studio](https://zmk.studio) over BLE (no software install)
- Per-key RGB via AW20216S *(requires SPI pin confirmation — see below)*
- 2.4 GHz dongle mode *(requires one-time access code sniff — see below)*
- Deep sleep with µA battery draw
- Safe revert to stock firmware — no hardware debugger needed

---

## Hardware Summary

| Property | Value |
|---|---|
| MCU | Telink TLSR9511 (B91, RISC-V RV32IMACF) — *confirmed from firmware binary* |
| Flash / SRAM | 1 MB / 256 KB |
| LED driver | AW20216S (SPI-connected, 154 LEDs) — *confirmed from firmware binary* |
| Matrix | 6 rows × 16 cols — *confirmed from v2_update.md* |
| Keys | 88 (ANSI layout) |
| Connectivity | USB-C + BLE 5.0 + 2.4 GHz dongle |
| Battery | 3750 mAh (Lite) / 7500 mAh (Pro) |

---

## Quick Start: Install Pre-built Firmware

If you just want to flash the latest firmware without building it yourself:

1. Go to the [Actions tab](../../actions) and click the latest successful **Build Crush 80 ZMK Firmware** run
2. Download the artifact: `crush80-firmware-XXXXXXXX.zip`
3. Unzip to get:
   - `crush80-ota-bridge.bin` — flash this first (Stage 1)
   - `crush80-zmk-app.signed.bin` — flash this second (Stage 2)
4. Follow the [Flashing Instructions](#flashing-instructions) below

---

## Building from Source

### Prerequisites

**Linux or WSL2 (Ubuntu 24.04 recommended)**

```bash
# System dependencies
sudo apt-get update
sudo apt-get install -y git cmake ninja-build python3-pip wget xz-utils \
    libusb-1.0-0-dev file

# Python tools
pip3 install west pyelftools

# Zephyr SDK — MUST be 0.17.0 (not 0.17.4, which breaks hal_telink)
cd ~
wget https://github.com/zephyrproject-rtos/sdk-ng/releases/download/v0.17.0/zephyr-sdk-0.17.0_linux-x86_64.tar.xz
tar xf zephyr-sdk-0.17.0_linux-x86_64.tar.xz
cd zephyr-sdk-0.17.0 && ./setup.sh -t riscv64-zephyr-elf
```

### First-Time Workspace Setup

```bash
git clone https://github.com/YOUR_USERNAME/Wobkey_Crush_80_Patched_Firmware
cd Wobkey_Crush_80_Patched_Firmware

# Initialize west workspace (fetches ZMK, Zephyr, HAL, MCUboot — ~500 MB, ~5 min)
cd zmk
west init -l .
west update

# Fetch the Telink BLE controller library
# (proprietary but publicly available from Telink's GitHub; not redistributed here)
cd ..
bash fetch_ble_blob.sh

# Install remaining Zephyr Python dependencies
pip3 install -r zmk/zephyr/scripts/requirements.txt
```

### Build

```bash
export ZEPHYR_SDK_INSTALL_DIR=~/zephyr-sdk-0.17.0

cd zmk

# Build all three targets at once:
#   - MCUboot bootloader
#   - OTA bridge (for initial flash)
#   - Full ZMK application
bash ../build.sh -a
```

**Output files:**
```
zmk/build/zephyr/zmk.signed.bin     ← flash this (Stage 2)
zmk/build-bridge/zephyr/zmk.bin     ← flash this (Stage 1)
zmk/build-mcuboot/zephyr/zephyr.bin ← only needed for hardware recovery
```

### Build via GitHub Actions (no local toolchain needed)

Every push to `main` that changes `zmk/`, `conf/`, or `patches/` triggers an automatic build. Firmware artifacts are available under Actions → latest run → **Artifacts**.

To trigger a manual build: Actions → **Build Crush 80 ZMK Firmware** → **Run workflow**.

---

## Flashing Instructions

> **Before you start:** Download the stock firmware from the Wobkey updater tool and keep it safe. `firmware/code_2M_v2_patched.bin` in this repo is a copy. You can always revert.

### Stage 1 — Flash OTA Bridge

The keyboard currently runs the Evision stock firmware, which has the Telink OTA bootloader in its chip ROM. Stage 1 uses this bootloader.

**Switch the keyboard to USB mode first** (press the mode key if you're in BT or 2.4G).

**Linux / WSL2:**
```bash
# Plug keyboard in via USB-C
python3 scripts/flash_ota.py zmk/build-bridge/zephyr/zmk.bin
# Expect: 100% ████████ | OTA SUCCESS!  (~23 seconds)
```

**Windows (if WSL fails):**
Use the existing `firmware/v2.exe` flasher: replace its `code_2M` resource with `build-bridge/zephyr/zmk.bin` using a resource editor (Resource Hacker), then run.

After Stage 1, the keyboard enumerates as a USB CDC-ACM serial device (`/dev/ttyACM0` on Linux).

### Stage 2 — Flash ZMK via mcumgr DFU

```bash
# Install mcumgr
go install github.com/apache/mynewt-mcumgr-cli/mcumgr@latest

# Upload the signed ZMK image
~/go/bin/mcumgr --conntype serial \
    --connstring "dev=/dev/ttyACM0,baud=115200" \
    image upload zmk/build/zephyr/zmk.signed.bin

# Confirm (MCUboot will boot this image on next reset)
~/go/bin/mcumgr --conntype serial \
    --connstring "dev=/dev/ttyACM0,baud=115200" \
    image confirm

# Reset the keyboard
~/go/bin/mcumgr --conntype serial \
    --connstring "dev=/dev/ttyACM0,baud=115200" \
    reset
```

The keyboard now boots ZMK. USB HID and BLE should work immediately.

### Updating Firmware Later (after initial flash)

Once ZMK is running, you never need the OTA bridge again. Update by re-running Stage 2 only:

```bash
python3 scripts/flash_ota.py zmk/build/zephyr/zmk.bin  # skips bridge, updates directly
# OR
~/go/bin/mcumgr image upload zmk/build/zephyr/zmk.signed.bin
```

---

## Reverting to Stock Firmware

### Software revert (no hardware needed)

```bash
# Restore stock firmware — works as long as MCUboot or the OTA bridge is running
bash restore_stock.sh -y
```

This writes `firmware/code_2M_v2_patched.bin` back via the `flash_mgmt` mcumgr group.

### Hardware recovery (Telink Burning Board)

If both the ZMK app and OTA bridge are gone (extremely unlikely given MCUboot's watchdog revert):

1. Telink TLSRGSOCBK56B Burning Board (~$15)
2. Connect 3 DuPont wires to SWS/GND/VCC pads on the PCB
3. Use Telink BDT tool → B91 → load `firmware/code_2M_v2_patched.bin` → flash

---

## Customizing the Keymap

Edit `zmk/boards/crush80/crush80.keymap` and rebuild. Or use [ZMK Studio](https://zmk.studio) in Chrome/Edge over BLE — no rebuild needed for keymap changes.

**Unlock ZMK Studio:** Press `Fn+ESC` on the keyboard.

For home row mods (the original purpose of this project), see [`docs/home_row_mods.md`](docs/home_row_mods.md) for the balanced-flavor configuration.

---

## Enabling 2.4 GHz Dongle Mode

> Status: **placeholder — one-time setup required**

The 2.4 GHz access code is device-specific and not in the firmware binary. You need to sniff it once from the air using a Raspberry Pi + nRF24L01+ module.

**Full instructions:** [`docs/hardware_guide_2g_and_diy.md`](docs/hardware_guide_2g_and_diy.md), Part 2.

**After sniffing:**
1. Edit `scripts/crush80_2g_config.py` — fill in `TPLL_ACCESS_CODE` and `TPLL_CHANNELS`
2. Run: `python3 scripts/crush80_2g_config.py` — generates the C header
3. Rebuild and flash

---

## Enabling RGB (AW20216S)

> Status: **partial — SPI pin extraction required**

The AW20216S driver is written and complete. The SPI pin numbers need to be confirmed from the firmware binary using Ghidra.

**Extraction procedure:** [`docs/rgb_pin_extraction.md`](docs/rgb_pin_extraction.md) *(to be written after Ghidra analysis)*

**Quick path:** If you want to attempt bring-up before running Ghidra, try the Rainy 75 GSPI pins first (PC0=CS, PC1=CLK, PC2=MOSI) — they may or may not match the Crush 80 PCB layout.

---

## Repository Layout

```
.github/workflows/build.yml       ← GitHub Actions CI (builds firmware on push)
zmk/
  boards/crush80/                 ← Board definition (DTS, keymap, Kconfig)
  drivers/
    bluetooth/                    ← BLE HCI shim (wraps Telink BLE blob)
    usb/                          ← USB device driver (B91-specific)
    sensor/                       ← Battery ADC driver
    watchdog/                     ← Hardware watchdog driver
    led/                          ← AW20216S LED driver + RGB engine
    radio/                        ← 2.4G TPLL driver (placeholder until access code known)
  src/                            ← poweroff, flash_mgmt, boot_diag, mcuboot_confirm
  west.yml                        ← Pins ZMK + Zephyr + HAL + MCUboot versions
conf/
  app.conf                        ← ZMK app Kconfig (BLE, USB, RGB, sleep, Studio)
  mcuboot.conf                    ← MCUboot Kconfig
  mcuboot.overlay                 ← MCUboot DTS overlay
  ota-bridge.conf                 ← Minimal build for initial OTA flash
patches/                          ← Small fixes applied at west update time
firmware/                         ← Stock firmware images (for restore)
scripts/
  flash_ota.py                    ← Stage 1 flasher (uses Telink OTA protocol)
  crush80_2g_config.py            ← 2.4G config — EDIT THIS to enable dongle mode
  sniff_2g_access_code.py         ← RPi + nRF24L01+ access code sniffer
  analyze_spi_led.py              ← Firmware analysis (confirmed AW20216S)
docs/                             ← Hardware guides, technical reports
```

---

## Known Limitations

| Feature | Status | Notes |
|---|---|---|
| USB HID (1000 Hz) | ✅ Works | Full NKRO |
| Bluetooth LE | ✅ Works | 3 profiles, ZMK Studio |
| Home row mods / all ZMK behaviors | ✅ Works | — |
| Battery reporting | ✅ Works (likely) | Validate ADC pin at bring-up |
| Deep sleep | ✅ Works | 15 min idle |
| Per-key RGB | ⚠️ Pending | Needs AW20216S SPI pin extraction (Ghidra) |
| 2.4 GHz dongle | ⚠️ Pending | Needs access code sniff (RPi + nRF24L01+) |
| VIA support | ❌ Removed | Replaced by ZMK Studio (better) |

---

## Credits

- ZMK firmware: [zmkfirmware/zmk](https://github.com/zmkfirmware/zmk) (MIT)
- Zephyr RTOS: [zephyrproject-rtos/zephyr](https://github.com/zephyrproject-rtos/zephyr) (Apache-2.0)
- Telink BLE blob: fetched at build time from [telink-semi](https://github.com/telink-semi/zephyr_hal_telink_b91_ble_lib) — proprietary, not redistributed
- Based on: [scholzri/rainy75-zmk](https://github.com/scholzri/rainy75-zmk) (Apache-2.0)

*Independent project — not affiliated with Wobkey, Telink, or Evision.*
