# Battery life in Bluetooth mode

**Status 2026-11-20:** audited by reading the code; one correctness fix and the RGB policy implemented; **nothing measured**. There is no current meter in the loop, so every number below that is not a code fact is an estimate.

## What the firmware already does
- ZMK idle at 60 s and deep sleep at 5 min (`conf/app.conf`); `ZMK_USB_NO_VBUS_DETECT` means USB never blocks sleep. Deep sleep is a cold boot through MCUboot.
- BLE connection interval 7.5-15 ms with latency 30 (ZMK defaults); TX power fixed in `b91_bt.c` (`rf_set_power_level_index`).
- Logging is off (`LOG=n`); the console stays on for MCUmgr.

## What costs the most
1. **The LED supply (PC2).** A dark WS2812 still draws a quiescent current (typically 0.5-1 mA each: roughly 80-150 mA for 154, **inferred, not measured**), likely more than the MCU and radio together. Only cutting the rail saves it, and the strip driver cuts PC2 whenever every pixel is black. This is why the engine is event driven and black whenever idle, on Base, or on Bluetooth.
2. **ZMK's underglow tick**: a 50 ms timer for as long as the backlight is "on", even when black (CPU wakes 20 times a second). Gone with the engine.
3. **The Telink BLE controller thread** polls every 2 ms (`b91_bt.c`). Real chip-level suspend between BLE events is the largest possible win but has no Zephyr support for this SoC and depends on the closed library: out of scope.

## Changes made
- RGB: off when idle; **off on Bluetooth** unless toggled (Fn+Backspace or Pause, temporary); USB keeps its saved choice. See `code/zmk/src/rgb/engine.c.md`.
- **Deep-sleep wake pins fixed** to this board's matrix (`code/zmk/src/poweroff.c.md`): a correctness fix first, though wrongly biased pins can also leak current.
- Brightness is capped (25 %), with a hard per-frame current budget.

## Candidates, not done (ranked, with the risk)
1. Deep sleep after 2 min instead of 5: saves little, costs a lost first key on wake. Left at 5 min until measured (owner's decision).
2. BLE controller poll 2 ms to 4 ms: possibly large, but the blob's timing needs are unknown; try only if the CPU-load measurement below shows a difference, and check typing latency.
3. TX power: small gain, leave.

## Measuring without a meter
- CPU load as a proxy: build with `conf/diag-power.conf` (thread runtime stats and `mcumgr taskstat`), read idle percentage over Bluetooth with the backlight off and on.
- Battery percentage from the host (`system_profiler SPBluetoothDataType`), logged hourly over days: coarse.
- A real answer needs the case open and a meter in series with the battery lead.
