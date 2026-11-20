---
name: crush80-firmware
description: >-
  Build, flash, recover and debug the Wobkey Crush 80 ZMK firmware (Telink B91). Use when working on Crush 80
  firmware, flashing or recovering the board, RGB, or the board DTS/keymap.
disable-model-invocation: true
---

# Crush 80 ZMK Firmware

Read `AGENTS.md` and `docs/status.md` first. The procedures live in the docs, not here, so there is one copy:

| Task | Read |
|---|---|
| Build | `docs/guides/build.md` |
| Install, upgrade, switch to stock | `docs/guides/install-and-upgrade.md` |
| Board hung, dead or not enumerating | `docs/guides/recovery.md` |
| First run of a new image on hardware | `docs/guides/hardware-test-plan.md` |
| RGB | `docs/features/rgb.md` |
| Why the install is built this way | `docs/features/install-mechanism.md`, `docs/decisions/install-safety.md` |

Flash only with `./crush80`. Never flash an experimental image unless the user says the board is connected and they are watching it.
