# Wobkey Crush 80 — ZMK Firmware

Open-source ZMK firmware for the Wobkey Crush 80 (Telink TLSR9511, B91, RISC-V).

**Features:** USB HID (1000 Hz) · Bluetooth LE (3 profiles) · home row mods + all ZMK behaviors ·
battery gauge · deep sleep · MCUboot with safe revert · ZMK Studio live keymap editing.

**Status:** USB + BLE functional. RGB requires AW20216S SPI pin extraction (see `docs/ghidra_spi_extraction.md`). 2.4 GHz dongle requires one sniff session (see `docs/hardware_guide_2g_and_diy.md`).

---

## Quick Start

### Option A — GitHub Actions (no local toolchain needed)

1. Fork this repository on GitHub.
2. Push any change (or trigger manually via **Actions → Build Crush 80 ZMK Firmware → Run workflow**).
3. Download the firmware artifact from the workflow run.
4. Flash following [Part 3: Flashing](#part-3-flashing) below.

### Option B — Local Build (WSL Ubuntu 24.04)

```bash
# 1. One-time toolchain setup (needs sudo):
sudo apt-get update && sudo apt-get install -y git cmake ninja-build python3-pip wget xz-utils libusb-1.0-0-dev file
pip3 install west pyelftools

# Zephyr SDK 0.17.0 — REQUIRED (not 0.17.4, which breaks hal_telink)
cd ~
wget https://github.com/zephyrproject-rtos/sdk-ng/releases/download/v0.17.0/zephyr-sdk-0.17.0_linux-x86_64.tar.xz
tar xf zephyr-sdk-0.17.0_linux-x86_64.tar.xz
cd zephyr-sdk-0.17.0 && ./setup.sh -t riscv64-zephyr-elf

# 2. Clone and init workspace:
git clone https://github.com/YOUR_USERNAME/Wobkey_Crush_80_Patched_Firmware crush80-zmk
cd crush80-zmk/zmk
west init -l .
west update                # ~500 MB download — takes 5–10 min

# 3. Fetch Telink BLE blob (fetched from Telink's public GitHub, not redistributed here):
cd ..
bash fetch_ble_blob.sh

# 4. Install Zephyr Python requirements:
pip3 install -r zmk/zephyr/scripts/requirements.txt

# 5. Build all targets:
export ZEPHYR_SDK_INSTALL_DIR=~/zephyr-sdk-0.17.0
bash build.sh -a
```

Build outputs:
```
zmk/build-mcuboot/zephyr/zephyr.bin      ← MCUboot bootloader (only needed for SWS recovery)
zmk/build-bridge/zephyr/zmk.bin         ← OTA bridge (Stage 1 flash)
zmk/build/zephyr/zmk.signed.bin         ← ZMK application (Stage 2 flash)
```

---

## Part 1: Customizing the Keymap

Edit `zmk/boards/crush80/crush80.keymap` and rebuild.

**Key bindings reference:** https://zmk.dev/docs/keymaps/behaviors

**Live editing without rebuilding:** Use [ZMK Studio](https://zmk.studio/) over Bluetooth
in Chrome or Edge. Unlock with `Fn + ESC`. No VIA — ZMK Studio is the replacement.

**Home row mods:** Add to the keymap behaviors section:
```dts
hml: home_row_mod_left {
    compatible = "zmk,behavior-hold-tap";
    #binding-cells = <2>;
    flavor = "balanced";          // ZMK equivalent of QMK PERMISSIVE_HOLD
    tapping-term-ms = <280>;
    quick-tap-ms = <175>;
    require-prior-idle-ms = <150>;
    bindings = <&kp>, <&kp>;
    hold-trigger-key-positions = <KEYS_R THUMBS>;
    hold-trigger-on-release;
};
```

---

## Part 2: Adding 2.4 GHz Dongle Support

The 2.4 GHz access code must be captured from your keyboard+dongle pair.
Full instructions in `docs/hardware_guide_2g_and_diy.md`.

**Once you have the code**, open `scripts/crush80_2g_config.py` and fill in two lines:
```python
TPLL_ACCESS_CODE = 0xXXXXXXXX    # from sniffer output
TPLL_CHANNELS    = [17, 35, ...]  # from sniffer output
```

Then regenerate the header and rebuild:
```bash
python3 scripts/crush80_2g_config.py   # writes zmk/drivers/radio/crush80_2g_constants.h
bash build.sh -a                       # rebuild all
```

---

## Part 3: Flashing

### Prerequisites

- Keyboard plugged in via USB-C and switched to USB mode
- On Linux: `docs/99-wobkey-crush80.rules` installed (`sudo cp docs/99-wobkey-crush80.rules /etc/udev/rules.d/ && sudo udevadm control --reload`)
- On Windows: `firmware/v2.exe` (the stock OTA flasher) available as fallback

### Stage 1 — Flash OTA Bridge

This replaces the stock Evision firmware with a minimal ZMK build that exposes USB DFU.
The stock Telink OTA bootloader in ROM survives this step — you can always reflash.

```bash
# Linux / WSL (keyboard must be visible as /dev/hidraw*)
python3 scripts/flash_ota.py zmk/build-bridge/zephyr/zmk.bin

# Expected output:
# Loading zmk.bin... Format: raw, Size: ~83KB, CRC: OK
# [100%] 1734/1734 packets | ~23s | OTA SUCCESS!
```

**Windows fallback** (if Linux OTA fails):
1. Open `firmware/v2.exe`
2. Replace the embedded firmware resource with `zmk/build-bridge/zephyr/zmk.bin`
   (requires ILSpy or resource hacker to replace `code_2M` resource, or use WSL with `usbipd-win`)

After Stage 1: keyboard appears as `/dev/ttyACM0` (USB-CDC serial device).

### Stage 2 — Flash ZMK via mcumgr DFU

```bash
# Install mcumgr (one time):
go install github.com/apache/mynewt-mcumgr-cli/mcumgr@latest

# Upload ZMK app:
~/go/bin/mcumgr --conntype serial --connstring "dev=/dev/ttyACM0,baud=115200" \
    image upload zmk/build/zephyr/zmk.signed.bin

# Confirm and reboot:
~/go/bin/mcumgr --conntype serial --connstring "dev=/dev/ttyACM0,baud=115200" \
    image confirm
~/go/bin/mcumgr --conntype serial --connstring "dev=/dev/ttyACM0,baud=115200" \
    reset
```

After Stage 2: keyboard boots ZMK. USB HID works immediately.

### Updating Firmware (After Initial Setup)

Once MCUboot is installed, future updates skip Stage 1:
```bash
# Rebuild after keymap/config changes:
bash build.sh

# Flash new app only:
~/go/bin/mcumgr --conntype serial --connstring "dev=/dev/ttyACM0,baud=115200" \
    image upload zmk/build/zephyr/zmk.signed.bin && \
~/go/bin/mcumgr --conntype serial --connstring "dev=/dev/ttyACM0,baud=115200" \
    image confirm && \
~/go/bin/mcumgr --conntype serial --connstring "dev=/dev/ttyACM0,baud=115200" \
    reset
```

---

## Part 4: Reverting to Stock Firmware

### Option A — Automated (if ZMK OTA bridge or ZMK app is running)

```bash
bash restore_stock.sh -y
# Writes firmware/code_2M_v2_patched.bin back via mcumgr flash_mgmt group.
# Takes ~40 seconds. Keyboard reboots to stock Evision firmware.
```

### Option B — Manual OTA (if keyboard is in OTA bridge mode)

```bash
python3 scripts/flash_ota.py firmware/code_2M_v2_patched.bin
```

### Option C — Hard Recovery via SWS (if both A and B fail)

Requires: Telink Burning Board (TLSRGSOCBK56B, ~$15), 3 Dupont wires.

1. Open the keyboard (ball-catch quick release, no tools)
2. Connect Burning Board to the 3 SWS pads near the MCU: GND, VCC, SWS
3. Use Telink BDT tool (Windows): B91 chip → load `firmware/code_2M_v2_patched.bin` → Flash

---

## Part 5: What's Working vs Pending

| Feature | Status | Notes |
|---|---|---|
| USB HID (1000 Hz) | ✅ Working | |
| Bluetooth LE (3 profiles) | ✅ Working | Pair with Fn+F1/F2/F3 |
| All 88 keys | ✅ Working | |
| Layers, hold-tap, home row mods | ✅ Working | |
| ZMK Studio (live edit) | ✅ Working | Via BLE in Chrome/Edge |
| Battery gauge | ✅ Working | BLE battery service |
| Deep sleep (15 min idle) | ✅ Working | |
| Safe revert to stock | ✅ Working | `restore_stock.sh` |
| Per-key RGB (154 LEDs) | ⚠️ Pending | Need AW20216S SPI pins from Ghidra |
| 2.4 GHz dongle | ⚠️ Pending | Need access code from nRF24 sniffer |

---

## Repository Layout

```
zmk/                    ZMK firmware module (board + drivers)
  boards/crush80/       Board definition (DTS, keymap, Kconfig)
  drivers/
    bluetooth/          BLE HCI shim for Telink blob
    led/                AW20216S driver + RGB engine
    radio/              2.4G TPLL driver (placeholder until access code known)
    sensor/             Battery ADC
    usb/                USB device driver
    watchdog/           Hardware watchdog
  west.yml              Dependency manifest (ZMK, Zephyr, HAL, MCUboot)

conf/                   Build configuration overlays
  app.conf              Main ZMK app config
  mcuboot.conf          MCUboot config
  ota-bridge.conf       OTA bridge (minimal DFU-only build)

patches/                Patches applied during build
  zmk-src/              ZMK: USB_NO_VBUS_DETECT (sleep fix)
  hal_telink/           HAL: BT_HCI_B91 fix
  mcuboot/              MCUboot: B91 RISC-V boot fixes
  zephyr/               Zephyr: GPIO interrupt fixes

firmware/               Critical firmware files
  code_2M_v2_patched.bin  STOCK RESTORE IMAGE — keep this safe
  v2_patched.bin          Stock firmware binary (for analysis)
  v2.exe                  Windows OTA flasher (backup)

scripts/                Operational scripts
  flash_ota.py          Stage 1 OTA flasher (Linux)
  crush80_2g_config.py  2.4G access code configuration
  sniff_2g_access_code.py  nRF24L01+ sniffer for RPi
  analyze_spi_led.py    AW20216S pin analysis tool
  check_2g_protocol.py  2.4G protocol analysis

docs/                   Human-readable documentation
  ghidra_spi_extraction.md  How to extract AW20216S SPI pins
  hardware_guide_2g_and_diy.md  2.4G hardware + LG TV guide
  Crush80-RGB-USB.JSON  Original VIA layout (LED map reference)

.github/workflows/      CI
  build.yml             Builds all firmware targets on push

.claude/                AI analysis notes (reference only)
.backup/                Archived files not needed for ZMK work
```

---

## Bluetooth Pairing

1. Press `Fn + F1` for BT profile 1, `Fn + F2` for profile 2, `Fn + F3` for profile 3
2. LED blinks — keyboard advertises as "Crush 80"
3. Pair on host — enter 6-digit passkey displayed on screen and type it on the keyboard
4. `Fn + F5` toggles between USB and Bluetooth output
5. `Fn + Delete` clears the current BT profile (re-pair from scratch)

---

## License

Firmware code: Apache 2.0  
ZMK: MIT | Zephyr: Apache 2.0 | MCUboot: Apache 2.0  
Telink BLE blob: proprietary (Telink NDA) — fetched at build time, not redistributed
