# 2026-08-27: RGB driver hung the board; rescued by hand

**What happened.** An experimental AW20216S driver held `irq_lock()` while busy-waiting on an HSPI status bit that never cleared. Every interrupt was masked, so USB, BLE and the key matrix died about two seconds after boot.
The board still enumerated for those two seconds, `mcumgr image upload` needs hundreds of round trips and could not finish, and the revert path did not save it. The board was recovered with hand-written Python scripts (`force_recovery.py`, below) that
sent one raw SMP command inside the window.

**Why it was possible.**
- The hang came about 2 s after boot, before the 5 s self-confirm, so the 11 s watchdog and MCUboot's revert should have undone it. They did not. The cause is not established; the working
  theory is that a watchdog reset does not reach MCUboot's revert logic on this chip (the notes say a software reset does not swap). The revert design now relies on a power cycle instead.
- The image confirmed itself 5 s after boot, so any defect that appeared later was permanent.
- Nothing required a known-good image to be on disk and verified before flashing.
- Recovery depended on a two-second window and ad-hoc scripts, each with its own copy of the protocol code.
- No rule forbade unbounded waits under `irq_lock()`.

**What changed.**
- Trial boot with host confirmation (`docs/features/install-mechanism.md`), `./crush80` for every flash, `releases/MANIFEST.sha256`, full flash backups, a scripted `recover`, tests for the safety invariants.
- AGENTS.md hardware safety rules 2 to 5 and 8.
- The RGB design no longer shares pins with the matrix (`docs/features/rgb.md`).

**The recovery that worked on the hung firmware.** `force_recovery.py` sent one `flash_mgmt` erase of the slot 0 header inside the 2 s window; MCUboot (`BOOT_SERIAL_NO_APPLICATION=y`) then waited in serial recovery with no app running;
the known-good image uploaded normally. `./crush80 recover` is that sequence, scripted.
