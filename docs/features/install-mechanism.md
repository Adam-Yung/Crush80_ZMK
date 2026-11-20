# Install and upgrade mechanism

How the board gets firmware without being bricked, as built. Procedures are in `guides/install-and-upgrade.md`; recovery in `guides/recovery.md`; layout in `features/flash-layout.md`.

## Why it exists

2026-08-27: an RGB driver held `irq_lock()` in an unbounded busy-wait. The board hung two seconds after every boot. The watchdog safety net, which should have forced a revert before the 5 s self-confirm,
did not rescue it (cause not established, see the incident), uploads could not finish in two seconds, and the board was saved only by hand-written Python scripts that sent one erase command inside that window. See `incidents/2026-08-27-irq-lock-hang.md`.

## Layers, outermost first

| Layer | What it stops | Where |
|---|---|---|
| Offline image validation | a raw `zmk.bin`, a truncated or corrupt file, an image too big for its slot | `scripts/crush80/mcuimg.py` |
| Known-good image check | flashing with no verified fallback on disk | `releases/MANIFEST.sha256`, `flows.check_golden` |
| Preflight on the board | an update on top of an unconfirmed trial; a no-op re-flash; a slot 1 that does not hold what was uploaded | `flows.update` |
| **Trial boot, host confirm** | any bad image that boots: a power cycle reverts to the previous one | `CONFIG_CRUSH80_MANUAL_CONFIRM`, `zmk/src/mcuboot_confirm.c` |
| Watchdog while unconfirmed | a wedged image resets instead of hanging | `heartbeat_handler` in `mcuboot_confirm.c` |
| Fatal handler | a crash reboots instead of spinning | `k_sys_fatal_error_handler` |
| Serial recovery | a hung image: force MCUboot into recovery, load the golden image | `./crush80 recover`, `flash_mgmt` group 64 |
| Full flash backup | everything else, with an SWS probe | `./crush80 backup`, `backups/` |

## Trial boot

MCUboot swap mode is `SWAP_USING_MOVE`. `image test HASH` swaps the new image into slot 0 once and keeps the old one in slot 1. If the new image never calls `boot_write_img_confirmed()`, the next boot swaps back.
The old firmware confirmed itself 5 s after boot, which is the opposite of useful for an experimental build: a hang after 5 s, or a defect that only shows in use, was permanent. The image now
confirms nothing by itself. The host tool confirms after it has seen the new hash running and the user has tested the board. Builds that must work with no host set `CONFIG_CRUSH80_MANUAL_CONFIRM=n`
(the golden images in `releases/` are such builds).

While unconfirmed, a delayed work item feeds the 11 s hardware watchdog every 2 s from the system work queue. A wedged firmware therefore resets about 11 s later. Once confirmed the same work item disables the watchdog.

## What is assumed and not yet proven on this board

1. A cold boot (power cycle) of an unconfirmed trial image reverts to the previous image. Standard MCUboot behaviour; the project notes already say swaps need a cold boot. Test T2.
2. Whether a *watchdog* reset also reaches MCUboot. The B91 notes say a software reset does not swap. Test T5 records the answer. The design does not depend on it: the unplug always works.
3. `boot_is_img_confirmed()` is false for an image that `image test` swapped in. Test T2 step 4 shows it.

## Stock switching

- Stock to ZMK: `install_zmk.sh` uses the stock OTA protocol (`scripts/flash_ota.py`), which writes the second bank and only then switches, so a failure leaves stock intact.
- ZMK to stock: `flash_mgmt` writes the stock image to slot 1, the tool reads every byte back and compares the SHA-256, and only then `commit` (cmd 3) runs a RAM-resident trampoline that erases the sectors the new image needs,
  copies it to 0x0 and resets. Since 2026-11-19 it erases only those sectors before the copy (it used to erase everything below the staging area), and cleans the rest of 0x0-0x80000 afterward. The window with no bootable image
  is the erase of about 30 sectors plus the copy. It cannot be removed without a second boot bank for stock; it is minimised and gated behind a backup instead.

## Failure states the tool distinguishes

`update` ends in exactly one of: *confirmed* (done), *left unconfirmed* (user said no), *reverted* (old hash is running), *stopped before touching the board* (validation, golden, preflight), or *stopped with an instruction*
(no port, no answer). The message always says what state the board is in and the single next action.
