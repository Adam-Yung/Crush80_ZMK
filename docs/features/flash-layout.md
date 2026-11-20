# Flash layout

| Range | What | Notes |
|---|---|---|
| 0x00000-0x0FFFF | MCUboot | 64 KB. Never rewritten by `update`. Serial recovery over USB CDC. |
| 0x10000-0x7FFFF | Slot 0, the running app | 448 KB (`0x70000`), swap trailer at the end. |
| 0x80000-0xEFFFF | Slot 1, upload and revert copy | Also the staging area for `stock-restore`. |
| 0xF0000-0xFDFFF | storage (NVS) | BLE bonds, ZMK settings. |
| 0xFE000-0xFFFFF | RF calibration, BLE MAC | `flash_mgmt` refuses any access here. Not in `backups/`. |

Stock firmware boots from 0x0 as a monolithic image (marker `KNLT` at offset 0x20). The OTA bridge used for the first install is monolithic too, because the B91 boot ROM boots the second bank at 0x40000 after an OTA,
and MCUboot cannot run from there.

`mcuimg.SLOT_SIZE` and the numbers above come from `conf/mcuboot.conf` (`BOOT_MAX_IMG_SECTORS=112` of 4 KB) and `zmk/boards/crush80/crush80.dts` partitions. Change all together.
