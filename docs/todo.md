# Todo

In order. Strike nothing; delete a line when it is done and move the fact to `status.md`.

**Needs the owner at the board** (image `ed774974` is confirmed; `guides/hardware-test-plan.md` T8)
1. Replug check: OS choice (Fn+W / Fn+M) and backlight on/off survive a replug; idle turns the backlight off and a keypress brings it back.
2. Caps+F5: try it once on the current image. If the USB drop-off does not recur, retire `incidents/2026-11-20-trial-reverted-on-capslock-f5.md`.
3. Deep-sleep wake from every key group (the pin audit in `poweroff.c` has never run on hardware).
4. Side bar versus logo: which of LEDs 92-153 are which (all 62 get one colour now); then colours and overrides in the private generator. LEDs 13 and 88 (keys this board does not have) stay dark.
5. Retest Option shortcuts in a real app. Alt+2 / Alt+3 print `^[^@` / `^[^[` in a terminal (Alt prefix is present, so Alt reaches the host; probably the terminal's handling of Option+digit).

**Risk and hygiene**
6. Password: rotated by the owner 2026-11-20 and scrubbed from history. Still open: ask GitHub Support to purge the old commits (cached views and the `refs/pull/2` refs); then delete `dist/golden-old-DO-NOT-PUBLISH/`.
7. USB upload stalls (one earlier case, none recently): if they return, try upstream's Zephyr USB transfer-slot patches (RitwickVerma/Crush80_ZMK `patches/zephyr/0004`-`0013`, 0009 first) on a branch.

**Later**
8. Battery measurements (`features/battery.md`): CPU-load baseline with `conf/diag-power.conf`; then the BLE poll-period experiment, only if it shows a difference.
9. Hardware test plan T3 (`recover` rehearsal), the revert-after-failed-trial path through `./crush80 update`, T5 (watchdog), T7 (stock switch, SWS probe needed).
10. `docs/code/` mirrors for the untouched source files, as they are touched.

**Notes**
- Default firmware: `dist/crush80-default.signed.bin` (local, untracked; `./crush80 update` uses it when present). The personal image lives in the private keybindings repo (`crush80-zmk/firmware/`), never in this public repo (its macros are inside the binary). `releases/` stays the generic known-good recovery image for that reason.
