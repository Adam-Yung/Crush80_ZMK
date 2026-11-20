# Todo

In order. Strike nothing; delete a line when it is done and move the fact to `status.md`.

1. Flash the private build with Base-layer backlight off and Nav blue (run in `Adam-Yung/keybindings`); confirm after testing. Verify the backlight-off behaviour and the brightness keys on Base.
2. Space ExtNav layer: reported misbehaving on the board with the old keymap; re-test with the ported keymap and fix if it persists.
3. USB upload stalls: try upstream's Zephyr USB transfer-slot patches (RitwickVerma/Crush80_ZMK `patches/zephyr/0004`-`0013`, 0009 first) in a branch; trial-boot; confirm uploads no longer stall.
4. Hardware test plan T3 (`recover` rehearsal) and the revert-after-failed-trial path through `./crush80 update` itself. T5 (watchdog). T7 (stock switch) needs an SWS probe.
5. If T3 passes: delete `scripts/legacy/`, update `guides/recovery.md`.
6. Add the confirmed image to `releases/MANIFEST.sha256` after a day of use.
7. Decide on the earlier password string in this repo's git history (08b88d1): change the password if it was real; rewrite history only if wanted.
8. Optional: upstream's per-key RGB engine, VIA and OpenRGB (see `decisions/rgb.md`).
9. `docs/code/` mirrors for the untouched source files, as they are touched.
