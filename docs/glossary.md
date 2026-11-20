# Glossary

| Term | Meaning |
|---|---|
| **B91** | Telink TLSR951x RISC-V MCU in the keyboard. |
| **MCUboot** | The bootloader at 0x0. Swaps images, serves USB serial recovery. Never rewritten by `update`. |
| **Slot 0 / slot 1** | Running image area (0x10000) / upload and revert area (0x80000). |
| **SMP / MCUmgr** | The management protocol over USB serial (and BLE). `mcumgr` is its CLI; `scripts/crush80/smp.py` speaks it for the custom group. |
| **flash_mgmt** | Custom MCUmgr group 64 in the firmware: raw flash erase, write, read, commit. Refuses 0xFE000 and up. |
| **Trial boot** | An image swapped in with `image test`: runs once, reverts at the next cold boot unless confirmed. |
| **Confirm** | `image confirm`: makes the running trial image permanent. By the host tool in normal builds. |
| **Revert** | MCUboot swapping the previous image back after an unconfirmed trial. Needs a power cycle. |
| **Cold boot** | A physical unplug and replug. A software reset does not swap images on this board. |
| **Golden image** | A known-good signed image in `releases/`, listed with its hash in `MANIFEST.sha256`. What `recover` loads. |
| **Serial recovery** | MCUboot waiting for an upload over USB when slot 0 has no valid image. No app runs. |
| **SWS** | Telink's single-wire debug interface. Last-resort access with a probe; needs `backups/`. |
| **Bridge** | The monolithic image used to go from stock firmware to ZMK over the stock OTA protocol. |
| **OTA (stock)** | The stock firmware's USB HID update protocol (usage page 0xFFEF), driven by `scripts/flash_ota.py`. |
| **KNLT / TLNK** | Telink boot marker in a firmware image header (`KNLT` as bytes at offset 0x20). |
| **PSPI** | The B91's peripheral SPI, used as a WS2812 pulse generator on PB7. |
| **Reboot Pro** | The RGB variant of the Crush 80 the RGB driver targets. |
