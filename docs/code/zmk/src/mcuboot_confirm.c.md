# zmk/src/mcuboot_confirm.c

Decides when the running image becomes permanent, and keeps a watchdog behind it until then.

**Why two modes.** `CONFIG_CRUSH80_MANUAL_CONFIRM=y` (default): the file never confirms. A 2 s heartbeat on the system work queue feeds the 11 s hardware watchdog while `boot_is_img_confirmed()` is false,
and disables the watchdog once the host has confirmed (`mcumgr image confirm`). A wedged firmware stops feeding it and resets. `=n`: the old behaviour, confirm 5 s after boot, for builds that must work with no host (the golden images).

**Why the watchdog starts at POST_KERNEL priority 1.** It must cover every driver init after it; a hang in an RGB or USB init would otherwise never be seen.

**Why `k_sys_fatal_error_handler` reboots.** Zephyr's default spins forever with interrupts masked, which is a hang no revert logic sees. A cold reboot at least gives MCUboot a chance.

**Not relied on.** Whether a watchdog or software reset makes MCUboot revert on this chip is unproven (`docs/features/install-mechanism.md`, "What is assumed"). The guaranteed revert is the unplug.
