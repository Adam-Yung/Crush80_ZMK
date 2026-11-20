/* SPDX-License-Identifier: Apache-2.0 */
/*
 * Pure colour maths for the backlight engine: no Zephyr, no state, so the host tests compile it
 * directly (scripts/tests/test_rgb_effects.py). Colours are 0xRRGGBB.
 */
#pragma once

#include <stdint.h>

#define C80_GAUGE_KEYS 10 /* number row 1..0 */

/* Linear mix of a and b, m = 0 gives a, m = 255 gives b. */
static inline uint32_t c80_mix(uint32_t a, uint32_t b, uint8_t m) {
    uint32_t out = 0;

    for (int shift = 0; shift <= 16; shift += 8) {
        uint32_t ca = (a >> shift) & 0xFF, cb = (b >> shift) & 0xFF;
        out |= ((ca * (255U - m) + cb * m + 127U) / 255U) << shift;
    }
    return out;
}

/* 0 -> 0, 128 -> 255, 255 -> ~0, eased at both ends so the wave has no visible corners. */
static inline uint8_t c80_wave(uint8_t phase) {
    uint32_t t = phase < 128 ? phase * 2U : (255U - phase) * 2U; /* triangle 0..254 */
    return (uint8_t)((t * t * (765U - 2U * t)) / 65025U);        /* smoothstep */
}

/* Number of number-row keys lit for a state of charge: one per full 10 %, at least one. */
static inline int c80_gauge_keys(uint8_t soc) {
    int n = soc / 10;

    if (n < 1) {
        return 1;
    }
    return n > C80_GAUGE_KEYS ? C80_GAUGE_KEYS : n;
}

/* Colour of gauge key i (0 = key 1 ... 9 = key 0): red, through yellow, to green. */
static inline uint32_t c80_gauge_color(int i) {
    uint32_t t = (uint32_t)i * 255U / (C80_GAUGE_KEYS - 1);
    uint32_t r = t < 128 ? 255U : (255U - t) * 2U;
    uint32_t g = t < 128 ? t * 2U : 255U;

    return (r << 16) | (g << 8);
}

/* Ambient wave phase of an LED at horizontal position x and row y (0..255 each) at time ms.
 * macOS: one colour cycle across the board, drifting left to right every 6 s.
 * Windows: the other way, tilted by row, every 8 s. */
static inline uint8_t c80_ambient_phase(uint32_t ms, uint8_t x, uint8_t y, int win) {
    if (win) {
        return (uint8_t)((ms % 8000U) * 256U / 8000U + x + y / 2U);
    }
    return (uint8_t)((ms % 6000U) * 256U / 6000U - x);
}
