# Install and upgrade safety

## 2026-11-19: new images boot as a trial and the host confirms

The old image confirmed itself 5 s after boot (`mcuboot_confirm.c`). A defect that showed after 5 s, or a hang, was permanent: the 2026-08-27 failure. Chosen: `CONFIG_CRUSH80_MANUAL_CONFIRM=y` by default; the image
feeds the watchdog but never confirms, and `./crush80 update` confirms after it has seen the new hash running and the user has tested the board. Rejected: a longer auto-confirm delay (still permanent after the delay),
and a health-check inside the firmware (the checks that matter, such as "do the LEDs light", are not observable by the firmware). Cost: an unconfirmed trial reverts at the next cold boot, including a deep-sleep wake.
Releases that must run with no host set the option to `n`.

## 2026-11-19: the revert is the power cycle, not the watchdog

The B91 notes say a software reset does not swap images. A watchdog reset may or may not reach MCUboot. The design therefore relies only on the unplug and replug, which is a cold boot, and treats the watchdog as a bonus.
Hardware test T5 records what the watchdog does.

## 2026-11-19: no firmware flash without a hash-verified known-good image on disk

`releases/MANIFEST.sha256` lists the images known to have run. `update`, `recover` and `install_zmk.sh` verify it first and refuse otherwise. Rejected: trusting `dist/` (it holds whatever was built last).

## 2026-11-19: stock restore erases only what the stock image occupies before the copy

The `flash_mgmt` commit trampoline used to erase everything below the staging area, then copy. With stock at about 120 KB that was a 448 KB erase window with no bootable image. It now erases only the sectors the new
image needs, copies, then cleans the remainder. Not hardware-tested (test T7). The window cannot reach zero: stock and MCUboot both boot from 0x0.

## 2026-11-19: legacy recovery scripts kept until the replacement is proven

`force_recovery.py`, `recovery_flash.py`, `emergency_upload.py` and `flash_mgmt_upload.py` moved to `scripts/legacy/`; `force_recovery.py` plus `mcumgr image upload` is the only recovery that has saved the board. They are deleted
after hardware test T4 shows `./crush80 recover` does the same. The pip auto-install lines in them were removed: agents and scripts do not install packages.
