# RGB on the Crush 80 Reboot Pro

**Status: the driver, build and basic controls are verified on the board (2026-11-20, Reboot Pro, 154 LEDs lit). Per-key colours (`code/zmk/src/rgb/engine.c.md`) are verified on the board too.**

## Hardware model the driver assumes

154 WS2812-compatible LEDs in one GRB chain: the first 92 under the keys, the other 62 in the logo and side bar. Data is the B91's PSPI MOSI on **PB7**; **PC2** switches the LED supply.
The PSPI clock is not routed to a pin (PB5, its clock pin, is a matrix column). The matrix pins keep their GPIO mode, which is the point: the earlier design shared PE0-PE2 between
matrix and LED SPI and needed interrupt-locked bit-banging, which is what hung the board (`incidents/2026-08-27-irq-lock-hang.md`).
Source of the pin map: the Reboot Pro PCB verification in the upstream port (RitwickVerma/Crush80_ZMK, its hardware notes, "LEDs" section), consistent with the Rainy 75 Pro the matrix pins were copied from.

## Which board is this

The older notes in `history/` concluded the LEDs were two AW20216S SPI controllers on PE0-PE2/PC0, from a Ghidra reading of the stock firmware. That reading never produced a lit LED in many attempts.
The WS2812 model fits that history (every attempt talked to chips that may not be there) but the two readings disagree, so confirm before trusting either:

1. The stock firmware's RGB is controlled over VIA (`reference/Crush80-RGB-USB.JSON`): this is an RGB board.
2. Look at the PCB, case open, nothing powered: per-key LEDs with no `AW20216S` IC anywhere = WS2812 chain. An `AW20216S`-marked IC = the old model, and this driver will not light it.
3. If it is not a Reboot Pro: stop. Do not flash `conf/rgb.conf`. This doc and the overlay need a second variant.

## Build and install

```bash
bash build.sh --skip-bridge --rgb                      # dist/crush80-zmk-app-rgb.signed.bin
./crush80 check dist/crush80-zmk-app-rgb.signed.bin
./crush80 update dist/crush80-zmk-app-rgb.signed.bin   # trial boot; confirm only after the checks in the test plan
```

`--rgb` adds `conf/rgb.conf` (`CONFIG_CRUSH80_RGB=y`, underglow on, brightness capped at 25 %) and `conf/rgb.overlay` (the `telink,b91-spi-led-strip` node and `zmk,underglow`). The plain build has no RGB code in it.
Keys with the supplied stock keymap: **Fn+Backspace** toggle, **Fn+Backslash** next effect (solid, breathing, spectrum, swirl), **Fn+Up / Fn+Down** brightness. Turning RGB off cuts LED power.

## Backlight scheme: per-key engine (2026-11-20, compiled, not yet run on the board)

With a `crush80,rgb-scheme` node in the keymap, `build.sh --rgb` builds the per-key engine (`code/zmk/src/rgb/engine.c.md`) instead of ZMK's single-colour underglow:
the **side bar and logo** show the layer colour (paler on Windows), **keys light by what they do** on the active layer (arrows, line jump, word jump, page, delete, clipboard, ...; keys that do nothing stay dark), **Base is dark on battery and shows a slow cyan-pink wave with a USB host (azure-orchid on Windows)**, and **a held home-row mod lights only its own key**.
It goes off when idle; the saved on/off applies on USB and Bluetooth alike. Hold Fn+Enter for the battery level on keys 1..0 (shown even with the backlight off). Keys: F5 / F6 dimmer / brighter, Pause or Fn+Backspace on/off, Fn+Up / Fn+Down brighter / dimmer. Effects (breathe, spectrum, swirl) are gone.
Colours, groups and overrides are edited in the keymap (private repo), drawn in its `Keymap.md`. Without the node, the build falls back to ZMK underglow (the earlier behaviour: one colour, effects).
The earlier one-colour-per-layer module (`layer_rgb.c`) was deleted once the engine was proven on the board (2026-11-20; `decisions/rgb.md`).

## How the driver works (`zmk/drivers/led_strip/led_strip_b91_spi.c`)

ZMK's underglow calls `led_strip_update_rgb()` with 154 pixels. The driver encodes each colour bit as one SPI byte at 6 MHz (`0xF0` = 1, `0xC0` = 0: highs of 0.67 µs and 0.33 µs, inside the WS2812B window),
fills a 3,696-byte buffer, and starts one PSPI transfer fed by **DMA channel 4**. The transfer-end interrupt (PLIC source 23, connected at run time) gives a semaphore the calling work queue waits on.
Interrupts stay enabled for the whole transfer. If the semaphore does not arrive within the expected 4.9 ms plus 2 ms, the driver stops the DMA, resets PSPI, cuts LED power and returns `-ETIMEDOUT`;
the next update retries. The only `irq_lock()` is around setting the power GPIO, one register write.

**Why this is acceptable to flash at all:** no unbounded wait anywhere; no long interrupt lock; a stuck LED transfer degrades to "LEDs off", not "board hung"; and the build boots as a trial,
so a defect that does hang the firmware is undone by a power cycle (`features/install-mechanism.md`).

## Open risks (what the first run must settle)

- **Build:** not compiled here. Likely trouble spots: `irq_connect_dynamic` with the multilevel IRQ number `IRQ_TO_L2(23) | 11` on the B91 PLIC, `select DYNAMIC_INTERRUPTS`, the overlay include path.
- **DMA channel 4 and PSPI IRQ 23** are assumed free. The Telink BLE blob and the USB driver are not fully source-visible; a clash would show as BLE or USB misbehaving only with RGB on (test plan T6, Bluetooth and 5-minute checks).
- **Current draw** of 154 LEDs: brightness is capped at 25 % for the first run. Raise it only after a battery test.
- **Sleep:** LEDs must be off in deep sleep. The driver cuts PC2 when every pixel is black; test T6 covers idle-to-sleep.
- LEDs dark with a healthy keyboard: record the model, PCB revision, whether stock firmware lit them, and whether USB typing and `./crush80 status` work, then stop. Do not guess pins on the board.

## History

`history/rgb-debug-history.md`, `history/rgb-led-full-investigation.md`, `history/rgb-led-plan.md` and `history/ghidra_spi_extraction.md` record the AW20216S attempts. Kept so the same dead ends are not walked again.
Decision record: `decisions/rgb.md`.


## Modifier display

While Ctrl, Shift, Alt or Cmd is held, the whole backlight goes dark except the top row (Esc, F1-F12, PrtSc, ScrLk, Pause), which shows one colour per combination of the four modifiers (15 colours, set in the keymap's `crush80,rgb-scheme` node as `mod-combo-colors`; the keys that form the bar are `mod-bar`). Any held modifier counts, including a physical Shift while typing capitals. Added 2026-11-20.
