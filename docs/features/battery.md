# Battery life in Bluetooth mode

**Status 2026-11-20:** audited by reading the code; one correctness fix and the RGB policy implemented; **nothing measured**. There is no current meter in the loop, so every number below that is not a code fact is an estimate.

## What the firmware already does
- ZMK idle at 60 s and deep sleep at 5 min (`conf/app.conf`); `ZMK_USB_NO_VBUS_DETECT` means USB never blocks sleep. Deep sleep is a cold boot through MCUboot.
- BLE connection interval 7.5-15 ms with latency 30 (ZMK defaults); TX power fixed in `b91_bt.c` (`rf_set_power_level_index`).
- Logging is off (`LOG=n`); the console stays on for MCUmgr.

## What costs the most
1. **The LED supply (PC2).** A dark WS2812 still draws a quiescent current (typically 0.5-1 mA each: roughly 80-150 mA for 154, **inferred, not measured**), likely more than the MCU and radio together. Only cutting the rail saves it, and the strip driver cuts PC2 whenever every pixel is black. This is why the engine is event driven and black whenever idle or on Base without a USB host; on battery Base and Native are fully dark (held-mod lights included) and the LEDs are lit only while another layer (or the battery gauge) is held.
2. **ZMK's underglow tick**: a 50 ms timer for as long as the backlight is "on", even when black (CPU wakes 20 times a second). Gone with the engine.
3. **The Telink BLE controller thread** polls every 2 ms (`b91_bt.c`). Real chip-level suspend between BLE events is the largest possible win but has no Zephyr support for this SoC and depends on the closed library: out of scope.

## Changes made
- RGB: off when idle. Since 2026-11-20 evening Bluetooth follows the same saved on/off as USB (it was off unless toggled). Base is dark on battery and animates only with a USB host. Fn+Enter (hold) shows the charge on the number row. See `code/zmk/src/rgb/engine.c.md`.
- **Deep-sleep wake pins fixed** to this board's matrix (`code/zmk/src/poweroff.c.md`): a correctness fix first, though wrongly biased pins can also leak current.
- Brightness is capped (25 %), with a hard per-frame current budget.

## Candidates, not done (ranked, with the risk)
1. Deep sleep after 2 min instead of 5: saves little, costs a lost first key on wake. Left at 5 min until measured (owner's decision).
2. BLE controller poll 2 ms to 4 ms: **rejected for now (2026-11-20)**. The poll is in the key path: `hci_b91_send` only queues the report for the blob, and `blc_sdk_main_loop()` in the controller thread moves it to the link layer, so the poll adds 0-2 ms today and would add 0-4 ms, and a report that misses a connection event waits one more interval (7.5-15 ms). Revisit only if a CPU-load measurement shows the poll costs real battery.
3. TX power: small gain, leave.
4. **Done 2026-11-20:** deep sleep no longer fires while a USB host is active (`patches/zmk-src/0006`): with `ZMK_USB_NO_VBUS_DETECT`, `is_usb_power_present()` is "configured and not suspended" instead of always false. A pulled cable or a sleeping host suspends the bus, so the board still sleeps then. Not run on the board.
5. Battery percentage is a linear map of the voltage (`battery_b91_adc.c`) and the ADC channel is "likely correct", not confirmed. Compare the Fn+Enter gauge with the host's percentage before trusting either.

## Measuring without a meter
- CPU load as a proxy: build with `conf/diag-power.conf` (thread runtime stats and `mcumgr taskstat`), read idle percentage over Bluetooth with the backlight off and on.
- Battery percentage from the host (`system_profiler SPBluetoothDataType`), logged hourly over days: coarse.
- A real answer needs the case open and a meter in series with the battery lead.
