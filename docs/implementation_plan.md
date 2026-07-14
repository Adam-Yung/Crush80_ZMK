# Crush 80 ZMK Firmware — Implementation Plan

**Legend:**
- ✅ **DONE** — complete, committed, ready to use
- ⏳ **IN PROGRESS** — user is working on this now
- ⚠️ **BLOCKED** — needs specific information or hardware before it can proceed
- 📋 **TODO** — unblocked, can be done next

---

## Phase 1: Core Firmware (USB + BLE) — No Blockers

Everything needed to get USB HID and Bluetooth working is already written.
The only remaining step is getting the toolchain installed and running the build.

### ✅ Hardware confirmed

| Fact | Evidence |
|------|----------|
| MCU: TLSR9511 | USB descriptor string at `firmware/v2_patched.bin:0x1DB20` |
| LED: AW20216S (SPI) | `0xFD 0x00` page-select command found 3× in firmware |
| Matrix: 6×16 | `v2_update.md`: "Same 16x6 scan routine, same pin assignments" |
| GPIO assignments | Copied from Rainy 75 Pro; `v2_update.md` confirms "same pin assignments" |

### ✅ Board definition written

| File | Status |
|------|--------|
| `zmk/boards/crush80/crush80.dts` | Complete. GPIO = Rainy 75 (likely correct). |
| `zmk/boards/crush80/crush80.keymap` | Complete. QWERTY + Fn layer. |
| `zmk/boards/crush80/crush80_defconfig` | Complete. |
| `zmk/boards/crush80/Kconfig.*` | Complete. |
| `zmk/boards/crush80/board.yml` | Complete. |
| `conf/app.conf` | Complete. |
| `zmk/west.yml` | Complete. Pinned to validated ZMK revision. |
| `.github/workflows/build.yml` | Complete. Builds and uploads artifacts on push. |

### ⏳ Toolchain setup (user running now)

```bash
# In WSL Ubuntu 24.04 — run these sequentially:
sudo apt-get update && sudo apt-get install -y git cmake ninja-build python3-pip wget xz-utils libusb-1.0-0-dev file
pip3 install west pyelftools

# Zephyr SDK 0.17.0 (exact version required):
cd ~
wget https://github.com/zephyrproject-rtos/sdk-ng/releases/download/v0.17.0/zephyr-sdk-0.17.0_linux-x86_64.tar.xz
tar xf zephyr-sdk-0.17.0_linux-x86_64.tar.xz
cd zephyr-sdk-0.17.0 && ./setup.sh -t riscv64-zephyr-elf
```

### 📋 TODO: west init + build + flash

```bash
# In crush80 repo root:
cd zmk
west init -l .
west update              # 5-10 min
cd ..
bash fetch_ble_blob.sh
pip3 install -r zmk/zephyr/scripts/requirements.txt

# Build:
export ZEPHYR_SDK_INSTALL_DIR=~/zephyr-sdk-0.17.0
bash build.sh -a

# Flash Stage 1 (OTA bridge):
python3 scripts/flash_ota.py zmk/build-bridge/zephyr/zmk.bin

# Flash Stage 2 (ZMK app via mcumgr):
~/go/bin/mcumgr --conntype serial --connstring "dev=/dev/ttyACM0,baud=115200" \
    image upload zmk/build/zephyr/zmk.signed.bin
~/go/bin/mcumgr --conntype serial --connstring "dev=/dev/ttyACM0,baud=115200" \
    image confirm && reset
```

### 📋 TODO: Bring-up validation

After first boot, validate in this order:

1. **USB HID** — plug in, open notepad, press keys. Characters appear.
2. **Key matrix** — if any key produces wrong output:
   - Add `CONFIG_ZMK_KSCAN_LOG_LEVEL_DBG=y` to `conf/app.conf`
   - Read serial console: `screen /dev/ttyACM0 115200`
   - Press known key (ESC → should log `RC(0,0)`)
   - If row/col are wrong, swap the `col-gpios`/`row-gpios` entries in `crush80.dts`
3. **Bluetooth** — `Fn+F1` to enter BT pairing, pair from host, type text over BLE
4. **Battery** — BLE battery service should show a percentage

---

## Phase 2: Per-Key RGB

### ⚠️ BLOCKED: AW20216S SPI pin extraction

**What's needed:** The CS, CLK, and MOSI GPIO pins used by the AW20216S chip.
These are not in any public documentation and must be extracted from the stock firmware.

**How to unblock:** Follow `docs/ghidra_spi_extraction.md` — takes ~1-2 hours.

**What's already written (waiting on pins):**
- `zmk/drivers/led/aw20216s.c` — full SPI driver, page register protocol ✅
- `zmk/drivers/led/crush80_rgb.c` — RGB engine, SOLID + ECHO effects ✅
- `zmk/dts/bindings/led/wobkey,aw20216s.yaml` — DTS binding ✅

### 📋 TODO: After extracting pins

1. Find the 3 GPIO pins from Ghidra analysis of LED init at ~`0xEF88`
2. Add AW20216S SPI node to `crush80.dts` with actual pins:
   ```dts
   &spi_gspi {                              // actual SPI peripheral name TBD
       aw20216s0: aw20216s@0 {
           compatible = "wobkey,aw20216s";
           reg = <0>;
           cs-gpios = <&gpioc 0 GPIO_ACTIVE_LOW>; // ← fill in actual CS pin
           num-leds = <154>;
           global-current = <32>;
       };
   };
   ```
3. Rebuild and flash
4. At bring-up: drive LED 0 solid blue, press keys — verify echo effect fires
5. If LED ordering is wrong: update `crush80_led_sw[]`/`crush80_led_cs[]` tables in `aw20216s.c`

---

## Phase 3: 2.4 GHz Dongle

### ⚠️ BLOCKED: nRF24L01+ hardware + access code sniff

**What's needed:**
1. nRF24L01+ PA+LNA module (~$12, pack of 4 on Amazon)
2. One sniffing session with keyboard in 2.4G mode + Raspberry Pi 3B

**What's already written (waiting on access code):**
- `scripts/sniff_2g_access_code.py` — RPi + nRF24 sniffer script ✅
- `scripts/crush80_2g_config.py` — config generator (edit 2 lines, run, done) ✅
- `zmk/drivers/radio/crush80_2g_constants.h` — placeholder header (auto-generated) ✅
- RF physical layer: open-source Apache 2.0 in `tl_platform_sdk` ✅
- TPLL state machine: ~300 lines to write once access code known 📋

### 📋 TODO: After sniffing

1. Wire nRF24L01+ to RPi 3B (7 Dupont wires, see `docs/hardware_guide_2g_and_diy.md`)
2. `pip3 install pyrf24` on RPi
3. `python3 scripts/sniff_2g_access_code.py` — switch keyboard to 2.4G, press keys
4. Note the `ACCESS CODE` and `CHANNELS` printed
5. Edit `scripts/crush80_2g_config.py` (2 lines)
6. Run `python3 scripts/crush80_2g_config.py` to regenerate header
7. Write `zmk/drivers/radio/b91_tpll.c` TPLL state machine (~300 lines)
8. Rebuild and flash

---

## Recovery Procedures

### Standard update (MCUboot installed)

```bash
bash build.sh
~/go/bin/mcumgr --conntype serial --connstring "dev=/dev/ttyACM0,baud=115200" \
    image upload zmk/build/zephyr/zmk.signed.bin
~/go/bin/mcumgr ... image confirm && reset
```

### Revert to stock firmware

```bash
bash restore_stock.sh -y
# or manually:
python3 scripts/flash_ota.py firmware/code_2M_v2_patched.bin
```

### Auto-revert (MCUboot watchdog)

If the ZMK app crashes on boot, MCUboot's watchdog automatically reverts to the previous
image within ~30 seconds. No action needed — just wait.

### Hard recovery (Telink Burning Board via SWS)

Only needed if both the app and OTA bridge are wiped:
1. Open keyboard case (ball-catch, no tools)
2. Wire Burning Board to 3 SWS pads: GND, VCC, SWS
3. BDT tool → B91 → `firmware/code_2M_v2_patched.bin` → Flash

---

## Outstanding Items Summary

| Item | Blocker | Effort |
|------|---------|--------|
| ⏳ Toolchain installed | None (user running apt/pip) | 20 min |
| ⏳ `west update` + BLE blob | Toolchain done first | 10 min |
| 📋 First build + flash | Toolchain done | 15 min |
| 📋 GPIO matrix validation | First flash done | 30 min bring-up |
| ⚠️ AW20216S SPI pins | Ghidra + firmware analysis | 1-2 hours |
| ⚠️ 2.4G access code | nRF24L01+ hardware ($12) | 30 min once hardware arrives |
| 📋 TPLL driver (~300 LOC) | Access code known | 2-3 hours coding |
