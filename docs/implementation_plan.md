# Crush 80 ZMK Firmware — Implementation Plan

**Legend:**
- ✅ **DONE** — complete, committed, validated
- ⏳ **NEXT** — unblocked, can be done immediately
- ⚠️ **NEEDS HARDWARE** — blocked on physical action (flash/probe)
- 📋 **OPTIONAL** — nice to have, not required for working keyboard

---

## Phase 1: Core Firmware (USB + BLE) ✅ COMPLETE

Everything for USB HID + BLE is written and built.

| Item | Status |
|------|--------|
| MCU confirmed: TLSR9511 | ✅ USB descriptor string |
| Matrix GPIO: same as Rainy 75 | ✅ v2_update.md confirmed |
| Board DTS, keymap, Kconfig | ✅ All written |
| AW20216S SPI pins confirmed | ✅ PE0=CS0, PE1=CLK, PE2=MOSI, PC0=CS1, PC2=power |
| DTS with correct &hspi node | ✅ Pinctrl for PE1/PE2 FUNC_C |
| Successful ZMK build (417/417) | ✅ zmk.bin 280KB |
| AW20216S Zephyr driver | ✅ Written (2-chip, HSPI) |
| RGB engine (solid + echo) | ✅ Written |
| 2.4G sniffer script | ✅ Written |
| OTA flash path documented | ✅ README.md Part 3 |
| Stock restore documented | ✅ README.md Part 4 |

### ⏳ NEXT: Build + Flash

```bash
# In WSL, from /home/adyung/Projects/crush80/rainy75-zmk:

# 1. Install protobuf (enables ZMK Studio — do this once with sudo):
sudo apt-get install -y protobuf-compiler

# 2. Sync updated board files from Windows repo:
cp -r /mnt/c/Users/adyung/Documents/Adam/Wobkey_Crush_80_Patched_Firmware/zmk/boards/crush80/* \
      /home/adyung/Projects/crush80/rainy75-zmk/zmk/boards/crush80/

# 3. Rebuild (remove ZMK_STUDIO=n override now that protoc is installed):
/bin/bash /mnt/c/Users/adyung/Documents/Adam/Wobkey_Crush_80_Patched_Firmware/build_crush80.sh

# 4. Flash OTA bridge (Stage 1):
python3 /mnt/c/Users/adyung/Documents/Adam/Wobkey_Crush_80_Patched_Firmware/scripts/flash_ota.py \
    /home/adyung/Projects/crush80/rainy75-zmk/build-bridge/zephyr/zmk.bin

# 5. Flash ZMK app (Stage 2 — after bridge enumerates as /dev/ttyACM0):
~/go/bin/mcumgr --conntype serial --connstring "dev=/dev/ttyACM0,baud=115200" \
    image upload /home/adyung/Projects/crush80/rainy75-zmk/build-crush80/zephyr/zmk.signed.bin
~/go/bin/mcumgr ... image confirm && reset
```

### ⚠️ After first flash: Validate key matrix

Enable debug logging, press ESC (expect RC(0,0)), press A (expect RC(3,1)). If wrong, swap GPIO entries in `crush80.dts`. See README.md for full procedure.

---

## Phase 2: RGB (AW20216S) — Hardware confirmed, needs bring-up

### What's done ✅
- SPI pins confirmed from Ghidra: PE0/PE1/PE2/PC0/PC2
- DTS with correct `&hspi` node and pinctrl
- Full AW20216S Zephyr driver written (2-chip, HSPI)
- RGB engine with SOLID + ECHO effects
- DTS binding written

### ⏳ NEXT: Enable in build, then validate channel map

```bash
# In build_crush80.sh, remove these lines from the override:
# CONFIG_RAINY_RGB=n
# CONFIG_LED_STRIP_B91_SPI=n
# And add: CONFIG_AW20216S=y

# Then rebuild and flash.
```

**Channel map bring-up** (30 min with keyboard flashed):

The AW20216S has 216 channels (9 rows SW × 24 cols CS). Each LED needs 3 channels (R,G,B). The `crush80_led_sw[]` and `crush80_led_cs[]` tables in `aw20216s.c` are placeholders.

Procedure: add a test mode that lights LED 0, then 1, then 2... Record which physical key lights up for each index. The firmware's LED index table at offset `0x1C260` in `v2_patched.bin` gives the stock ordering as a reference.

---

## Phase 3: 2.4 GHz Dongle — Needs hardware

### ⚠️ Needs: nRF24L01+ PA+LNA modules (~$12, 4-pack on Amazon)

Once you have them:
1. Wire to RPi 3B (7 Dupont wires — see `docs/hardware_guide_2g_and_diy.md`)
2. `pip3 install pyrf24` on RPi
3. `python3 scripts/sniff_2g_access_code.py` — keyboard in 2.4G mode, press keys
4. Get `ACCESS_CODE` and `CHANNELS` output
5. Edit 2 lines in `scripts/crush80_2g_config.py`
6. Run `python3 scripts/crush80_2g_config.py` → regenerates header
7. Write TPLL driver (~300 lines C, template provided in plan)

### 📋 OPTIONAL: Also needs dongle-side firmware

The existing Wobkey dongle runs proprietary firmware. Re-flashing it requires SWS access (opening the dongle). An alternative: source a compatible Telink dongle dev board that can run open TPLL firmware.

---

## What's strictly necessary vs optional

### STRICTLY NECESSARY (for working keyboard)
1. `sudo apt install protobuf-compiler` — 1 command
2. Sync updated board files to WSL workspace
3. Rebuild firmware (removes stub overrides)
4. Flash OTA bridge + ZMK app via mcumgr
5. Validate matrix GPIO with debug log

### NEEDED FOR RGB
6. Enable `CONFIG_AW20216S=y` in build
7. Channel map validation at bring-up (30 min, no hardware needed beyond keyboard)

### OPTIONAL (nice, not required)
- 2.4G dongle: nRF24 hardware + sniff session
- ZMK Studio: just needs `sudo apt install protobuf-compiler`
- Home row mods: pure keymap change, no firmware rebuild needed

---

## Recovery cheatsheet

| Situation | Fix |
|-----------|-----|
| ZMK app crashes | MCUboot WDT reverts automatically in ~30s |
| Want stock back | `bash restore_stock.sh -y` |
| Manual stock restore | `python3 scripts/flash_ota.py firmware/code_2M_v2_patched.bin` |
| Total brick | Telink Burning Board + SWS pads (see `docs/ghidra_spi_extraction.md`) |
