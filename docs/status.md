# Status

**Last updated:** 2026-11-20 (evening). The board runs the confirmed per-key RGB image `ed774974` (firmware commit `611b0d1`, built by the private keybindings CI) in slot 0; slot 1 holds the previous confirmed image `f8768f32`. Verified on the board: held home-row mods light only their own key, Nav palette, typing. Still open: see `todo.md` (Caps+F5, OS persistence, Bluetooth, deep-sleep wake).

## Works (on the board, before this branch)

Keys, USB HID, BLE with 5 profiles, Mac mode, deep sleep, MCUmgr over USB serial, ZMK Studio. Running image: `releases/Crush80-No-RGB.bin` (self-confirming build). No RGB.

## Built on this branch, verified on the host only

| Piece | Verified how | Not verified |
|---|---|---|
| `./crush80` (check, golden, status, backup, update, confirm, recover, stock-restore) | 29 unit tests (`scripts/tests`): CBOR, SMP framing against log noise and split delivery, image validation against the real release image, the update state machine against a fake board incl. revert, decline, unconfirmed-blocks, corrupt-image, tampered-golden | Everything that touches the serial port or `mcumgr`: `RawSerial`, `Mcumgr` wrapper output parsing against the real CLI, `backup`, `recover`, `stock-restore` |
| Trial boot (`CONFIG_CRUSH80_MANUAL_CONFIRM`) in `mcuboot_confirm.c` | code review | **not compiled**; revert-on-power-cycle on this board (hardware test T2) |
| Shorter erase window in the `flash_mgmt` commit trampoline | code review | **not compiled**, not run (T7) |
| WS2812 RGB driver (from `crush80-rgb.patch`), `--rgb` build, overlay, keymap bindings | patch applies cleanly; read in full; safety properties reviewed | **not compiled**, not run; board model unconfirmed (`features/rgb.md`, "Which board is this") |
| Docs, conventions, gate (`scripts/gate/verify.sh`) | gate runs green | |

## Blockers

1. **Build environment.** The Python deps for west are gone from this machine (`west`, `pyyaml`, `pyelftools` do not import). The owner runs `bash scripts/owner/install-deps.sh --run`; until then no firmware here can be compiled.
2. **Board.** Needs to be connected for `guides/hardware-test-plan.md`.
3. **Board model.** Reboot Pro (WS2812) vs the old AW20216S reading: PCB inspection decides.

## Documentation coverage

`docs/code/` mirrors exist for the files added or changed on this branch (`mcuboot_confirm.c`, `flash_mgmt.c`, the RGB driver, `scripts/crush80/`). The rest of the source tree has none yet; add a mirror when a file is next touched.

## 2026-11-19: first CI image did not enumerate
CI image (hal_telink at `main`) was swapped in as a trial, showed no serial port, and a power cycle reverted to the known-good image (revert path works).
Suspected cause: `hal_telink` was unpinned. Now pinned to 4226c7fc (the commit the known-good build used); CI fails if it drifts. Not yet confirmed by a successful trial boot.

## 2026-11-20: what the first CI trial image taught us
The first CI image booted (keyboard typed) but never showed a USB serial port. It was built from `keymaps/stock.keymap` and a trimmed `conf/app.conf`, not the owner's personal config that built the known-good image.
CI now builds `keymaps/personal.keymap` (the owner's keymap with the password macro replaced by a placeholder; the real one stays in `~/.config/DOTFILES`, which local `build.sh` prefers) and `conf/app.conf` is back to the proven LOG/console lines. `hal_telink` pin did not change the image. Still unverified on hardware.

## 2026-11-20: RGB works, install path proven, keymap ported (not yet built)
- **Proven on the board:** CI-built plain image trial-booted and confirmed; CI-built RGB image trial-booted, all 154 LEDs light (keys, side bar, logo), Fn+Backspace / Fn+\\ / Fn+Up / Fn+Down work, typing normal. Brightness is capped at 25 % (`conf/rgb.conf`), dimmer than stock.
- **Upload stalls** seen earlier were not reproduced with `mcumgr` called directly (about 80 s for 289 KB). Cause unknown; upstream (Ritwick Verma's fork) carries USB transfer-slot fixes (Zephyr patches 0004-0013) that may explain it. Not applied yet.
- **Host bug fixed:** the SMP reply decoder rejected indefinite-length CBOR, so every `backup` / `recover` / `stock-restore` reply was dropped. Fixed in `c5b7d06`; `./crush80 backup` now works (backup `53d78d52...` taken).
- **Keymap ported** from `kanata-macos.kbd` and **moved out of this public repo** into the private `Adam-Yung/keybindings` (see `decisions/keymap-private.md`, `guides/keymap.md`). Built there by this repo's reusable workflow. Verified on the board: layers, home-row mods, colours. Layers Base, Native, Fn, Nav, ExtNav, Sym, Desk, DeskMove; F5/F6 backlight brightness, Pause backlight toggle.
- **Layer / modifier colours:** `zmk/src/layer_rgb.c` (`docs/code/zmk/src/layer_rgb.c.md`), verified on the board. **Not yet verified:** Base layer backlight off (`layer-on`), added after the test.
- Known issue to revisit: the old ExtNav (Space in Nav) layer misbehaved on the board.

## 2026-11-20 overnight: OS layers, per-key RGB, battery (built in CI, NOT flashed, NOT run on the board)
Verified: CI compiles both images with the private keymap (firmware `9f97bdf`, run 44729894315, hashes checked, `./crush80 check` OK, RGB image 297,006 bytes); the build fails if the RGB config silently drops (it did once: `LED_STRIP` was no longer selected). 35 host tests and the gate pass. The firmware layout was checked against `kanata-macos.kbd` and `kanata-windows.kbd` position by position (884 of 914 identical, the rest deliberate).
Not verified (needs the board, `guides/hardware-test-plan.md` T8): everything about behaviour.
- **macOS + Windows**: 13 layers, marker layer + conditional layers, `&os_win` / `&os_mac` with a saved choice (`decisions/os-layers.md`, `code/zmk/src/crush80_os.c.md`).
- **Per-key backlight engine** (`code/zmk/src/rgb/engine.c.md`): side bar = layer colour, keys coloured by what they do, dark when unbound, Base dark, held mod lights only itself, idle off, Bluetooth off unless toggled. LED order from upstream's stock-firmware table, re-keyed by matrix position and tested.
- **Battery** (`features/battery.md`): idle/Bluetooth backlight policy; **deep-sleep wake pins corrected** to this board's matrix (`code/zmk/src/poweroff.c.md`), untested.
- **Home-row-mod hand split corrected** (the position lists were shifted one key in several rows): the mods will feel different, probably better.
- `./crush80` host bug (CBOR) fixed earlier; `build.sh` now checks the final configuration for RGB builds.
