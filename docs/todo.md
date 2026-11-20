# Todo

In order. Strike nothing; delete a line when it is done and move the fact to `status.md`.

1. **Owner:** `bash scripts/owner/install-deps.sh --run`, then `bash build.sh --skip-bridge` and `bash build.sh --skip-bridge --rgb`. Fix whatever the first compile of this branch reports (the RGB driver is the likely source).
2. **Owner:** open the case, confirm the LED type (`features/rgb.md`, "Which board is this").
3. Connect the board; run `guides/hardware-test-plan.md` T1 to T4. Agents do not flash without the user watching.
4. T5 (watchdog), then T6 (RGB). Record each result in `status.md`.
5. If T4 passes: delete `scripts/legacy/`, update `guides/recovery.md`.
6. If T6 passes: decide whether RGB becomes part of the default build; add the new image to `releases/MANIFEST.sha256` after a day of use.
7. T7 (stock switch) when an SWS probe is at hand.
8. `docs/code/` mirrors for the untouched source files, as they are touched.
