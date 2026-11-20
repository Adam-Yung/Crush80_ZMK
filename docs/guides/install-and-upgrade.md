# Install, upgrade and switch firmware

How to put firmware on the board without risking it. The design reasoning is in `features/install-mechanism.md`; when something goes wrong, `guides/recovery.md`.

**Status: the host tool is unit-tested but has not yet run against the board.** First run: `guides/hardware-test-plan.md`.

## The rules in one paragraph

A new image is uploaded into slot 1 and marked for **one trial boot**. You power-cycle, the tool checks that the new image is the one running, you test the keyboard,
and only then does the tool confirm it. Until confirmation, **another unplug and replug puts the previous image back**, even if the new firmware is completely dead.
The bootloader is never rewritten in this flow.

## Before the first flash (once per board)

1. `./crush80 golden`: verifies `releases/` against `releases/MANIFEST.sha256`. This is the image `recover` loads if everything else fails.
2. `./crush80 backup` (about 3 minutes, board running ZMK, read-only): dumps flash 0x0-0xFE000 to `backups/<timestamp>/flash.bin` with a sha256. This is the full-board restore point for an SWS probe.
3. `./crush80 status`: slot 0 should show `confirmed active`. If it does not, stop; see `guides/recovery.md`.

## Upgrade ZMK to a new build (board already running ZMK)

```bash
bash build.sh --skip-bridge            # or add --rgb for the Reboot Pro RGB build
./crush80 check dist/crush80-zmk-app.signed.bin
./crush80 update dist/crush80-zmk-app.signed.bin     # same as: bash update.sh
```

`update` does, in this order, and stops at the first failure with the board's state spelled out:

1. Validates the image offline: MCUboot magic, header, SHA-256 of the contents, size fits the slot with its trailer. A raw `zmk.bin` or a corrupt file never leaves the computer.
2. Verifies the known-good images in `releases/`.
3. Talks to the board (`echo`), reads `image list`. **Refuses if the running image is itself an unconfirmed trial.**
4. Uploads, then checks slot 1 holds exactly the uploaded hash. Marks it for test. Checks it is pending.
5. Tells you to unplug, wait 3 seconds, replug. Waits for the port to disappear and return.
6. Reads `image list` again. Three outcomes:
   - **New hash running**: asks you to test (type, Fn layer, LEDs). You answer `y` and it confirms and re-reads to prove it.
   - **Old hash running**: the new image failed to start and MCUboot reverted. Nothing to do; the board is safe. Fix the build.
   - **No port or no answer**: unplug, wait 5 seconds, replug. The previous image returns. Still nothing: `./crush80 recover`.
7. If you answer `n`, it leaves the image unconfirmed. Unplug and replug to go back.

A trial that you neither confirm nor revert reverts at the next cold boot, including a deep-sleep wake. That is deliberate.

## First install: stock firmware to ZMK

Needs the stock board on USB (`320f:5055`), `pip` deps from `scripts/owner/install-deps.sh`, and a build in `dist/` (`bash build.sh`, bridge included).

```bash
bash install_zmk.sh
```

It validates the images, then uses the stock firmware's own OTA protocol (`scripts/flash_ota.py`) to put a bridge image in the second bank, which stays safe against a power loss
because the stock bank is untouched until the new one is complete. The bridge then writes MCUboot and the app. Run `./crush80 backup` as soon as ZMK is up.

## Switch back to stock firmware

Stock images are in `firmware/Wobkey_Crush_80_Patched_Firmware/firmware/` (`firmware.bin`, `firmware_patched.bin`, `v2_patched.bin`); use the one matching your board's original. `param_128K.bin` and the 2 MB images are not flash targets for this tool.

```bash
./crush80 stock-restore PATH/firmware.bin            # dry run: stages in slot 1, verifies by read-back, changes nothing else
./crush80 backup                                     # full backup, if the last one predates your current firmware
./crush80 stock-restore PATH/firmware.bin --commit   # replaces bootloader and app
```

**This is the one operation with a real power-loss window.** The commit erases the sectors the stock image needs (about 30) and copies it: a few seconds in which a power cut
leaves no bootable image and only an SWS probe plus `backups/` brings the board back. Before `--commit`: USB cable firmly seated, no hub, laptop on power with sleep prevented
(`caffeinate -dis ./crush80 ...`), and the SWS probe within reach. The firmware erases only what the stock image occupies before the copy and cleans the rest afterward, to keep that window short.
After the commit the board resets itself and enumerates as stock (`320f:5055`). Do not unplug until it does.

To return to ZMK afterwards, run `bash install_zmk.sh` again.

## Recovery images and what is allowed to confirm

| Image | Self-confirms? | Use |
|---|---|---|
| `releases/*` (golden, built before trial boot existed) | yes, after 5 s | what `recover` loads; works with no host |
| anything built from this tree with `CONFIG_CRUSH80_MANUAL_CONFIRM=y` (default) | no, the host confirms | every normal and experimental build |

When you want a build to become the new golden image: it has run, been confirmed, you used it for a day, then copy it to `releases/` and add its line to `MANIFEST.sha256`.
That image is trial-boot, so it does not self-confirm; after `recover` loads it, run `./crush80 confirm`.
