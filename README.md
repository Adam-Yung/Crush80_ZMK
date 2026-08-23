# Crush 80 ZMK Firmware

Custom ZMK firmware for the Wobkey Crush 80 mechanical keyboard (Telink TLSR9518/B91).

## Prerequisites

- macOS (arm64)
- West workspace at `~/Projects/crush80-workspace` (run `bash install_zmk.sh` to set up)
- Zephyr SDK at `~/zephyr-sdk-0.17.0`
- Go mcumgr: `~/go/bin/mcumgr`
- Python 3 with pyserial: `pip install pyserial`

## Quick Start

### Build
```bash
bash build.sh --skip-bridge --skip-mcuboot
```

### Flash
```bash
bash flash.sh --build   # builds then flashes
# or just flash (if already built):
bash flash.sh
```

### Recovery (if keyboard SMP is unresponsive)
```bash
bash flash.sh --build   # build first
# Then unplug keyboard, run:
python3 scripts/recovery_flash.py
# Plug keyboard back in when prompted
```

## Configuration

Keymap configuration lives in `~/.config/DOTFILES/keybindings/crush80-zmk/`.
The build script syncs it automatically.

Key files:
- `crush80.keymap` — Key bindings (layers, home row mods, macros)
- `app.conf` — ZMK application config (USB, BLE, battery, etc.)

## Project Structure

```
zmk/boards/crush80/     Board definition (DTS, defconfig)
conf/                   Build configuration
scripts/                Flashing and diagnostic tools
dist/                   Built firmware artifacts (gitignored)
docs/                   Technical documentation
```

## Key Technical Notes

- Matrix: 6 rows × 16 columns, col2row diodes
- GPIO columns: PE0,PE1,PE2,PE4,PE5,PE6,PB0,PB1,PB2,PB3,PB4,PB5,PB6,PC0,PC1,PC4
- GPIO rows: PD7,PD2,PD3,PD4,PD5,PD6
- PE0/PE1/PE2 are shared between matrix scan and LED SPI — HSPI is disabled
- Flash via MCUboot image swap: upload → test → reset → confirm
- NEVER set CONFIG_LOG_DEFAULT_LEVEL=4 (bricks SMP serial communication)
