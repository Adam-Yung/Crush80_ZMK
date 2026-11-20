# Crush 80 ZMK Firmware

Custom ZMK firmware for the Wobkey Crush 80 mechanical keyboard (Telink TLSR9518/B91 RISC-V).

## Features

- Full ZMK support: USB HID, Bluetooth 5.0, MCUboot DFU
- [RGB build for the Crush 80 Reboot Pro](docs/features/rgb.md): per-key backlight that follows the layer and what each key does (built in CI; board verification in progress), macOS and Windows layer sets (Fn+W / Fn+M)
- **Safe updates:** every new firmware boots as a trial and reverts on a power cycle until you confirm it (`./crush80 update`)
- MCUmgr firmware updates over USB serial (no special hardware needed)
- Built in CI (GitHub Actions), downloaded with verified hashes, flashed only through `./crush80`
- Stock QWERTY keymap included (ready to flash out of the box); bring your own keymap from a private repo ([how](docs/guides/keymap.md))

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

For the Reboot Pro RGB build, run `bash build.sh --skip-bridge --rgb`.
Output: `dist/crush80-zmk-app-rgb.signed.bin`. See the [RGB setup and hardware test](docs/features/rgb.md).

### Pre-built Firmware

If you don't want to build from source, use the pre-built release:

| File | Description |
|------|-------------|
| `releases/Crush80-No-RGB.bin` | Default firmware — no RGB, battery optimized, 5 BT profiles, Mac mode |

Flash a pre-built release:
```bash
./crush80 update releases/Crush80-No-RGB.bin
```

### 3. Install ZMK on a stock Crush 80

If your keyboard is still running the manufacturer firmware:

```bash
bash install_zmk.sh
```

This uses the stock firmware's own OTA protocol to bring in a bridge image, which then installs ZMK. To go back to stock: `./crush80 stock-restore` (see [install and upgrade](docs/guides/install-and-upgrade.md)).

### 4. Load new firmware (keyboard already running ZMK)

The usual route is a **CI build**, so no local toolchain is needed:

```bash
git push                                          # CI builds a plain and an RGB image (Actions tab, about 5 min)
scripts/ci/fetch-build.sh                         # download the run for HEAD, verify hashes, check the images (never flashes)
./crush80 backup                                  # once: full flash dump, read-only, ~3 min
./crush80 update ci-downloads/<run>/crush80-firmware-*/crush80-zmk-app-rgb.signed.bin   # the command fetch-build prints
```

Or build locally (needs the west workspace): `bash build.sh --skip-bridge [--rgb]` then `./crush80 update dist/crush80-zmk-app.signed.bin`.

The new image boots as a **trial**: you unplug and replug, test the keyboard, and only then does the tool confirm it. Until it is confirmed, another unplug and replug restores the previous image,
even if the new firmware is dead. The bootloader is never rewritten. Full procedure: [docs/guides/install-and-upgrade.md](docs/guides/install-and-upgrade.md).

## If something goes wrong

Unplug, wait 5 s, replug: an unconfirmed trial reverts. If the board hangs after every boot, `./crush80 recover`. Everything else, down to the SWS last resort: [docs/guides/recovery.md](docs/guides/recovery.md).

---

## Keymap Configuration

This repo is public and holds **only generic keymaps**. A personal keymap (and any text macros in it) belongs in a **private** repo; the gate fails if one is committed here.

| File | Description |
|------|-------------|
| `keymaps/stock.keymap` | Standard QWERTY + Fn layer (BT/USB controls). Default, and what this repo's CI builds. |
| `keymaps/example.keymap` | Advanced example: Home Row Mods, Nav/ExtNav, Sym, Mac mode (9 layers) |

### Using your own keymap

**In CI, privately (recommended):** keep `crush80.keymap` in a private repo and call this repo's reusable workflow from there; the keymap and the build artifact never become public. Setup, the exact workflow, and how to update a keymap: [docs/guides/keymap.md](docs/guides/keymap.md).

**Locally:** `export CRUSH80_KEYMAP=/path/to/crush80.keymap`, then `bash build.sh --skip-bridge --rgb` and `./crush80 update dist/crush80-zmk-app-rgb.signed.bin`.

### Keymap selection priority (local builds)

1. `CRUSH80_KEYMAP` env var (explicit path to a `.keymap` file)
2. Dotfiles directory (`~/.config/DOTFILES/keybindings/crush80-zmk/`, or `CRUSH80_ZMK_CONFIG`)
3. `keymaps/stock.keymap` (default)

### Backlight colours

With the RGB build and a `crush80,rgb-scheme` node in the keymap, the side bar shows the layer and each key is coloured by what it does; held home-row mods light only their own key. See [docs/features/rgb.md](docs/features/rgb.md) and `docs/guides/keymap.md`.

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
| `./crush80` | **The tool.** `check`, `golden`, `status`, `backup`, `update`, `confirm`, `recover`, `stock-restore`. Standard library only; needs `mcumgr`. |
| `update.sh` | Wrapper: `./crush80 update`, optionally after `build.sh`. |
| `build.sh` | Build ZMK firmware (`--rgb` for the Reboot Pro RGB build). |
| `install_zmk.sh` | First install from stock firmware. |
| `setup.sh`, `fetch_ble_blob.sh`, `scripts/owner/install-deps.sh` | Owner-run setup and downloads. Agents never run these. |
| `scripts/flash_ota.py` | Stock OTA protocol (used by `install_zmk.sh`). |
| `scripts/gate/verify.sh` | Pre-commit gate: tests, syntax, doc links, known-good images, no personal keymap. |
| `scripts/ci/fetch-build.sh` | Download and verify a CI build (`[run-id] [owner/repo]`); never flashes. |
| `scripts/legacy/` | Hand-run recovery scripts kept until `./crush80 recover` is proven on hardware. |

Rules for contributors and agents: [AGENTS.md](AGENTS.md). Docs map: [docs/README.md](docs/README.md).

## Project Structure

```
keymaps/                Generic keymaps only (stock.keymap, example.keymap); personal keymaps live in a private repo
conf/                   Build configuration (app.conf, mcuboot.conf)
zmk/                    ZMK module (board def, drivers, DTS, source)
  boards/crush80/       Board definition (DTS, defconfig, matrix)
  drivers/              Platform drivers (USB, BLE, battery, watchdog, LED)
  src/                  Application source (boot_diag, flash_mgmt, etc.)
crush80                 Install/upgrade/recovery tool (wrapper); code in scripts/crush80/
scripts/                Tool package, tests, gate, owner-run installs, legacy recovery scripts
patches/                Zephyr and ZMK patches for B91 platform
docs/                   Documentation (map: docs/README.md)
dist/                   Built firmware artifacts (gitignored)
```

## Acknowledgements

- **Ritwick Verma** ([RitwickVerma/Crush80_ZMK](https://github.com/RitwickVerma/Crush80_ZMK), Apache-2.0): the key-to-LED order of the per-key backlight, read from the stock firmware's table, and the idea of colouring keys from the live keymap; also the kernel tick-rate fix in `conf/app.conf` (PR #2).
- **scholzri** (Rainy 75 ZMK, Apache-2.0): the WS2812 driver that fork builds on.

Details and licence text for the RGB engine: `zmk/src/rgb/NOTICE`.

## Technical Notes

- MCU: Telink TLSR9518 (B91 RISC-V), 48 MHz, 128KB ILM + 128KB DLM, 1MB flash
- Matrix: 6 rows x 16 columns, col2row diode direction, 88 keys
- Flash layout: MCUboot (0x0-0x10000), App (0x10000-0x80000), Slot1 (0x80000-0xF0000)
- BLE: Telink proprietary blob (`liblt_9518_zephyr.a`)
- MCUboot swap and revert require a **physical USB unplug/replug** (cold boot) — software reset alone does NOT trigger a swap
- NEVER set `CONFIG_LOG_DEFAULT_LEVEL=4` (floods serial, bricks SMP)
- The Reboot Pro RGB strip uses PB7 (PSPI MOSI) and PC2 (LED power); PE0/PE1/PE2 remain matrix columns
- The [factory 2.4 GHz USB receiver](docs/features/receiver.md) requires the stock Wobkey radio protocol
