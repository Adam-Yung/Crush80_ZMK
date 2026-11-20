# RGB

## 2026-11-19: adopt the WS2812 / PSPI driver, drop the AW20216S code

The patch `crush80-rgb.patch` (from the upstream Reboot Pro work) replaces the AW20216S bit-bang driver with a PSPI + DMA WS2812 driver on PB7 and removes `zmk/drivers/led`, `zmk/src/crush80_rgb.*` and the AW20216S binding.
Reviewed and accepted because: it does not share pins with the matrix; it has no unbounded wait and no long interrupt lock; a timeout degrades to LEDs off. It also repairs `patches/zmk-src/0005`, which had been
generated wrongly (a copy of 0002 under 0005's name) and is now the one-line return-type fix its name describes.
Not verified: compilation in this tree and every hardware property (`docs/features/rgb.md`, "Open risks"). The old AW20216S investigation stays in `docs/history/`.

## 2026-11-19: the RGB build is opt-in (`build.sh --rgb`)

The default build has no RGB code, so the daily-use firmware is not exposed to an unproven driver. Promote RGB into the default only after hardware test T6 passes and it has run for a few days.

## 2026-11-19: the board model is a precondition, not an assumption

The patch's pin map is verified for a Reboot Pro, not necessarily for this board; the older Ghidra reading says AW20216S. `docs/features/rgb.md` says how to tell (PCB inspection) before flashing.

## 2026-11-20
**Brightness cap stays at 25 %** (`conf/rgb.conf`, `ZMK_RGB_UNDERGLOW_BRT_MAX`). Measured on the board: all 154 LEDs light, dimmer than stock. 154 WS2812 draw far more than a USB port gives at full brightness, and the owner prefers the battery life. Raise only with a current measurement.
**Backlight colour follows layer and held modifier** through one small listener (the since-deleted `layer_rgb.c`, replaced by the per-key engine) instead of porting upstream's per-key engine: ZMK underglow has a single colour, which is all the owner asked for. Base layer backlight is off (LED power cut), every other layer has a colour. The per-key engine in Ritwick Verma's fork remains an option if per-key effects are wanted.

## 2026-11-20 (evening): Bluetooth follows the USB on/off; ambient Base on USB; battery gauge
**Bluetooth uses the saved on/off** like USB. The owner found "off unless toggled" too limiting. The cost stays small because Base is dark on battery and the other layers are momentary holds, so the rail is cut most of the time; idle still turns everything off.
**Base animates only with a USB host** (layer mode 3, `zmk_usb_is_hid_ready()`), cyan-pink on macOS, azure-orchid in the other direction on Windows. The animation is the engine's only tick, and it runs only while the frame it draws is ambient. The board has no VBUS pin, so "host configured" stands in for "cable in".
**Battery gauge on Fn+Enter (hold)**: number row 1..0, one key per 10 %, shown whatever the on/off and output, because a gauge that hides when the backlight is off is useless on battery.

## 2026-11-20 (later): Base and Native fully dark on battery
On battery a top layer of mode 0 or 3 shows nothing at all, held-mod lights included, so ordinary typing never powers the LED rail. Owner's request.
