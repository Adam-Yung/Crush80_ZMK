/*
 * AW20216S RGB lighting engine for the Wobkey Crush 80.
 *
 * Implements three effects:
 *   LAYER  — per-layer colors with HRM reactive lighting (default)
 *   SOLID  — all LEDs at a fixed color
 *   ECHO   — reactive: key press lights up the key LED, fades to black
 *
 * The engine runs in a dedicated low-priority thread at ~30 Hz.
 * Pin-sharing coordinator (crush80_led_acquire/release) is called around
 * every aw20216s_update() to avoid conflicts with kscan.
 *
 * Copyright (c) 2025 — Apache 2.0
 */

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/init.h>
#include <zmk/events/position_state_changed.h>
#include <zmk/events/layer_state_changed.h>
#include <zmk/events/position_state_changed.h>
#include <zmk/keymap.h>
#include <zmk/keymap.h>

#include "aw20216s.h"

#include <zephyr/logging/log.h>
LOG_MODULE_REGISTER(crush80_rgb, CONFIG_AW20216S_LOG_LEVEL);

/* -----------------------------------------------------------------------
 * Pin-sharing coordinator (defined in crush80_led_coord.c)
 * ---------------------------------------------------------------------- */

extern int crush80_led_acquire(void);
extern int crush80_led_release(void);

/* -----------------------------------------------------------------------
 * Configuration
 * ---------------------------------------------------------------------- */

#define RGB_THREAD_PERIOD_MS  33  /* ~30 Hz */

#define NUM_PER_KEY_LEDS  91
#define LOGO_LED_INDEX    88

/* Echo effect */
#define AMBIENT_R   5
#define AMBIENT_G   5
#define AMBIENT_B   10
#define ECHO_PEAK_R   0
#define ECHO_PEAK_G   150
#define ECHO_PEAK_B  255
#define ECHO_FADE_MS 500

/* Solid default color */
#define SOLID_R  180
#define SOLID_G  180
#define SOLID_B  180

#define MAX_ECHO_LEDS  16

/* -----------------------------------------------------------------------
 * Effect enum
 * ---------------------------------------------------------------------- */

enum crush80_rgb_effect {
	RGB_EFFECT_LAYER = 0,
	RGB_EFFECT_SOLID,
	RGB_EFFECT_ECHO,
	RGB_EFFECT_COUNT,
};

/* -----------------------------------------------------------------------
 * Color type
 * ---------------------------------------------------------------------- */

struct rgb_color {
	uint8_t r, g, b;
};

#define RGB(r, g, b)  { (r), (g), (b) }
#define RGB_OFF       { 0, 0, 0 }

/* -----------------------------------------------------------------------
 * Echo state
 * ---------------------------------------------------------------------- */

struct echo_slot {
	uint8_t  led_idx;
	int64_t  pressed_at_ms;
	bool     active;
};

/* -----------------------------------------------------------------------
 * HRM positions and colors
 * ---------------------------------------------------------------------- */

#define NUM_HRM_KEYS  8

struct hrm_key {
	uint8_t position;
	struct rgb_color color;
};

static const struct hrm_key hrm_keys[NUM_HRM_KEYS] = {
	{ 51, RGB(200, 0, 0)     },  /* A / LCTRL */
	{ 52, RGB(0, 200, 0)     },  /* S / LALT */
	{ 53, RGB(0, 100, 255)   },  /* D / LGUI */
	{ 54, RGB(255, 200, 0)   },  /* F / LSHFT */
	{ 57, RGB(255, 200, 0)   },  /* J / RSHFT */
	{ 58, RGB(0, 100, 255)   },  /* K / RGUI */
	{ 59, RGB(0, 200, 0)     },  /* L / RALT */
	{ 60, RGB(200, 0, 0)     },  /* ; / RCTRL */
};

/* -----------------------------------------------------------------------
 * Layer color maps
 * Per-layer LED color assignments. Only non-zero entries are listed;
 * all others default to OFF.
 * ---------------------------------------------------------------------- */

/* Layer 1 (FN) key indices */
static const struct rgb_color layer_fn_colors[NUM_PER_KEY_LEDS] = {
	/* F-row: indices 0-15 = red */
	[0]  = RGB(200, 0, 0), [1]  = RGB(200, 0, 0), [2]  = RGB(200, 0, 0),
	[3]  = RGB(200, 0, 0), [4]  = RGB(200, 0, 0), [5]  = RGB(200, 0, 0),
	[6]  = RGB(200, 0, 0), [7]  = RGB(200, 0, 0), [8]  = RGB(200, 0, 0),
	[9]  = RGB(200, 0, 0), [10] = RGB(200, 0, 0), [11] = RGB(200, 0, 0),
	[12] = RGB(200, 0, 0), [13] = RGB(200, 0, 0), [14] = RGB(200, 0, 0),
	[15] = RGB(200, 0, 0),
	/* BT 1,2,3 positions (mapped to number row area): blue */
	[17] = RGB(0, 100, 255), [18] = RGB(0, 100, 255), [19] = RGB(0, 100, 255),
	/* USB/BT toggle */
	[20] = RGB(0, 200, 0),
	/* RGB controls */
	[21] = RGB(200, 200, 200), [22] = RGB(200, 200, 200),
	[23] = RGB(200, 200, 200), [24] = RGB(200, 200, 200),
};

/* Layer 2 (NAV) */
static const struct rgb_color layer_nav_colors[NUM_PER_KEY_LEDS] = {
	/* W (trigger) = green — position ~37 in sequential */
	[37] = RGB(0, 200, 0),
	/* IJKL = cool blue — positions 56,57,58,59 area */
	[40] = RGB(0, 120, 255), /* I */
	[57] = RGB(0, 120, 255), /* J */
	[58] = RGB(0, 120, 255), /* K */
	[59] = RGB(0, 120, 255), /* L */
	/* U = purple */
	[39] = RGB(150, 0, 255),
	/* O = pink */
	[41] = RGB(255, 0, 150),
	/* E/R (Home/End) = teal */
	[38] = RGB(0, 200, 180), /* E */
	[22] = RGB(0, 200, 180), /* R */
	/* Z/X/C/V (edit) = orange */
	[62] = RGB(255, 140, 0), /* Z */
	[63] = RGB(255, 140, 0), /* X */
	[64] = RGB(255, 140, 0), /* C */
	[65] = RGB(255, 140, 0), /* V */
	/* Shift keys = yellow */
	[61] = RGB(255, 200, 0), /* LShift */
	[72] = RGB(255, 200, 0), /* RShift */
	/* G (CapsWord) = white */
	[54] = RGB(200, 200, 200),
	/* comma/dot (select) = coral */
	[69] = RGB(255, 100, 80), /* comma */
	[70] = RGB(255, 100, 80), /* dot */
};

/* Layer 3 (EXTNAV) — same as NAV but word-jump keys slightly brighter blue */
static const struct rgb_color layer_extnav_colors[NUM_PER_KEY_LEDS] = {
	[37] = RGB(0, 200, 0),
	/* IJKL word-jump = brighter blue */
	[40] = RGB(0, 150, 255),
	[57] = RGB(0, 150, 255),
	[58] = RGB(0, 150, 255),
	[59] = RGB(0, 150, 255),
	[39] = RGB(150, 0, 255),
	[41] = RGB(255, 0, 150),
	[38] = RGB(0, 200, 180),
	[22] = RGB(0, 200, 180),
	[62] = RGB(255, 140, 0),
	[63] = RGB(255, 140, 0),
	[64] = RGB(255, 140, 0),
	[65] = RGB(255, 140, 0),
	[61] = RGB(255, 200, 0),
	[72] = RGB(255, 200, 0),
	[54] = RGB(200, 200, 200),
	[69] = RGB(255, 100, 80),
	[70] = RGB(255, 100, 80),
};

/* Layer 4 (SYM) */
static const struct rgb_color layer_sym_colors[NUM_PER_KEY_LEDS] = {
	/* Number keys (4-9 area) = purple */
	[20] = RGB(150, 0, 255), [21] = RGB(150, 0, 255),
	[22] = RGB(150, 0, 255), [23] = RGB(150, 0, 255),
	[24] = RGB(150, 0, 255), [25] = RGB(150, 0, 255),
	/* Brackets/parens = magenta */
	[39] = RGB(255, 0, 180), [40] = RGB(255, 0, 180),
	[41] = RGB(255, 0, 180), [42] = RGB(255, 0, 180),
	/* Operators = cyan */
	[55] = RGB(0, 220, 220), [56] = RGB(0, 220, 220),
	[57] = RGB(0, 220, 220), [58] = RGB(0, 220, 220),
	/* Coding macros = green */
	[63] = RGB(0, 200, 0), [64] = RGB(0, 200, 0),
	[65] = RGB(0, 200, 0), [66] = RGB(0, 200, 0),
};

/* -----------------------------------------------------------------------
 * Global RGB state
 * ---------------------------------------------------------------------- */

static struct {
	enum crush80_rgb_effect effect;
	uint8_t brightness;
	uint8_t current_layer;
	bool hrm_held[NUM_HRM_KEYS];
	struct echo_slot echoes[MAX_ECHO_LEDS];
	struct k_mutex lock;
} rgb_state = {
	.effect        = RGB_EFFECT_LAYER,
	.brightness    = 200,
	.current_layer = 0,
};

/* -----------------------------------------------------------------------
 * ZMK layer state listener
 * ---------------------------------------------------------------------- */

static int crush80_rgb_layer_listener(const zmk_event_t *eh)
{
	const struct zmk_layer_state_changed *ev =
		as_zmk_layer_state_changed(eh);

	if (!ev) {
		return ZMK_EV_EVENT_BUBBLE;
	}

	k_mutex_lock(&rgb_state.lock, K_FOREVER);

	/* Find the highest active layer */
	uint8_t highest = 0;
	for (uint8_t i = 0; i < 9; i++) {
		if (zmk_keymap_layer_active(i)) {
			highest = i;
		}
	}
	rgb_state.current_layer = highest;

	k_mutex_unlock(&rgb_state.lock);
	return ZMK_EV_EVENT_BUBBLE;
}

ZMK_LISTENER(crush80_rgb_layer, crush80_rgb_layer_listener);
ZMK_SUBSCRIPTION(crush80_rgb_layer, zmk_layer_state_changed);

/* -----------------------------------------------------------------------
 * ZMK position state listener → HRM reactive + echo
 * ---------------------------------------------------------------------- */

static void echo_add(uint8_t led_idx);

static int crush80_rgb_position_listener(const zmk_event_t *eh)
{
	const struct zmk_position_state_changed *ev =
		as_zmk_position_state_changed(eh);

	if (!ev) {
		return ZMK_EV_EVENT_BUBBLE;
	}

	/* Track HRM held state */
	k_mutex_lock(&rgb_state.lock, K_FOREVER);

	for (int i = 0; i < NUM_HRM_KEYS; i++) {
		if (ev->position == hrm_keys[i].position) {
			rgb_state.hrm_held[i] = ev->state;
			break;
		}
	}

	k_mutex_unlock(&rgb_state.lock);

	/* Trigger echo on key press */
	if (ev->state && ev->position < 88) {
		echo_add((uint8_t)ev->position);
	}

	return ZMK_EV_EVENT_BUBBLE;
}

ZMK_LISTENER(crush80_rgb_position, crush80_rgb_position_listener);
ZMK_SUBSCRIPTION(crush80_rgb_position, zmk_position_state_changed);

/* -----------------------------------------------------------------------
 * ZMK keycode state listener → echo trigger
 * ---------------------------------------------------------------------- */

/* Position-to-LED: for per-key LEDs, position index == LED index (0-87) */

static void echo_add(uint8_t led_idx)
{
	k_mutex_lock(&rgb_state.lock, K_FOREVER);

	for (int i = 0; i < MAX_ECHO_LEDS; i++) {
		if (!rgb_state.echoes[i].active ||
		    rgb_state.echoes[i].led_idx == led_idx) {
			rgb_state.echoes[i].led_idx      = led_idx;
			rgb_state.echoes[i].pressed_at_ms = k_uptime_get();
			rgb_state.echoes[i].active       = true;
			k_mutex_unlock(&rgb_state.lock);
			return;
		}
	}

	k_mutex_unlock(&rgb_state.lock);
}

/* Removed: crush80_rgb_key_listener (keycode event has no position field).
 * Echo is triggered from crush80_rgb_position_listener instead. */

/* Key echo triggered from position listener below */

/* -----------------------------------------------------------------------
 * Color scale helper
 * ---------------------------------------------------------------------- */

static uint8_t scale(uint8_t val, uint8_t brightness)
{
	return (uint8_t)(((uint16_t)val * brightness) >> 8);
}

/* -----------------------------------------------------------------------
 * Effect: LAYER (per-layer + HRM reactive)
 * ---------------------------------------------------------------------- */

static const struct rgb_color *get_layer_colormap(uint8_t layer)
{
	switch (layer) {
	case 1:  return layer_fn_colors;
	case 2:  return layer_nav_colors;
	case 3:  return layer_extnav_colors;
	case 4:  return layer_sym_colors;
	case 7:  return layer_nav_colors;      /* MACNAV = NAV */
	case 8:  return layer_extnav_colors;   /* MACEXTNAV = EXTNAV */
	default: return NULL;
	}
}

static void render_layer(const struct device *led_dev)
{
	uint8_t layer;

	k_mutex_lock(&rgb_state.lock, K_FOREVER);
	layer = rgb_state.current_layer;

	/* Clear all LEDs first */
	aw20216s_set_all_rgb(led_dev, 0, 0, 0);

	switch (layer) {
	case 0: /* BASE: all per-key OFF, logo = warm white */
		aw20216s_set_rgb(led_dev, LOGO_LED_INDEX,
			scale(255, rgb_state.brightness),
			scale(200, rgb_state.brightness),
			scale(100, rgb_state.brightness));
		break;

	case 5: /* NATIVE: all keys dim white */
		aw20216s_set_all_rgb(led_dev,
			scale(30, rgb_state.brightness),
			scale(30, rgb_state.brightness),
			scale(30, rgb_state.brightness));
		break;

	case 6: /* MAC: same as BASE but logo = cyan */
		aw20216s_set_rgb(led_dev, LOGO_LED_INDEX,
			scale(0, rgb_state.brightness),
			scale(200, rgb_state.brightness),
			scale(220, rgb_state.brightness));
		break;

	case 1: /* FN */
	case 2: /* NAV */
	case 3: /* EXTNAV */
	case 4: /* SYM */
	case 7: /* MACNAV */
	case 8: /* MACEXTNAV */
	{
		const struct rgb_color *cmap = get_layer_colormap(layer);
		if (cmap) {
			for (int i = 0; i < NUM_PER_KEY_LEDS; i++) {
				if (cmap[i].r || cmap[i].g || cmap[i].b) {
					aw20216s_set_rgb(led_dev, i,
						scale(cmap[i].r, rgb_state.brightness),
						scale(cmap[i].g, rgb_state.brightness),
						scale(cmap[i].b, rgb_state.brightness));
				}
			}
		}
		break;
	}

	default:
		break;
	}

	/* HRM reactive overlay: override LED color for held HRM keys */
	for (int i = 0; i < NUM_HRM_KEYS; i++) {
		if (rgb_state.hrm_held[i]) {
			uint8_t pos = hrm_keys[i].position;
			if (pos < NUM_PER_KEY_LEDS) {
				aw20216s_set_rgb(led_dev, pos,
					scale(hrm_keys[i].color.r, rgb_state.brightness),
					scale(hrm_keys[i].color.g, rgb_state.brightness),
					scale(hrm_keys[i].color.b, rgb_state.brightness));
			}
		}
	}

	k_mutex_unlock(&rgb_state.lock);
}

/* -----------------------------------------------------------------------
 * Effect: SOLID
 * ---------------------------------------------------------------------- */

static void render_solid(const struct device *led_dev)
{
	uint8_t r = scale(SOLID_R, rgb_state.brightness);
	uint8_t g = scale(SOLID_G, rgb_state.brightness);
	uint8_t b = scale(SOLID_B, rgb_state.brightness);

	aw20216s_set_all_rgb(led_dev, r, g, b);
}

/* -----------------------------------------------------------------------
 * Effect: ECHO (reactive fade)
 * ---------------------------------------------------------------------- */

static void render_echo(const struct device *led_dev)
{
	int64_t now = k_uptime_get();

	uint8_t ar = scale(AMBIENT_R, rgb_state.brightness);
	uint8_t ag = scale(AMBIENT_G, rgb_state.brightness);
	uint8_t ab = scale(AMBIENT_B, rgb_state.brightness);
	aw20216s_set_all_rgb(led_dev, ar, ag, ab);

	k_mutex_lock(&rgb_state.lock, K_FOREVER);

	for (int i = 0; i < MAX_ECHO_LEDS; i++) {
		if (!rgb_state.echoes[i].active) {
			continue;
		}

		int64_t elapsed = now - rgb_state.echoes[i].pressed_at_ms;

		if (elapsed >= ECHO_FADE_MS) {
			rgb_state.echoes[i].active = false;
			continue;
		}

		uint8_t fade = (uint8_t)(255 - (elapsed * 255 / ECHO_FADE_MS));
		uint8_t r = scale(scale(ECHO_PEAK_R, fade), rgb_state.brightness);
		uint8_t g = scale(scale(ECHO_PEAK_G, fade), rgb_state.brightness);
		uint8_t b = scale(scale(ECHO_PEAK_B, fade), rgb_state.brightness);

		aw20216s_set_rgb(led_dev, rgb_state.echoes[i].led_idx, r, g, b);
	}

	k_mutex_unlock(&rgb_state.lock);
}

/* -----------------------------------------------------------------------
 * RGB engine thread
 * ---------------------------------------------------------------------- */

static void rgb_thread_fn(void *p1, void *p2, void *p3)
{
	ARG_UNUSED(p1);
	ARG_UNUSED(p2);
	ARG_UNUSED(p3);

	const struct device *led_dev = DEVICE_DT_GET(DT_NODELABEL(aw20216s0));

	if (!device_is_ready(led_dev)) {
		LOG_ERR("AW20216S device not ready — RGB disabled");
		return;
	}

	LOG_INF("Crush 80 RGB engine started (effect=%d)", rgb_state.effect);

	while (1) {
		switch (rgb_state.effect) {
		case RGB_EFFECT_LAYER:
			render_layer(led_dev);
			break;
		case RGB_EFFECT_SOLID:
			render_solid(led_dev);
			break;
		case RGB_EFFECT_ECHO:
		default:
			render_echo(led_dev);
			break;
		}

		crush80_led_acquire();
		aw20216s_update(led_dev);
		crush80_led_release();

		k_sleep(K_MSEC(RGB_THREAD_PERIOD_MS));
	}
}

K_THREAD_DEFINE(crush80_rgb_tid, 1536, rgb_thread_fn,
		NULL, NULL, NULL, K_PRIO_PREEMPT(8), 0, 0);

/* -----------------------------------------------------------------------
 * Public API — called from keymap behaviors
 * ---------------------------------------------------------------------- */

void crush80_rgb_toggle(void)
{
	if (rgb_state.brightness == 0) {
		rgb_state.brightness = 200;
	} else {
		rgb_state.brightness = 0;
	}
}

void crush80_rgb_next_effect(void)
{
	rgb_state.effect = (rgb_state.effect + 1) % RGB_EFFECT_COUNT;
	LOG_INF("RGB effect → %d", rgb_state.effect);
}

void crush80_rgb_brightness_up(void)
{
	rgb_state.brightness = MIN(255, rgb_state.brightness + 25);
}

void crush80_rgb_brightness_down(void)
{
	rgb_state.brightness = (rgb_state.brightness > 25)
		? rgb_state.brightness - 25 : 0;
}
