/* SPDX-License-Identifier: Apache-2.0 */
/*
 * Per-key backlight engine for the Crush 80 (154 WS2812: 92 under the keys, 62 side bar and logo).
 *
 * Event driven: a frame is built when the layer, held modifiers, pressed keys, activity, USB state or
 * battery level changes, and only sent when it differs from the last one. The only periodic tick is the
 * ambient animation, which runs only while it is visible (USB host connected). Every LED black means
 * the strip driver cuts the LED supply (PC2), which is where the battery saving is.
 *
 *   - Side bar and logo: the colour of the highest active layer.
 *   - Keys: coloured by what the key does on the active layers (group colours, optional per-key
 *     overrides); keys bound to nothing stay dark. A layer can also be set to "dark", or to "ambient":
 *     a slow two-colour wave over the whole board while a USB host is connected. On battery, layers
 *     that do not light their keys (Base, Native) are fully dark.
 *   - A held home-row mod (or modifier key) lights only its own key, in the modifier's colour.
 *   - Battery gauge (&c80rgb_bat held): number row 1..0 shows the charge, whatever the other state.
 *   - Idle or toggled off: everything off. USB and Bluetooth share the saved on/off and brightness.
 *
 * The LED order comes from led_map_data.h (see NOTICE). Colours and layers come from the
 * crush80,rgb-scheme node in the keymap. Needs CONFIG_ZMK_RGB_UNDERGLOW=n (one owner of the strip).
 */
#define DT_DRV_COMPAT crush80_rgb_scheme

#include <string.h>

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/led_strip.h>
#include <zephyr/logging/log.h>
#include <zephyr/settings/settings.h>
#include <zephyr/sys/atomic.h>

#include <zmk/activity.h>
#include <zmk/battery.h>
#include <zmk/behavior.h>
#include <zmk/event_manager.h>
#include <zmk/events/activity_state_changed.h>
#include <zmk/events/battery_state_changed.h>
#include <zmk/events/layer_state_changed.h>
#include <zmk/events/keycode_state_changed.h>
#include <zmk/events/position_state_changed.h>
#include <zmk/events/usb_conn_state_changed.h>
#include <zmk/hid.h>
#include <zmk/keymap.h>
#include <zmk/keys.h>
#include <zmk/matrix.h>
#if IS_ENABLED(CONFIG_ZMK_USB)
#include <zmk/usb.h>
#endif

#include <dt-bindings/zmk/modifiers.h>

#include "effects.h"
#include "engine.h"
#include "led_map_data.h"

LOG_MODULE_REGISTER(c80rgb, LOG_LEVEL_INF);

BUILD_ASSERT(DT_NUM_INST_STATUS_OKAY(DT_DRV_COMPAT) == 1, "need exactly one crush80,rgb-scheme node");

#define NLAYERS ZMK_KEYMAP_LAYERS_LEN
#define TRANSFORM_NODE DT_NODELABEL(default_transform) /* the board has physical layouts, so ZMK gives no node macro */
#define NPOS DT_PROP_LEN(TRANSFORM_NODE, map)

enum group {
    G_ARROW, G_LINE, G_WORD, G_PAGE, G_DELETE, G_CLIP, G_NUMBER, G_SYMBOL, G_LETTER, G_MACRO,
    G_LAYER, G_MOD, G_CTRL, G_FKEY, G_MEDIA, G_DESKTOP, G_SYSTEM, G_DANGER, G_COUNT
};

static const uint32_t layer_mode[] = DT_INST_PROP(0, layer_modes);
static const uint32_t layer_side[] = DT_INST_PROP(0, layer_side);
static const uint32_t layer_side_win[] = DT_INST_PROP(0, layer_side_win);
static const uint32_t group_color[] = DT_INST_PROP(0, group_colors);
static const uint32_t mod_color[] = DT_INST_PROP(0, mod_colors);
static const uint32_t overrides[] = DT_INST_PROP(0, overrides);
#if DT_INST_NODE_HAS_PROP(0, ambient_colors)
static const uint32_t ambient_mac[] = DT_INST_PROP(0, ambient_colors);
#else
static const uint32_t ambient_mac[] = {0x00D8FF, 0xFF2A8C};
#endif
#if DT_INST_NODE_HAS_PROP(0, ambient_colors_win)
static const uint32_t ambient_win[] = DT_INST_PROP(0, ambient_colors_win);
#else
static const uint32_t ambient_win[] = {0x2080FF, 0xE040FF};
#endif
#define POS_RC_ENTRY(i, _) DT_PROP_BY_IDX(TRANSFORM_NODE, map, i)
static const uint32_t pos_rc[] = {LISTIFY(NPOS, POS_RC_ENTRY, (, ))};

BUILD_ASSERT(ARRAY_SIZE(layer_mode) == NLAYERS, "layer-modes needs one entry per layer");
BUILD_ASSERT(ARRAY_SIZE(layer_side) == NLAYERS, "layer-side needs one entry per layer");
BUILD_ASSERT(ARRAY_SIZE(layer_side_win) == NLAYERS, "layer-side-win needs one entry per layer");
BUILD_ASSERT(ARRAY_SIZE(group_color) == G_COUNT, "group-colors needs 18 entries");
BUILD_ASSERT(ARRAY_SIZE(mod_color) == 4, "mod-colors needs 4 entries");
BUILD_ASSERT(ARRAY_SIZE(overrides) % 3 == 0, "overrides are triples");
BUILD_ASSERT(ARRAY_SIZE(ambient_mac) == 2 && ARRAY_SIZE(ambient_win) == 2, "ambient colours are pairs");
BUILD_ASSERT(NPOS == ZMK_KEYMAP_LEN, "matrix transform length");

#define WIN_LAYER DT_PROP(DT_COMPAT_GET_ANY_STATUS_OKAY(crush80_os_config), win_layer)

#define MODE_DARK 0
#define MODE_KEYS 1
#define MODE_MARKER 2
#define MODE_AMBIENT 3

#define BRT_LEVELS 10
#define AMBIENT_FRAME_MS 40
#define GAUGE_MAX_S 10 /* a lost release must not keep the gauge lit on battery */
#define STRIP_NODE DT_CHOSEN(zmk_underglow)

static const struct device *strip = DEVICE_DT_GET(STRIP_NODE);

static uint8_t pos_led[NPOS];
static uint8_t pos_extra[NPOS][2];
static uint8_t led_x[C80_TOTAL_LEDS], led_y[C80_TOTAL_LEDS]; /* 0..255, for the ambient wave */
static bool led_used[C80_TOTAL_LEDS];                         /* false for key LEDs with no key */
static uint8_t gauge_pos[C80_GAUGE_KEYS];                     /* positions of keys 1..0 */

static struct {
    uint8_t enabled; /* backlight on */
    uint8_t level;   /* 1..BRT_LEVELS, of CONFIG_CRUSH80_RGB_BRT_MAX percent */
} st = {1, BRT_LEVELS};

static bool idle;
static volatile bool gauge; /* battery gauge key held; set by the behaviour, read by the work queue */
static ATOMIC_DEFINE(pressed, NPOS);

static struct led_rgb px[C80_TOTAL_LEDS];
static struct led_rgb last[C80_TOTAL_LEDS];
static bool last_valid;
static int fails;

static K_THREAD_STACK_DEFINE(wq_stack, 1536);
static struct k_work_q wq;

static void render_handler(struct k_work *work);
static K_WORK_DELAYABLE_DEFINE(render_work, render_handler);

static bool ready; /* the work queue exists; events that arrive before that are picked up by the boot render */

static void request_render(void) {
    if (ready) {
        k_work_reschedule_for_queue(&wq, &render_work, K_MSEC(5));
    }
}

/* ---------- what a key does -> group ---------- */

static bool starts(const char *s, const char *p) {
    return strncmp(s, p, strlen(p)) == 0;
}

static int classify_kp(uint32_t param) {
    uint16_t page = ZMK_HID_USAGE_PAGE(param);
    uint16_t id = ZMK_HID_USAGE_ID(param);
    uint8_t m = SELECT_MODS(param);
    uint8_t mods = (m & 0x0F) | (m >> 4); /* bit0 ctrl, bit1 shift, bit2 alt, bit3 gui; left and right alike */
    bool ctrl = mods & 1, alt = mods & 4, gui = mods & 8;

    if (page == 0x0C) {
        return G_MEDIA;
    }
    if (id >= 0xE0 && id <= 0xE7) {
        return G_MOD;
    }
    if ((ctrl && gui) || (gui && id == 0x2B /* Tab */)) {
        return G_DESKTOP; /* Ctrl+Cmd+key, Win+Tab */
    }
    if (id >= 0x4F && id <= 0x52) { /* right left down up */
        bool vertical = id >= 0x51;
        if (!mods) return G_ARROW;
        if (gui) return G_LINE;
        if (alt) return G_WORD;
        if (ctrl) return vertical ? G_DESKTOP : G_WORD; /* Ctrl+Up = Mission Control */
        return G_ARROW;
    }
    if (id == 0x4A || id == 0x4D) return G_LINE;   /* Home End */
    if (id == 0x4B || id == 0x4E) return G_PAGE;   /* PgUp PgDn */
    if (id == 0x2A || id == 0x4C) return G_DELETE; /* Backspace Delete */
    if (id >= 0x04 && id <= 0x1D) {                /* letters */
        if (ctrl || gui) {
            if (id == 0x1D || id == 0x1B || id == 0x06 || id == 0x19) return G_CLIP; /* Z X C V */
            return G_MACRO;
        }
        return G_LETTER;
    }
    if (id >= 0x1E && id <= 0x27) { /* digits */
        return (mods & 2) ? G_SYMBOL : G_NUMBER;
    }
    if (id == 0x28 || id == 0x29 || id == 0x2B || id == 0x2C || id == 0x39 || id == 0x49) return G_CTRL;
    if (id >= 0x2D && id <= 0x38) return G_SYMBOL;
    if (id >= 0x3A && id <= 0x48) return G_FKEY;
    return G_LETTER;
}

/* Group of a binding, or -1 for a key that does nothing. */
static int classify(const struct zmk_behavior_binding *b) {
    const char *n = b->behavior_dev;

    if (!n || !strcmp(n, "none")) return -1;
    if (!strcmp(n, "key_press")) return classify_kp(b->param1);
    if (starts(n, "home_row_mod")) return classify_kp(b->param2);
    if (starts(n, "layer_tap") || !strcmp(n, "momentary_layer") || !strcmp(n, "toggle_layer") ||
        !strcmp(n, "to_layer")) {
        return G_LAYER;
    }
    if (!strcmp(n, "bootloader")) return G_DANGER;
    if (!strcmp(n, "bluetooth") || !strcmp(n, "outputs") || starts(n, "c80rgb") || starts(n, "os_") ||
        starts(n, "behavior_rgb")) {
        return G_SYSTEM;
    }
    return G_MACRO; /* macros, caps word, anything else that is bound */
}

/* The binding in force at a position: highest active layer that is not transparent. */
static const struct zmk_behavior_binding *effective(uint8_t pos) {
    for (int l = NLAYERS - 1; l >= 0; l--) {
        zmk_keymap_layer_id_t id = zmk_keymap_layer_index_to_id(l);
        if (!zmk_keymap_layer_active(id)) {
            continue;
        }
        const struct zmk_behavior_binding *b = zmk_keymap_get_layer_binding_at_idx(id, pos);
        if (b && b->behavior_dev && !strcmp(b->behavior_dev, "transparent")) {
            continue;
        }
        return b;
    }
    return NULL;
}

/* ---------- frame ---------- */

static void put(int led, uint32_t rgb) {
    if (led >= 0 && led < C80_TOTAL_LEDS) {
        px[led].r = (rgb >> 16) & 0xFF;
        px[led].g = (rgb >> 8) & 0xFF;
        px[led].b = rgb & 0xFF;
    }
}

static void put_key(uint8_t pos, uint32_t rgb) {
    if (pos_led[pos] != C80_LED_NONE) {
        put(pos_led[pos], rgb);
    }
    for (int i = 0; i < 2; i++) {
        if (pos_extra[pos][i] != C80_LED_NONE) {
            put(pos_extra[pos][i], rgb);
        }
    }
}

/* A host has configured the board and the bus is not suspended. Without VBUS sensing this is the only
 * sign of the cable: a pulled cable leaves the bus in SUSPEND (and still "HID ready"), as does a sleeping
 * host; both count as unplugged. */
static bool plugged_in(void) {
#if IS_ENABLED(CONFIG_ZMK_USB)
    return zmk_usb_is_hid_ready() && zmk_usb_get_status() != USB_DC_SUSPEND;
#else
    return false;
#endif
}

static void draw_gauge(void) {
#if IS_ENABLED(CONFIG_ZMK_BATTERY_REPORTING)
    uint8_t soc = zmk_battery_state_of_charge();
#else
    uint8_t soc = 0;
#endif
    int n = c80_gauge_keys(soc);

    for (int i = 0; i < n; i++) {
        if (gauge_pos[i] < NPOS) {
            put_key(gauge_pos[i], c80_gauge_color(i));
        }
    }
}

static void draw_ambient(bool win) {
    const uint32_t *c = win ? ambient_win : ambient_mac;
    uint32_t now = k_uptime_get_32();

    for (int led = 0; led < C80_TOTAL_LEDS; led++) {
        if (led_used[led]) {
            put(led, c80_mix(c[0], c[1], c80_wave(c80_ambient_phase(now, led_x[led], led_y[led], win))));
        }
    }
}

/* ---------- held modifiers ---------- */

#define PICK_ALL 0xFF

static const struct zmk_behavior_binding *eff[NPOS]; /* effective binding per position, this frame */

static bool is_hrm(const struct zmk_behavior_binding *b) {
    return b->behavior_dev && starts(b->behavior_dev, "home_row_mod");
}

/* Modifier bit (0..7) of a binding whose hold or key is a modifier that is held now, else -1. */
static int held_mod_bit(const struct zmk_behavior_binding *b, uint8_t held) {
    uint16_t id = ZMK_HID_USAGE_ID(b->param1);

    if (!b->behavior_dev || id < 0xE0 || id > 0xE7 || !(held & BIT(id - 0xE0))) {
        return -1;
    }
    return id - 0xE0;
}

/* Home-row mods are recognised by held modifier state because position events do not reliably reach
 * this listener (engine.c.md). Two home-row keys can share a modifier (left and right hand), so for each
 * held modifier the pressed bit picks the one key when it names exactly one; otherwise all of that
 * modifier's home-row keys light. */
static void pick_home_row_mods(uint8_t held, uint8_t pick[8]) {
    uint8_t npressed[8] = {0};

    memset(pick, PICK_ALL, 8);
    for (uint8_t pos = 0; pos < NPOS; pos++) {
        const struct zmk_behavior_binding *b = eff[pos];
        int m = b ? held_mod_bit(b, held) : -1;
        if (m >= 0 && is_hrm(b) && atomic_test_bit(pressed, pos)) {
            npressed[m]++;
            pick[m] = pos;
        }
    }
    for (int m = 0; m < 8; m++) {
        if (npressed[m] != 1) {
            pick[m] = PICK_ALL;
        }
    }
}

/* Builds the frame; returns true when it animates and needs another one soon. */
static bool build_frame(void) {
    memset(px, 0, sizeof(px));
    if (gauge) {
        draw_gauge();
        return false;
    }
    if (idle || !st.enabled) {
        return false;
    }

    /* highest active layer that is not a marker layer */
    int top = 0;
    for (int l = NLAYERS - 1; l >= 0; l--) {
        if (layer_mode[l] != MODE_MARKER && zmk_keymap_layer_active(zmk_keymap_layer_index_to_id(l))) {
            top = l;
            break;
        }
    }
    bool win = WIN_LAYER < NLAYERS && zmk_keymap_layer_active(zmk_keymap_layer_index_to_id(WIN_LAYER));
    bool usb = plugged_in();
    if (!usb && layer_mode[top] != MODE_KEYS) {
        return false; /* on battery, Base and Native stay fully dark, held mods included */
    }
    bool ambient = layer_mode[top] == MODE_AMBIENT && usb;
    if (ambient) {
        draw_ambient(win);
    } else {
        uint32_t side = win ? layer_side_win[top] : layer_side[top];
        for (int led = C80_KEY_LEDS; led < C80_TOTAL_LEDS; led++) {
            put(led, side);
        }
    }

    for (uint8_t pos = 0; pos < NPOS; pos++) {
        eff[pos] = effective(pos);
    }
    uint8_t held = zmk_hid_get_explicit_mods();
    uint8_t pick[8];
    pick_home_row_mods(held, pick);
    for (uint8_t pos = 0; pos < NPOS; pos++) {
        const struct zmk_behavior_binding *b = eff[pos];
        if (!b) {
            continue;
        }

        int m = held_mod_bit(b, held);
        if (m >= 0 && (is_hrm(b) ? (pick[m] == PICK_ALL || pick[m] == pos) : atomic_test_bit(pressed, pos))) {
            put_key(pos, mod_color[m & 3]);
            continue;
        }

        if (layer_mode[top] != MODE_KEYS) {
            continue;
        }
        int g = classify(b);
        if (g < 0) {
            continue;
        }
        uint32_t color = group_color[g];
        for (size_t i = 0; i + 2 < ARRAY_SIZE(overrides); i += 3) {
            if (overrides[i] == (uint32_t)top && overrides[i + 1] == pos) {
                color = overrides[i + 2];
            }
        }
        put_key(pos, color);
    }
    return ambient;
}

static void scale_frame(uint8_t level) {
    uint32_t sum = 0;

    for (int i = 0; i < C80_TOTAL_LEDS; i++) {
        px[i].r = (px[i].r * level * CONFIG_CRUSH80_RGB_BRT_MAX) / (BRT_LEVELS * 100);
        px[i].g = (px[i].g * level * CONFIG_CRUSH80_RGB_BRT_MAX) / (BRT_LEVELS * 100);
        px[i].b = (px[i].b * level * CONFIG_CRUSH80_RGB_BRT_MAX) / (BRT_LEVELS * 100);
        sum += px[i].r + px[i].g + px[i].b;
    }
    /* hard current budget: never exceed it whatever the colours and brightness */
    if (sum > CONFIG_CRUSH80_RGB_BUDGET) {
        for (int i = 0; i < C80_TOTAL_LEDS; i++) {
            px[i].r = (px[i].r * CONFIG_CRUSH80_RGB_BUDGET) / sum;
            px[i].g = (px[i].g * CONFIG_CRUSH80_RGB_BUDGET) / sum;
            px[i].b = (px[i].b * CONFIG_CRUSH80_RGB_BUDGET) / sum;
        }
    }
}

static void render_handler(struct k_work *work) {
    if (fails >= 10) {
        return; /* strip keeps failing: stay dark until reboot */
    }
    bool animating = build_frame();
    scale_frame(gauge ? BRT_LEVELS : st.level); /* the gauge stays readable at the lowest brightness */
    if (animating) {
        k_work_reschedule_for_queue(&wq, &render_work, K_MSEC(AMBIENT_FRAME_MS));
    }
    if (last_valid && memcmp(px, last, sizeof(px)) == 0) {
        return;
    }
    int rc = led_strip_update_rgb(strip, px, C80_TOTAL_LEDS);
    if (rc) {
        fails++;
        LOG_WRN("strip update failed: %d (%d)", rc, fails);
        if (fails < 3) {
            k_work_reschedule_for_queue(&wq, &render_work, K_MSEC(200));
        }
        return;
    }
    fails = 0;
    memcpy(last, px, sizeof(px));
    last_valid = true;
}

/* ---------- battery gauge ---------- */

static void gauge_timeout(struct k_work *work) {
    gauge = false;
    request_render();
}
static K_WORK_DELAYABLE_DEFINE(gauge_work, gauge_timeout);

/* ---------- saved state ---------- */

#if IS_ENABLED(CONFIG_SETTINGS)
static void save_handler(struct k_work *work) {
    settings_save_one("c80rgb/state", &st, sizeof(st));
}
static K_WORK_DELAYABLE_DEFINE(save_work, save_handler);

static int set_cb(const char *name, size_t len, settings_read_cb read_cb, void *cb_arg) {
    const char *next;

    if (settings_name_steq(name, "state", &next) && !next) {
        if (len != sizeof(st)) {
            return -EINVAL;
        }
        int rc = read_cb(cb_arg, &st, sizeof(st));
        if (rc >= 0 && (st.level < 1 || st.level > BRT_LEVELS)) {
            st.level = BRT_LEVELS;
        }
        return rc >= 0 ? 0 : -EIO;
    }
    return -ENOENT;
}
SETTINGS_STATIC_HANDLER_DEFINE(c80rgb, "c80rgb", NULL, set_cb, NULL, NULL);
#endif

static void save_soon(void) {
#if IS_ENABLED(CONFIG_SETTINGS)
    if (ready) {
        k_work_reschedule_for_queue(&wq, &save_work, K_SECONDS(3));
    }
#endif
}

int c80_rgb_action(int action) {
    switch (action) {
    case C80_RGB_TOGGLE:
        st.enabled = !st.enabled;
        save_soon();
        break;
    case C80_RGB_BRIGHTER:
        if (st.level < BRT_LEVELS) st.level++;
        save_soon();
        break;
    case C80_RGB_DIMMER:
        if (st.level > 1) st.level--;
        save_soon();
        break;
    case C80_RGB_BATTERY:
        gauge = true;
        if (ready) {
            k_work_reschedule_for_queue(&wq, &gauge_work, K_SECONDS(GAUGE_MAX_S));
        }
        break;
    default:
        return -EINVAL;
    }
    request_render();
    return 0;
}

int c80_rgb_release(int action) {
    if (action == C80_RGB_BATTERY) {
        gauge = false;
        k_work_cancel_delayable(&gauge_work);
        request_render();
    }
    return 0;
}

/* ---------- events and init ---------- */

static int listener(const zmk_event_t *eh) {
    const struct zmk_position_state_changed *p = as_zmk_position_state_changed(eh);
    if (p) {
        if (p->position < NPOS) {
            if (p->state) {
                atomic_set_bit(pressed, p->position);
            } else {
                atomic_clear_bit(pressed, p->position);
            }
        }
    }
    const struct zmk_activity_state_changed *a = as_zmk_activity_state_changed(eh);
    if (a) {
        idle = (a->state != ZMK_ACTIVITY_ACTIVE);
    }
    request_render();
    return ZMK_EV_EVENT_BUBBLE;
}

ZMK_LISTENER(c80rgb, listener);
ZMK_SUBSCRIPTION(c80rgb, zmk_layer_state_changed);
ZMK_SUBSCRIPTION(c80rgb, zmk_position_state_changed);
/* ZMK never raises zmk_modifiers_state_changed; a modifier press or release (a home-row mod resolving
 * to its hold, or a plain modifier key) shows up as a keycode event. */
ZMK_SUBSCRIPTION(c80rgb, zmk_keycode_state_changed);
ZMK_SUBSCRIPTION(c80rgb, zmk_activity_state_changed);
ZMK_SUBSCRIPTION(c80rgb, zmk_usb_conn_state_changed);
#if IS_ENABLED(CONFIG_ZMK_BATTERY_REPORTING)
ZMK_SUBSCRIPTION(c80rgb, zmk_battery_state_changed);
#endif

static void boot_handler(struct k_work *work) {
    request_render();
}
static K_WORK_DELAYABLE_DEFINE(boot_work, boot_handler);

static void place_led(uint8_t led, uint8_t r, uint8_t c) {
    if (led < C80_KEY_LEDS) {
        led_used[led] = true;
        led_x[led] = c * 17; /* matrix column approximates the key's x: 16 columns over 0..255 */
        led_y[led] = r * 51;
    }
}

static int c80rgb_init(void) {
    memset(gauge_pos, 0xFF, sizeof(gauge_pos));
    for (int p = 0; p < NPOS; p++) {
        uint8_t r = pos_rc[p] >> 8, c = pos_rc[p] & 0xFF;
        pos_led[p] = (r < 6 && c < 16) ? c80_rc_to_led[r][c] : C80_LED_NONE;
        pos_extra[p][0] = pos_extra[p][1] = C80_LED_NONE;
        place_led(pos_led[p], r, c);
        int n = 0;
        for (size_t i = 0; i < ARRAY_SIZE(c80_extra_leds); i++) {
            if (c80_extra_leds[i][0] == r && c80_extra_leds[i][1] == c && n < 2) {
                pos_extra[p][n++] = c80_extra_leds[i][2];
                place_led(c80_extra_leds[i][2], r, c);
            }
        }
        if (r == 1 && c >= 1 && c <= C80_GAUGE_KEYS) { /* number row: column 1 is the 1 key */
            gauge_pos[c - 1] = p;
        }
    }
    /* side bar and logo: their geometry is unmapped (todo.md), so spread the wave by LED index */
    for (int led = C80_KEY_LEDS; led < C80_TOTAL_LEDS; led++) {
        led_used[led] = true;
        led_x[led] = (led - C80_KEY_LEDS) * 255 / (C80_TOTAL_LEDS - 1 - C80_KEY_LEDS);
    }
    if (!device_is_ready(strip)) {
        LOG_ERR("LED strip not ready");
        fails = 10;
        return 0;
    }
    k_work_queue_start(&wq, wq_stack, K_THREAD_STACK_SIZEOF(wq_stack), K_PRIO_PREEMPT(5), NULL);
    k_thread_name_set(&wq.thread, "c80rgb");
    ready = true;
    /* saved state has loaded by now */
    k_work_schedule_for_queue(&wq, &boot_work, K_SECONDS(2));
    return 0;
}
SYS_INIT(c80rgb_init, APPLICATION, 99);
