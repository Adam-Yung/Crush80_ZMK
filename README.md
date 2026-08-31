# Crush 80 ZMK Firmware

Custom ZMK firmware for the Wobkey Crush 80 mechanical keyboard (Telink TLSR9518/B91 RISC-V).

## Features

- Full ZMK support: USB HID, Bluetooth 5.0, MCUboot DFU
- MCUmgr firmware updates over USB serial (no special hardware needed)
- Stock QWERTY keymap included (ready to flash out of the box)
- Example advanced keymap with Home Row Mods, Nav/Sym layers, Mac mode

## Quick Start (New User)

### 1. Set up the build environment

```bash
git clone https://github.com/Adam-Yung/Crush80_ZMK.git
cd Crush80_ZMK
bash setup.sh
```

This installs: Zephyr SDK, west, Python dependencies, Go mcumgr, and initializes the build workspace. Takes ~10 minutes on first run.

### 2. Build firmware

```bash
bash build.sh --skip-bridge --skip-mcuboot
```

This builds the ZMK firmware using the stock keymap. Output: `dist/crush80-zmk-app.signed.bin`

### Pre-built Firmware

If you don't want to build from source, use the pre-built release:

| File | Description |
|------|-------------|
| `releases/Crush80-No-RGB.bin` | Default firmware — no RGB, battery optimized, 5 BT profiles, Mac mode |

Flash a pre-built release:
```bash
CRUSH80_FIRMWARE=releases/Crush80-No-RGB.bin bash update.sh
# Then unplug/replug
```

### 3. Install ZMK on a stock Crush 80

If your keyboard is still running the manufacturer firmware:

```bash
bash install_zmk.sh
```

This uses the OTA bridge method to replace the stock firmware with ZMK. To revert, use `python3 scripts/flash_mgmt_upload.py` with the stock firmware binary.

### 4. Update firmware (keyboard already running ZMK)

```bash
bash update.sh --build
```

Or if you've already built:

```bash
bash update.sh
```

After upload completes, **unplug the keyboard USB cable, wait 2 seconds, plug back in**. MCUboot swaps to the new firmware on cold boot.

## Emergency Recovery (Bricked Keyboard)

> **Symptom**: Keyboard stops typing ~2 seconds after plug-in. `mcumgr image upload` stalls or fails. USB device may enumerate but SMP commands timeout.

> **Cause**: Firmware bug where `irq_lock()` + unbounded busy-wait (`while (REG & BIT) {}`) creates a permanent system hang. All interrupts are masked, so USB, BLE, and kscan all die simultaneously.

### Fix: Force MCUboot Serial Recovery

```bash
# Step 1: With keyboard plugged in (even if hung), run:
python3 scripts/force_recovery.py

# Step 2: UNPLUG the keyboard, wait 2 seconds, REPLUG
# MCUboot enters serial recovery mode (no app runs — no hang!)

# Step 3: Upload known-good firmware:
PORT=$(python3 -c "import glob; p=glob.glob('/dev/cu.usbmodem*') or glob.glob('/dev/ttyACM*'); print(p[0] if p else '')")
~/go/bin/mcumgr --conntype serial --connstring "dev=$PORT,baud=115200" \
  image upload dist/crush80-zmk-app.signed.MACMODE-WORKING.bin

# Step 4: Unplug, wait 2 seconds, replug — keyboard boots normally
```

### How It Works

The firmware includes a custom `flash_mgmt` MCUmgr group (ID 64) that can erase flash sectors. `force_recovery.py` erases the slot 0 image header (address 0x10000, 4096 bytes). MCUboot is configured with `CONFIG_BOOT_SERIAL_NO_APPLICATION=y`, so when it sees no valid app header, it enters permanent serial recovery mode over USB. From there, firmware can be uploaded with no time pressure because no application code is running.

### Why Normal Recovery Doesn't Work

The normal `mcumgr image upload` requires the running app's SMP handler to process each upload chunk. When the system hangs 2 seconds after boot, only a few chunks transfer before the irq_lock deadlock kills everything. The `force_recovery.py` script only needs to send ONE small erase command within that 2-second window — which reliably succeeds.

---

## Keymap Configuration

### Available keymaps

| File | Description |
|------|-------------|
| `keymaps/stock.keymap` | Standard QWERTY + Fn layer (BT/USB controls). Default. |
| `keymaps/example.keymap` | Advanced: Home Row Mods, Nav/ExtNav, Sym, Mac mode (9 layers) |

### Using a custom keymap

Set the `CRUSH80_KEYMAP` environment variable before building:

```bash
export CRUSH80_KEYMAP=/path/to/my/crush80.keymap
bash build.sh --skip-bridge --skip-mcuboot
bash update.sh
```

### Keymap selection priority

1. `CRUSH80_KEYMAP` env var (explicit path to a `.keymap` file)
2. Dotfiles directory (`~/.config/DOTFILES/keybindings/crush80-zmk/`)
3. `keymaps/stock.keymap` (default)

## Environment Variables

| Variable | Description |
|----------|-------------|
| `CRUSH80_KEYMAP` | Path to `.keymap` file to use for build |
| `CRUSH80_APP_CONF` | Path to `app.conf` to use for build |
| `CRUSH80_FIRMWARE` | Path to `.signed.bin` for `update.sh` (skips build) |
| `CRUSH80_ZMK_CONFIG` | Path to config directory (contains `crush80.keymap` + `app.conf`) |

## Scripts

| Script | Purpose |
|--------|---------|
| `setup.sh` | One-time environment setup (SDK, west, mcumgr) |
| `build.sh` | Build ZMK firmware from source |
| `update.sh` | Flash firmware onto a running ZMK keyboard |
| `install_zmk.sh` | First-time install from stock manufacturer firmware |
| `fetch_ble_blob.sh` | Download Telink BLE binary blob |
| `scripts/force_recovery.py` | **EMERGENCY**: Force MCUboot recovery when system is hung |
| `scripts/flash_mgmt_upload.py` | Write firmware to flash in 256-byte chunks (for bricked keyboards) |
| `scripts/flash_ota.py` | Stage 1 OTA flash for initial ZMK install |
| `scripts/recovery_flash.py` | Recovery flash when SMP is unresponsive |
| `scripts/emergency_upload.py` | Power-cycle upload for hung firmware |

## Recovery

If the keyboard stops responding after a bad flash:

1. **Unplug and replug** — MCUboot auto-reverts if the new firmware doesn't confirm within 11 seconds
2. **Force MCUboot recovery** — `python3 scripts/force_recovery.py` (erases slot 0 header, forces MCUboot serial recovery on next boot)
3. **nRF Connect Device Manager** — Install on phone, connect via BLE, tap "Reset to firmware loader mode"
4. **Recovery flash** — `python3 scripts/recovery_flash.py` (unplug, run script, replug when prompted)
5. **Restore stock** — `python3 scripts/flash_mgmt_upload.py firmware/Wobkey_Crush_80_Patched_Firmware/firmware/v2_patched.bin`

## Project Structure

```
keymaps/                Custom keymap files (stock.keymap, example.keymap)
conf/                   Build configuration (app.conf, mcuboot.conf)
zmk/                    ZMK module (board def, drivers, DTS, source)
  boards/crush80/       Board definition (DTS, defconfig, matrix)
  drivers/              Platform drivers (USB, BLE, battery, watchdog, LED)
  src/                  Application source (boot_diag, flash_mgmt, etc.)
scripts/                Flashing and diagnostic tools
patches/                Zephyr and ZMK patches for B91 platform
docs/                   Technical documentation
dist/                   Built firmware artifacts (gitignored)
```

## Technical Notes

- MCU: Telink TLSR9518 (B91 RISC-V), 48 MHz, 128KB ILM + 128KB DLM, 1MB flash
- Matrix: 6 rows x 16 columns, col2row diode direction, 88 keys
- Flash layout: MCUboot (0x0-0x10000), App (0x10000-0x80000), Slot1 (0x80000-0xF0000)
- BLE: Telink proprietary blob (`liblt_9518_zephyr.a`)
- MCUboot swap requires **physical USB unplug/replug** (cold boot) — software reset alone does NOT trigger swap
- NEVER set `CONFIG_LOG_DEFAULT_LEVEL=4` (floods serial, bricks SMP)
- HSPI is disabled — PE0/PE1/PE2 are shared between matrix columns and LED SPI
