# Recovery

Work down the ladder; stop at the first step that works. Everything here needs only the USB cable except the last step.

| Symptom | Do this |
|---|---|
| A new image misbehaves but the board still runs (wrong keys, no LEDs, flaky) | Unplug, wait 5 s, replug. An unconfirmed trial reverts to the previous image. `./crush80 status` should show the old hash. |
| New image: board dead or hung (no typing, USB dead) | Same: unplug, wait 5 s, replug. A trial that never confirmed reverts at that cold boot. |
| Reverted, but the old image also looks wrong, or `status` times out | Unplug 10 s (full power-down), replug, retry `./crush80 status`. |
| Board hangs 2 s after every boot (the 2026-08 failure) and revert did not help | `./crush80 recover` (below). |
| App works and you want the bootloader on purpose | **Fn+Esc**: reboots into MCUboot serial recovery. Upload with `mcumgr image upload`. |
| No USB device appears at all | Unplug 10+ s, try another cable and a direct port (no hub). Then `./crush80 recover`. |
| Still nothing | SWS probe and `backups/<timestamp>/flash.bin` (last step). |

Software resets never swap images on this board. Every revert and every upgrade needs a **physical unplug and replug**.

## `./crush80 recover`

Puts a hung board into the bootloader's serial recovery and loads the known-good image.

1. Unplug the board. Press Enter in the tool. Plug the board in.
2. The tool fires one tiny `flash_mgmt` erase of the slot 0 header the instant the port appears, inside the 1-2 seconds a hung app still answers.
3. Unplug, wait 3 s, replug. MCUboot finds no valid app and waits in serial recovery (`CONFIG_BOOT_SERIAL_NO_APPLICATION=y`). No app runs, so nothing can hang.
4. The tool uploads `releases/Crush80-No-RGB.bin` without time pressure. Unplug, wait 3 s, replug. The keyboard boots the known-good firmware.

Proven by hand on 2026-08-27 (`docs/incidents/2026-08-27-irq-lock-hang.md`); the scripted version has not run on hardware yet. The hand-run originals are in `scripts/legacy/`
(`force_recovery.py` then `mcumgr image upload`) and stay until `docs/guides/hardware-test-plan.md` T4 passes.

## Last resort: SWS

Needs a Telink SWS debug probe on the board's SWS pad and the vendor tools. Restore `backups/<timestamp>/flash.bin` to 0x0-0xFE000. Never write at or above 0xFE000: it holds RF calibration and the BLE MAC.
Without a backup, `dist/crush80-mcuboot.bin` goes to 0x0 and `releases/Crush80-No-RGB.bin` to 0x10000, then use `./crush80 status`.

## Never

- Do not `mcumgr image test` an unvalidated file by hand.
- Do not run any flash tool while the board is in a trial you have not either confirmed or reverted.
- Do not unplug during `stock-restore --commit` until stock firmware enumerates.
