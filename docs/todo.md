# Todo

In order. Strike nothing; delete a line when it is done and move the fact to `status.md`.

1. **Owner, watching the board:** flash the overnight private build as a trial and run `guides/hardware-test-plan.md` T8 in order (LED map correctness first: wrong colour on a key means stop and report which). Confirm only after T8 steps 1-8 pass.
2. After confirming: T8 steps 9-10 (OS choice and backlight state survive a replug; Bluetooth backlight off; deep-sleep wake from every key group).
3. Reproduce or retire the Caps+F5 trial reset (`incidents/2026-11-20-trial-reverted-on-capslock-f5.md`) on the new engine.
4. LED map details: which of LEDs 92-153 are side bar versus logo (all 62 get one colour now); LEDs 13 and 88 (keys this board does not have) stay dark; tune colours and overrides in the private generator.
5. Decide the home-row-mod feel after the position-list correction; tuning is in `keymap.md`.
6. USB upload stalls: try upstream's Zephyr USB transfer-slot patches (RitwickVerma/Crush80_ZMK `patches/zephyr/0004`-`0013`, 0009 first) on a branch; trial-boot; confirm uploads no longer stall.
7. Battery measurements (`features/battery.md`): CPU-load baseline with `conf/diag-power.conf`; then the BLE poll-period experiment, only if it shows a difference.
8. Hardware test plan T3 (`recover` rehearsal), the revert-after-failed-trial path through `./crush80 update`, T5 (watchdog), T7 (stock switch, SWS probe needed).
9. After a week of use: delete `zmk/src/layer_rgb.c` and its Kconfig/CMake entries (decision in `decisions/os-layers.md`); add the confirmed image to `releases/MANIFEST.sha256`.
10. The earlier password string in this repo's git history (08b88d1): change the password if it was real.
11. `docs/code/` mirrors for the untouched source files, as they are touched.
