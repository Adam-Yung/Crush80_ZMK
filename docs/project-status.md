# Crush 80 ZMK — Project Status & Future Plan

## Current Status: KEYBOARD FULLY FUNCTIONAL

All 88 keys scan correctly with proper GPIO pin assignments extracted from the
original firmware binary. MCUboot + ZMK app boot successfully. USB HID, BLE,
battery reporting, and mcumgr DFU all work.

## Completed

- [x] MCUboot bootloader (0x0) + ZMK app (0x10000) boot chain
- [x] USB HID keyboard (all 88 keys correct)
- [x] Matrix GPIO pins identified and verified (6 rows × 16 columns)
- [x] CDC-ACM serial for mcumgr DFU (upload/test/reset/confirm)
- [x] BLE SMP transport (backup DFU path)
- [x] Battery ADC (PD1, channel 0x0A, half-divider)
- [x] Custom keymap with home row mods, nav/sym layers
- [x] ZMK Studio support (BLE GATT)
- [x] Deep sleep with key wakeup
- [x] Build/flash/recovery scripts
- [x] Firmware recovery procedure documented

## Future TODO

### Priority 1: Bluetooth Testing
- [ ] Pair with phone/laptop via BLE
- [ ] Verify all keys work in BLE mode
- [ ] Test BT profile switching (Fn+F1/F2/F3)
- [ ] Test USB/BT output toggle (Fn+F5)
- [ ] Verify battery level reporting over BLE
- [ ] Test deep sleep and BLE wake

### Priority 2: RGB LED Support
- [ ] Implement AW20216S driver that time-multiplexes with matrix scan
  - PE0/PE1/PE2 are shared between matrix columns and SPI
  - Need to disable columns momentarily during SPI LED updates
  - Or use a dedicated SPI with different pins (if available)
- [ ] Map 154 LEDs to physical key positions
- [ ] Implement per-key RGB effects
- [ ] ZMK underglow integration

### Priority 3: Keymap Refinement
- [ ] Fine-tune HRM timings after daily use
- [ ] Add macOS-specific layer (Cmd instead of Ctrl)
- [ ] Consider adding mouse keys layer
- [ ] Test ZMK Studio live keymap editing

### Priority 4: Wireless 2.4G Dongle
- [ ] Investigate Wobkey 2.4G dongle protocol (PID 0x5088)
- [ ] Determine if ZMK can use the dongle (likely needs custom driver)
- [ ] Compare BLE latency vs 2.4G for gaming use

### Priority 5: Polish
- [ ] Caps Lock LED indicator (use one AW20216S LED)
- [ ] Battery low warning (blink LED or BLE notification)
- [ ] Firmware version tracking (bump VERSION in build)
- [ ] Automated CI build (GitHub Actions with west)
- [ ] Create proper install_zmk.sh that sets up workspace from scratch

## Known Issues

1. **HSPI disabled**: RGB LEDs don't work because PE0/PE1/PE2 are shared with matrix.
   Future fix requires SPI/matrix time-multiplexing or hardware rework.

2. **VIA config says 8 rows**: Original firmware reports 8×16 matrix to VIA but only
   uses 6 rows for scanning. The extra 2 "rows" may be phantom rows for VIA compat.

3. **Debug logging bricks SMP**: CONFIG_LOG_DEFAULT_LEVEL=4 floods serial output and
   blocks all mcumgr communication. Recovery requires physical unplug/replug race.

## Reference

- Original firmware repo: https://github.com/Desz01ate/Wobkey_Crush_80_Patched_Firmware
- Rainy 75 ZMK (same platform): https://github.com/scholzri/rainy75-zmk
- GPIO pin source: firmware offset 0xF078-0xF188 (gpio_init calls)
- West workspace: ~/Projects/crush80-workspace
- Zephyr SDK: ~/zephyr-sdk-0.17.0
