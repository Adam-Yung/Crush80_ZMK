/*
 * Per-layer and per-modifier backlight colour.
 *
 * ZMK's underglow has one colour. This listener changes that colour to follow the highest
 * active layer, and while any modifier key is held (home-row mods included) to the colour of
 * that modifier. Brightness is left to the normal RGB keys. Colours come from the
 * "crush80,layer-rgb" node in the keymap. Only the Solid effect shows them; the effect is
 * forced to Solid shortly after boot.
 */

#define DT_DRV_COMPAT crush80_layer_rgb

#include <zephyr/kernel.h>
#include <zephyr/devicetree.h>
#include <zephyr/logging/log.h>

#include <zmk/event_manager.h>
#include <zmk/events/keycode_state_changed.h>
#include <zmk/events/layer_state_changed.h>
#include <zmk/keymap.h>
#include <zmk/rgb_underglow.h>

LOG_MODULE_REGISTER(layer_rgb, LOG_LEVEL_INF);

BUILD_ASSERT(DT_NUM_INST_STATUS_OKAY(DT_DRV_COMPAT) == 1, "need exactly one crush80,layer-rgb node");

static const uint16_t layer_hue[] = DT_INST_PROP(0, layer_hues);
static const uint16_t layer_sat[] = DT_INST_PROP(0, layer_sats);
static const uint16_t mod_hue[] = DT_INST_PROP(0, mod_hues);
static const uint16_t mod_sat[] = DT_INST_PROP(0, mod_sats);

BUILD_ASSERT(ARRAY_SIZE(layer_hue) == ARRAY_SIZE(layer_sat), "layer-hues/layer-sats length differ");
BUILD_ASSERT(ARRAY_SIZE(mod_hue) == 4 && ARRAY_SIZE(mod_sat) == 4, "mod-hues/mod-sats need 4 entries");

#define USAGE_PAGE_KEYBOARD 0x07
#define USAGE_LCTRL         0xE0
#define USAGE_RGUI          0xE7

/* Bit n = modifier usage 0xE0 + n is held. Usage order: Ctrl, Shift, Alt, Gui, then the right-hand four. */
static uint8_t mods_held;

/* Which class wins when several modifiers are held: Gui, Alt, Ctrl, Shift. Indexes are class numbers. */
static const uint8_t class_priority[] = {3, 2, 0, 1};

static void apply(void) {
    struct zmk_led_hsb color = zmk_rgb_underglow_calc_brt(0); /* current colour; keeps brightness */

    int cls = -1;
    for (size_t i = 0; i < ARRAY_SIZE(class_priority); i++) {
        uint8_t c = class_priority[i];
        if (mods_held & (BIT(c) | BIT(c + 4))) {
            cls = c;
            break;
        }
    }

    if (cls >= 0) {
        color.h = mod_hue[cls];
        color.s = mod_sat[cls];
    } else {
        uint8_t layer = zmk_keymap_highest_layer_active();
        if (layer >= ARRAY_SIZE(layer_hue)) {
            return;
        }
        color.h = layer_hue[layer];
        color.s = layer_sat[layer];
    }

    int rc = zmk_rgb_underglow_set_hsb(color);
    if (rc) {
        LOG_WRN("set_hsb failed: %d", rc);
    }
}

static int layer_rgb_listener(const zmk_event_t *eh) {
    const struct zmk_keycode_state_changed *kc = as_zmk_keycode_state_changed(eh);
    if (kc) {
        if (kc->usage_page == USAGE_PAGE_KEYBOARD && kc->keycode >= USAGE_LCTRL &&
            kc->keycode <= USAGE_RGUI) {
            uint8_t bit = BIT(kc->keycode - USAGE_LCTRL);
            if (kc->state) {
                mods_held |= bit;
            } else {
                mods_held &= ~bit;
            }
            apply();
        }
        return ZMK_EV_EVENT_BUBBLE;
    }

    apply(); /* layer change */
    return ZMK_EV_EVENT_BUBBLE;
}

ZMK_LISTENER(layer_rgb, layer_rgb_listener);
ZMK_SUBSCRIPTION(layer_rgb, zmk_layer_state_changed);
ZMK_SUBSCRIPTION(layer_rgb, zmk_keycode_state_changed);

/* ZMK restores its saved effect and colour from settings after init, so set ours a moment later. */
static void boot_work_handler(struct k_work *work) {
    zmk_rgb_underglow_select_effect(0); /* Solid */
    apply();
}
static K_WORK_DELAYABLE_DEFINE(boot_work, boot_work_handler);

static int layer_rgb_init(void) {
    k_work_schedule(&boot_work, K_SECONDS(2));
    return 0;
}
SYS_INIT(layer_rgb_init, APPLICATION, 99);
