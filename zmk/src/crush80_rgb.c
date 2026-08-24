/*
 * Crush80 RGB LED Driver — AW20216S via GPIO bit-bang SPI
 *
 * PE0 = CS chip 0 (active low)  — shared with kscan column 0
 * PE1 = CLK                     — shared with kscan column 1
 * PE2 = MOSI                    — shared with kscan column 2
 * PC0 = CS chip 1 (active low)  — shared with kscan column 13
 * PC2 = LED power MOSFET (active high) — dedicated, not kscan
 *
 * Strategy: kscan configures PE0/PE1/PE2/PC0 as outputs (col2row columns,
 * driven HIGH when idle, driven LOW during scan). We reuse these pins for
 * SPI under irq_lock (preventing kscan from scanning during our ~4ms frame).
 * We only change the OUT register — never touch OEN/IE/direction.
 * After SPI, we restore all pins to HIGH (kscan idle state).
 */

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <string.h>

#include "crush80_rgb.h"

LOG_MODULE_REGISTER(crush80_rgb, LOG_LEVEL_INF);

/* B91 GPIO register addresses (direct memory-mapped) */
#define REG_GPIO_PE_OUT    (*(volatile uint8_t *)0x80140321)
#define REG_GPIO_PE_OEN    (*(volatile uint8_t *)0x80140322)

#define REG_GPIO_PC_OUT    (*(volatile uint8_t *)0x80140311)
#define REG_GPIO_PC_OEN    (*(volatile uint8_t *)0x80140312)
#define REG_GPIO_PC_IE     (*(volatile uint8_t *)0x80140313)
#define REG_GPIO_PC_GPIO   (*(volatile uint8_t *)0x80140310)

/* Pin bitmasks */
#define PE0_BIT  0x01  /* CS chip 0 */
#define PE1_BIT  0x02  /* CLK */
#define PE2_BIT  0x04  /* MOSI */
#define PC0_BIT  0x01  /* CS chip 1 */
#define PC2_BIT  0x04  /* LED power MOSFET */

/* AW20216S register pages */
#define AW_PAGE_FUNC   0xC0
#define AW_PAGE_PWM    0xC1
#define AW_PAGE_SCALE  0xC2

/* AW20216S function registers */
#define AW_REG_CONFIG   0x00
#define AW_REG_GCC      0x01

/* SPI address byte: bit7=0 write, bit7=1 read */
#define AW_WRITE(page)  ((page) & 0x7F)
#define AW_ADDR(reg)    (reg)

/* Frame buffer: 3 bytes (R,G,B) per LED */
static uint8_t led_pwm[CRUSH80_LED_COUNT_TOTAL * 3];
static bool rgb_enabled = true;
static bool rgb_initialized;

/* Thread stack and scheduling */
#define RGB_STACK_SIZE 1024
#define RGB_THREAD_PRIORITY 10
#define RGB_REFRESH_MS 33  /* ~30 Hz */

static K_THREAD_STACK_DEFINE(rgb_stack, RGB_STACK_SIZE);
static struct k_thread rgb_thread_data;

/* ── GPIO pin management ─────────────────────────────────────────────── */

static inline void spi_pins_acquire(void) {
    /*
     * The kscan driver toggles OEN per-scan: columns are in INPUT mode (OEN=1)
     * between scans, and briefly set to OUTPUT (OEN=0) during each column's
     * scan slot. Since we hold irq_lock, kscan can't run, so columns are in
     * input mode. We must enable output (OEN=0) to actually drive the SPI pins.
     */
    REG_GPIO_PE_OEN &= ~(PE0_BIT | PE1_BIT | PE2_BIT);  /* enable output */
    REG_GPIO_PC_OEN &= ~PC0_BIT;                         /* enable output */

    /* SPI idle state */
    REG_GPIO_PE_OUT |= PE0_BIT;   /* CS0 high (deasserted) */
    REG_GPIO_PE_OUT &= ~PE1_BIT;  /* CLK low */
    REG_GPIO_PE_OUT &= ~PE2_BIT;  /* MOSI low */
    REG_GPIO_PC_OUT |= PC0_BIT;   /* CS1 high (deasserted) */
}

static inline void spi_pins_release(void) {
    /*
     * Restore all SPI pins to HIGH first (safe state for kscan active-low).
     * Then disable output (OEN=1) — kscan expects columns in input mode
     * between scans and will re-enable output during its own scan slots.
     */
    REG_GPIO_PE_OUT |= (PE0_BIT | PE1_BIT | PE2_BIT);  /* all HIGH */
    REG_GPIO_PC_OUT |= PC0_BIT;                         /* PC0 HIGH */

    REG_GPIO_PE_OEN |= (PE0_BIT | PE1_BIT | PE2_BIT);  /* disable output (input mode) */
    REG_GPIO_PC_OEN |= PC0_BIT;                         /* disable output (input mode) */
}

/* ── SPI bit-bang ────────────────────────────────────────────────────── */

static inline void spi_write_byte(uint8_t data) {
    for (int i = 7; i >= 0; i--) {
        if (data & (1 << i)) {
            REG_GPIO_PE_OUT |= PE2_BIT;
        } else {
            REG_GPIO_PE_OUT &= ~PE2_BIT;
        }
        REG_GPIO_PE_OUT |= PE1_BIT;   /* CLK high — data latched on rising edge */
        REG_GPIO_PE_OUT &= ~PE1_BIT;  /* CLK low */
    }
}

static void aw_write_reg(uint8_t chip, uint8_t page, uint8_t reg,
                         const uint8_t *data, uint8_t len) {
    /* Select page */
    if (chip == 0) {
        REG_GPIO_PE_OUT &= ~PE0_BIT;  /* CS0 low */
    } else {
        REG_GPIO_PC_OUT &= ~PC0_BIT;  /* CS1 low */
    }
    spi_write_byte(AW_WRITE(page));
    spi_write_byte(reg);
    for (uint8_t i = 0; i < len; i++) {
        spi_write_byte(data[i]);
    }
    REG_GPIO_PE_OUT |= PE0_BIT;   /* CS0 high */
    REG_GPIO_PC_OUT |= PC0_BIT;   /* CS1 high */
}

static void aw_write_reg_single(uint8_t chip, uint8_t page,
                                uint8_t reg, uint8_t val) {
    aw_write_reg(chip, page, reg, &val, 1);
}

/* ── AW20216S initialization ─────────────────────────────────────────── */

static void aw_chip_init(uint8_t chip) {
    /* Software reset (config reg bit 0) */
    aw_write_reg_single(chip, AW_PAGE_FUNC, AW_REG_CONFIG, 0x01);
    k_busy_wait(2000);  /* 2ms for reset */

    /* Enable chip: CHIPEN=1 (bit 0 of config after reset) */
    aw_write_reg_single(chip, AW_PAGE_FUNC, AW_REG_CONFIG, 0x01);

    /* Set global current control to max (0xFF) */
    aw_write_reg_single(chip, AW_PAGE_FUNC, AW_REG_GCC, 0xFF);

    /* Enable all 216 channels via scaling page (set all to 0xFF) */
    uint8_t all_on[18];
    memset(all_on, 0xFF, sizeof(all_on));
    for (uint8_t sw = 0; sw < 12; sw++) {
        aw_write_reg(chip, AW_PAGE_SCALE, sw * 18, all_on, 18);
    }

    /* Clear all PWM values */
    uint8_t all_off[18];
    memset(all_off, 0x00, sizeof(all_off));
    for (uint8_t sw = 0; sw < 12; sw++) {
        aw_write_reg(chip, AW_PAGE_PWM, sw * 18, all_off, 18);
    }
}

/* ── LED power control ───────────────────────────────────────────────── */

static void led_power_on(void) {
    /* PC2 is the LED power MOSFET gate — set as output, drive high */
    REG_GPIO_PC_IE &= ~PC2_BIT;
    REG_GPIO_PC_GPIO |= PC2_BIT;
    REG_GPIO_PC_OEN &= ~PC2_BIT;
    REG_GPIO_PC_OUT |= PC2_BIT;
    k_msleep(5);  /* Let power rail stabilize */
}

static void led_power_off(void) {
    REG_GPIO_PC_OUT &= ~PC2_BIT;
}

/* ── Frame update ────────────────────────────────────────────────────── */

static void rgb_update_frame(void) {
    if (!rgb_enabled || !rgb_initialized) {
        return;
    }

    unsigned int key = irq_lock();

    spi_pins_acquire();

    /*
     * Write PWM data to chip 0 (LEDs 0-90, 91 LEDs × 3 channels = 273 bytes).
     * AW20216S has 12 SW rows × 18 CS columns = 216 channels per chip.
     * We write in 18-byte chunks per SW row.
     */
    for (uint8_t sw = 0; sw < 12; sw++) {
        uint8_t buf[18];
        uint16_t base = sw * 18;

        for (uint8_t cs = 0; cs < 18; cs++) {
            uint16_t ch_idx = base + cs;
            if (ch_idx < CRUSH80_LED_COUNT_CHIP0 * 3) {
                buf[cs] = led_pwm[ch_idx];
            } else {
                buf[cs] = 0;
            }
        }
        aw_write_reg(0, AW_PAGE_PWM, sw * 18, buf, 18);
    }

    /* Write PWM data to chip 1 (LEDs 91-153, underglow) */
    for (uint8_t sw = 0; sw < 12; sw++) {
        uint8_t buf[18];
        uint16_t base = sw * 18;

        for (uint8_t cs = 0; cs < 18; cs++) {
            uint16_t ch_idx = base + cs;
            uint16_t led_offset = CRUSH80_LED_COUNT_CHIP0 * 3 + ch_idx;
            if (ch_idx < CRUSH80_LED_COUNT_CHIP1 * 3) {
                buf[cs] = led_pwm[led_offset];
            } else {
                buf[cs] = 0;
            }
        }
        aw_write_reg(1, AW_PAGE_PWM, sw * 18, buf, 18);
    }

    spi_pins_release();

    irq_unlock(key);
}

/* ── Public API ──────────────────────────────────────────────────────── */

void crush80_rgb_set_led(uint8_t index, uint8_t r, uint8_t g, uint8_t b) {
    if (index >= CRUSH80_LED_COUNT_TOTAL) {
        return;
    }
    uint16_t offset = (uint16_t)index * 3;
    led_pwm[offset + 0] = r;
    led_pwm[offset + 1] = g;
    led_pwm[offset + 2] = b;
}

void crush80_rgb_set_all(uint8_t r, uint8_t g, uint8_t b) {
    for (uint8_t i = 0; i < CRUSH80_LED_COUNT_TOTAL; i++) {
        crush80_rgb_set_led(i, r, g, b);
    }
}

void crush80_rgb_toggle(void) {
    rgb_enabled = !rgb_enabled;
    if (!rgb_enabled) {
        memset(led_pwm, 0, sizeof(led_pwm));
        rgb_update_frame();
        led_power_off();
    } else {
        led_power_on();
    }
}

bool crush80_rgb_is_on(void) {
    return rgb_enabled;
}

/* ── Background thread ───────────────────────────────────────────────── */

static void rgb_thread_fn(void *p1, void *p2, void *p3) {
    ARG_UNUSED(p1);
    ARG_UNUSED(p2);
    ARG_UNUSED(p3);

    /* Wait for system init to complete */
    k_msleep(2000);

    LOG_INF("crush80_rgb: starting init");

    /* Power on LED rail */
    led_power_on();

    /* Initialize both AW20216S chips */
    unsigned int key = irq_lock();
    spi_pins_acquire();
    aw_chip_init(0);
    aw_chip_init(1);
    spi_pins_release();
    irq_unlock(key);

    rgb_initialized = true;
    LOG_INF("crush80_rgb: init complete, setting test color");

    /* Initial test: set all per-key LEDs to warm white at low brightness */
    for (uint8_t i = 0; i < CRUSH80_LED_COUNT_CHIP0; i++) {
        crush80_rgb_set_led(i, 40, 30, 15);
    }
    /* Underglow: dim warm white */
    for (uint8_t i = CRUSH80_LED_COUNT_CHIP0; i < CRUSH80_LED_COUNT_TOTAL; i++) {
        crush80_rgb_set_led(i, 25, 20, 10);
    }

    /* Main refresh loop */
    while (1) {
        if (rgb_enabled) {
            rgb_update_frame();
        }
        k_msleep(RGB_REFRESH_MS);
    }
}

/* ── System init ─────────────────────────────────────────────────────── */

static int crush80_rgb_sys_init(void) {
    k_thread_create(&rgb_thread_data, rgb_stack,
                    K_THREAD_STACK_SIZEOF(rgb_stack),
                    rgb_thread_fn, NULL, NULL, NULL,
                    RGB_THREAD_PRIORITY, 0, K_NO_WAIT);
    k_thread_name_set(&rgb_thread_data, "crush80_rgb");

    LOG_INF("crush80_rgb: thread created");
    return 0;
}

SYS_INIT(crush80_rgb_sys_init, APPLICATION, 99);
