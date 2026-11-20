# zmk/src/flash_mgmt.c

Custom MCUmgr group 64: raw flash erase, write, read, commit, plus a USB diagnostic ring. It exists so a board can be recovered over USB with no probe. Protected region 0xFE000 and up is refused for every command.

**The commit trampoline** runs from RAM because it erases the flash the firmware executes from: interrupts off, BTB off, watchdog off, then erase, copy, reset. It is the only code path that rewrites the bootloader.
Phase 1 erases only `round_up(fw_len, 4 KB)` sectors, so the time with no bootable image is the erase of what the new image needs plus the copy (stock: about 30 sectors). Phase 3, after the copy, cleans the remainder
of 0x0-0x80000 (old image remnants and any stale TLNK at 0x40000 that would make the boot ROM pick the wrong bank). Before 2026-11-19 phase 1 erased everything below the staging area. Hardware-untested since the change (test T7).

**Why the staging area must be at or above `erase_end`:** the commit handler rejects overlap, otherwise phase 1 would erase its own source.

Host side: `scripts/crush80/smp.py` and `flows.stock_restore`. The slot 0 header erase used by `recover` is cmd 0 on 0x10000.
