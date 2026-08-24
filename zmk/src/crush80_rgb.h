#pragma once

#include <stdint.h>
#include <stdbool.h>

#define CRUSH80_LED_COUNT_CHIP0  91
#define CRUSH80_LED_COUNT_CHIP1  63
#define CRUSH80_LED_COUNT_TOTAL  154

void crush80_rgb_set_led(uint8_t index, uint8_t r, uint8_t g, uint8_t b);
void crush80_rgb_set_all(uint8_t r, uint8_t g, uint8_t b);
void crush80_rgb_toggle(void);
bool crush80_rgb_is_on(void);
