/*
 * AW20216S driver public API header
 */

#ifndef AW20216S_H_
#define AW20216S_H_

#include <zephyr/device.h>
#include <stdint.h>

/**
 * Set one LED to an RGB color (buffered — call aw20216s_update() to flush).
 * @param led_idx  Logical LED index (0 to NUM_LEDS-1)
 * @param r,g,b    Color components (0-255)
 */
void aw20216s_set_rgb(const struct device *dev,
		      uint8_t led_idx, uint8_t r, uint8_t g, uint8_t b);

/** Set all LEDs to one color (buffered). */
void aw20216s_set_all_rgb(const struct device *dev,
			  uint8_t r, uint8_t g, uint8_t b);

/** Push buffered PWM values to hardware. */
int aw20216s_update(const struct device *dev);

/* RGB engine controls (called from keymap behaviors) */
void crush80_rgb_toggle(void);
void crush80_rgb_next_effect(void);
void crush80_rgb_brightness_up(void);
void crush80_rgb_brightness_down(void);

#endif /* AW20216S_H_ */
