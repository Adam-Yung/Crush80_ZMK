# Status

**Last updated:** 2026-11-19, branch `rgb-and-safe-install` (uncommitted). The board is not connected; nothing below has run on hardware.

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
