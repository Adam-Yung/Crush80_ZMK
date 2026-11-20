# zmk/src/layer_rgb.c

Changes the backlight colour with the active layer and with held modifiers. Built only with the RGB build (`CONFIG_CRUSH80_LAYER_RGB`, default y when `CONFIG_CRUSH80_RGB` and the keymap has a `crush80,layer-rgb` node).

**How:** ZMK underglow has one colour (`state.color`). A listener on `zmk_layer_state_changed` and `zmk_keycode_state_changed` calls `zmk_rgb_underglow_set_hsb()`. Brightness is read back from the current state, so the brightness keys keep working. A held modifier (usage 0xE0-0xE7, so home-row mods and the bottom-row mods alike) wins over the layer colour; with several held the order is Gui, Alt, Ctrl, Shift.

**Colours** live in the keymap, node `layer_rgb`: `layer-hues` / `layer-sats` / `layer-on` by layer index (highest active layer wins; `layer-on = 0` blacks the backlight out on that layer, which cuts LED power; the user's brightness is remembered across that), `mod-hues` / `mod-sats` in the order Ctrl, Shift, Alt, Gui. Binding: `zmk/dts/bindings/misc/crush80,layer-rgb.yaml`.

**Needs the Solid effect.** Two seconds after boot the effect is forced to Solid, because ZMK restores the saved effect from settings after init. Cycling to another effect (Fn+\) shows that effect instead of the colours until the next boot.

Compiled in CI and run on the board for colours and modifier overrides (2026-11-20). The Base-layer-off option is new and not yet run on the board. Brightness keys pressed while the backlight is off on a layer light it at the new step until the next layer or modifier change.
