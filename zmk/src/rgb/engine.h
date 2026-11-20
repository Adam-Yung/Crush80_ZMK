/* SPDX-License-Identifier: Apache-2.0 */
#pragma once

#include <zephyr/sys/util.h>

/* Backlight actions for the &c80rgb_* behaviours. */
#define C80_RGB_TOGGLE 0
#define C80_RGB_BRIGHTER 1
#define C80_RGB_DIMMER 2

#if IS_ENABLED(CONFIG_CRUSH80_RGB_ENGINE)
int c80_rgb_action(int action);
#else
static inline int c80_rgb_action(int action) {
    (void)action;
    return 0;
}
#endif

/* OS selection (zmk/src/crush80_os.c): 0 = macOS, 1 = Windows, 2 = toggle. */
int c80_os_action(int action);
