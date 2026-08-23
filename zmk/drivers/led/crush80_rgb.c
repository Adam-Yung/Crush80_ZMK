/*
 * AW20216S RGB lighting engine for the Wobkey Crush 80.
 *
 * Implements two effects:
 *   SOLID  — all LEDs at a fixed color (default: white at 30% brightness)
 *   ECHO   — reactive: key press lights up the key LED, fades to black over
 *            ~500 ms. Other LEDs show a dim "ambient" color.
 *
 * The engine runs in a dedicated low-priority thread, updating at ~60 Hz.
 * ZMK's key event listener feeds key positions into the echo state.
 *
 * Copyright (c) 2025 — Apache 2.0
 */

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/init.h>
#include <zmk/events/keycode_state_changed.h>
#include <zmk/keymap.h>
#include <zmk/matrix.h>

#include "aw20216s.h"

#include <zephyr/logging/log.h>
LOG_MODULE_REGISTER(crush80_rgb, CONFIG_AW20216S_LOG_LEVEL);

/* -----------------------------------------------------------------------
 * Configuration
 * ---------------------------------------------------------------------- */

/* Ambient color shown when no key has been pressed recently */
#define AMBIENT_R  5
#define AMBIENT_G  5
#define AMBIENT_B  10

/* Peak color of echo flash (key press) */
#define ECHO_PEAK_R  0
#define ECHO_PEAK_G  150
#define ECHO_PEAK_B  255

/* Echo fade time in ms */
#define ECHO_FADE_MS  500

/* Solid default color */
#define SOLID_R  180
#define SOLID_G  180
#define SOLID_B  180

/* Refresh interval */
#define RGB_THREAD_PERIOD_MS  16  /* ~60 Hz */

/* Number of LED slots with active echo */
#define MAX_ECHO_LEDS  16

/* -----------------------------------------------------------------------
 * Effect state
 * ---------------------------------------------------------------------- */

enum crush80_rgb_effect {
	RGB_EFFECT_SOLID = 0,
	RGB_EFFECT_ECHO,
	RGB_EFFECT_COUNT,
};

struct echo_slot {
	uint8_t  led_idx;
	int64_t  pressed_at_ms;
	bool     active;
};

static struct {
	enum crush80_rgb_effect effect;
	uint8_t brightness;        /* 0-255 global scale */
	struct echo_slot echoes[MAX_ECHO_LEDS];
	struct k_mutex lock;
} rgb_state = {
	.effect     = RGB_EFFECT_ECHO,
	.brightness = 200,
};

/* -----------------------------------------------------------------------
 * ZMK key event listener → echo trigger
 * ---------------------------------------------------------------------- */

/* RC(row, col) → LED index lookup.
 * This table maps matrix position to AW20216S LED index.
 * PLACEHOLDER: must be calibrated at bring-up.
 * Rows are 0-5, cols 0-15. -1 = no LED at this position.
 */
static const int16_t rc_to_led[6][16] = {
	/* Row 0 */ { 0, 1, 2, 3, 4, 5, 6, 7, 8, 9,10,11,12,13,14,15},
	/* Row 1 */ {16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31},
	/* Row 2 */ {32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47},
	/* Row 3 */ {48,49,50,51,52,53,54,55,56,57,58,59,-1,60,-1,-1},
	/* Row 4 */ {61,-1,62,63,64,65,66,67,68,69,70,71,-1,72,73,-1},
	/* Row 5 */ {74,75,76,-1,-1,77,-1,-1,-1,78,79,80,-1,81,82,83},
};

static void echo_add(uint8_t led_idx)
{
	k_mutex_lock(&rgb_state.lock, K_FOREVER);

	/* Reuse existing slot for same LED or find free slot */
	for (int i = 0; i < MAX_ECHO_LEDS; i++) {
		if (!rgb_state.echoes[i].active ||
		    rgb_state.echoes[i].led_idx == led_idx) {
			rgb_state.echoes[i].led_idx     = led_idx;
			rgb_state.echoes[i].pressed_at_ms = k_uptime_get();
			rgb_state.echoes[i].active      = true;
			k_mutex_unlock(&rgb_state.lock);
			return;
		}
	}

	k_mutex_unlock(&rgb_state.lock);
}

static int crush80_rgb_key_listener(const zmk_event_t *eh)
{
	const struct zmk_keycode_state_changed *ev =
		as_zmk_keycode_state_changed(eh);

	if (!ev || !ev->state) {
		return ZMK_EV_EVENT_BUBBLE;
	}

	/* Get matrix row/col from position */
	uint32_t pos = ev->implicit_modifiers;  /* position encoded in source */
	uint8_t row = ZMK_MATRIX_EXTRACT_ROW(pos);
	uint8_t col = ZMK_MATRIX_EXTRACT_COL(pos);

	if (row < 6 && col < 16) {
		int16_t led = rc_to_led[row][col];
		if (led >= 0) {
			echo_add((uint8_t)led);
		}
	}

	return ZMK_EV_EVENT_BUBBLE;
}

ZMK_LISTENER(crush80_rgb, crush80_rgb_key_listener);
ZMK_SUBSCRIPTION(crush80_rgb, zmk_keycode_state_changed);

/* -----------------------------------------------------------------------
 * Color scale helper
 * ---------------------------------------------------------------------- */

static uint8_t scale(uint8_t val, uint8_t brightness)
{
	return (uint8_t)(((uint16_t)val * brightness) >> 8);
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

	/* Start with dim ambient */
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

		/* Linear fade: 255 → 0 over ECHO_FADE_MS */
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
		case RGB_EFFECT_SOLID:
			render_solid(led_dev);
			break;
		case RGB_EFFECT_ECHO:
		default:
			render_echo(led_dev);
			break;
		}

		aw20216s_update(led_dev);
		k_sleep(K_MSEC(RGB_THREAD_PERIOD_MS));
	}
}

K_THREAD_DEFINE(crush80_rgb_tid, 1024, rgb_thread_fn,
		NULL, NULL, NULL, K_PRIO_PREEMPT(8), 0, 0);

/* -----------------------------------------------------------------------
 * Public API — called from keymap behaviors
 * ---------------------------------------------------------------------- */

void crush80_rgb_toggle(void)
{
	const struct device *led_dev = DEVICE_DT_GET(DT_NODELABEL(aw20216s0));

	/* Toggle between off (ambient=0) and on */
	if (rgb_state.brightness == 0) {
		rgb_state.brightness = 200;
	} else {
		rgb_state.brightness = 0;
		aw20216s_set_all_rgb(led_dev, 0, 0, 0);
		aw20216s_update(led_dev);
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
