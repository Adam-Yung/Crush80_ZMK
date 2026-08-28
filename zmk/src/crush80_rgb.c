/*
 * Crush80 RGB DIAGNOSTIC — Cycles through all SPI modes with different colors.
 * If any LED lights up, the color tells us which mode is correct.
 *
 * Color → Mode mapping:
 *   RED    = SPI Mode 0 (CPOL=0, CPHA=0), normal pins
 *   GREEN  = SPI Mode 1 (CPOL=0, CPHA=1), normal pins
 *   BLUE   = SPI Mode 2 (CPOL=1, CPHA=0), normal pins
 *   WHITE  = SPI Mode 3 (CPOL=1, CPHA=1), normal pins
 *   PURPLE = Mode 0, pins swapped (PE1=MOSI, PE2=CLK)
 *   YELLOW = Mode 0, PC2 inverted (drive LOW instead of HIGH)
 *   CYAN   = Mode 3, PC2 inverted
 *
 * Each mode runs for 5 seconds, then cycles to next.
 * Uses GPIO bit-bang (proven to physically drive the pins via kscan evidence).
 */

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <string.h>

#include "crush80_rgb.h"

LOG_MODULE_REGISTER(crush80_rgb, LOG_LEVEL_INF);

/* GPIO registers */
#define REG_GPIO_PE_OUT   (*(volatile uint8_t *)0x80140321)
#define REG_GPIO_PC_OUT   (*(volatile uint8_t *)0x80140311)
#define REG_GPIO_PC_OEN   (*(volatile uint8_t *)0x80140312)
#define REG_GPIO_PC_IE    (*(volatile uint8_t *)0x80140313)

#define PE0_BIT  0x01  /* CS chip 0 */
#define PE1_BIT  0x02  /* CLK (or MOSI if swapped) */
#define PE2_BIT  0x04  /* MOSI (or CLK if swapped) */
#define PC0_BIT  0x01  /* CS chip 1 */
#define PC2_BIT  0x04  /* LED power MOSFET */

/* AW20216S */
#define AW_CMD_WRITE(page)  (0xA0 | (((page) & 0x07) << 1))
#define AW_PAGE_CONFIG  0
#define AW_PAGE_PWM     1
#define AW_PAGE_SCALE   2
#define AW_REG_GCR      0x00
#define AW_REG_GCCR     0x01
#define AW_REG_RSTN     0x2F
#define AW_RESET_VAL    0xAE
#define AW_PWM_CHANNELS 216

/* Thread */
#define RGB_STACK_SIZE     2048
#define RGB_THREAD_PRIORITY 10

static K_THREAD_STACK_DEFINE(rgb_stack, RGB_STACK_SIZE);
static struct k_thread rgb_thread_data;

/* Current mode config */
static uint8_t clk_bit = PE1_BIT;
static uint8_t mosi_bit = PE2_BIT;
static bool cpol = false;  /* false=idle LOW, true=idle HIGH */
static bool cpha = false;  /* false=sample on first edge, true=sample on second edge */

/* ── Bit-bang SPI (mode-aware) ───────────────────────────────────── */

static inline void bb_write_byte(uint8_t data) {
    for (int i = 7; i >= 0; i--) {
        if (cpha) {
            /* CPHA=1: toggle clock FIRST, then set data, then toggle back */
            if (cpol) {
                REG_GPIO_PE_OUT &= ~clk_bit;  /* first edge (falling for CPOL=1) */
            } else {
                REG_GPIO_PE_OUT |= clk_bit;   /* first edge (rising for CPOL=0) */
            }
            /* Set MOSI */
            if (data & (1 << i)) {
                REG_GPIO_PE_OUT |= mosi_bit;
            } else {
                REG_GPIO_PE_OUT &= ~mosi_bit;
            }
            __asm__ volatile("nop; nop; nop; nop;");
            /* Second edge (data latched here) */
            if (cpol) {
                REG_GPIO_PE_OUT |= clk_bit;   /* back to idle HIGH */
            } else {
                REG_GPIO_PE_OUT &= ~clk_bit;  /* back to idle LOW */
            }
            __asm__ volatile("nop; nop;");
        } else {
            /* CPHA=0: set data, then first clock edge (data latched), then back */
            /* Set MOSI */
            if (data & (1 << i)) {
                REG_GPIO_PE_OUT |= mosi_bit;
            } else {
                REG_GPIO_PE_OUT &= ~mosi_bit;
            }
            __asm__ volatile("nop; nop;");
            /* First edge (data latched here) */
            if (cpol) {
                REG_GPIO_PE_OUT &= ~clk_bit;  /* falling edge for CPOL=1 */
            } else {
                REG_GPIO_PE_OUT |= clk_bit;   /* rising edge for CPOL=0 */
            }
            __asm__ volatile("nop; nop; nop; nop;");
            /* Back to idle */
            if (cpol) {
                REG_GPIO_PE_OUT |= clk_bit;   /* idle HIGH */
            } else {
                REG_GPIO_PE_OUT &= ~clk_bit;  /* idle LOW */
            }
            __asm__ volatile("nop; nop;");
        }
    }
}

static void bb_spi_write(uint8_t chip, uint8_t page, uint8_t reg,
                         const uint8_t *data, uint16_t len) {
    /* Set CLK to idle state */
    if (cpol) {
        REG_GPIO_PE_OUT |= clk_bit;
    } else {
        REG_GPIO_PE_OUT &= ~clk_bit;
    }
    REG_GPIO_PE_OUT &= ~mosi_bit;

    /* Assert CS */
    if (chip == 0) {
        REG_GPIO_PE_OUT &= ~PE0_BIT;
    } else {
        REG_GPIO_PC_OUT &= ~PC0_BIT;
    }
    for (volatile int d = 0; d < 20; d++) {}

    /* Send command + register + data */
    bb_write_byte(AW_CMD_WRITE(page));
    bb_write_byte(reg);
    for (uint16_t i = 0; i < len; i++) {
        bb_write_byte(data[i]);
    }

    for (volatile int d = 0; d < 20; d++) {}

    /* Deassert CS */
    REG_GPIO_PE_OUT |= PE0_BIT;
    REG_GPIO_PC_OUT |= PC0_BIT;

    /* Restore pins to HIGH (kscan idle) */
    REG_GPIO_PE_OUT |= (PE1_BIT | PE2_BIT);

    for (volatile int d = 0; d < 30; d++) {}
}

static void bb_spi_write_single(uint8_t chip, uint8_t page, uint8_t reg, uint8_t val) {
    bb_spi_write(chip, page, reg, &val, 1);
}

/* ── AW20216S init + set color ─────────────────────────────────── */

static void aw_init_and_set_color(uint8_t r, uint8_t g, uint8_t b) {
    unsigned int key = irq_lock();

    /* Init both chips */
    for (uint8_t chip = 0; chip < 2; chip++) {
        bb_spi_write_single(chip, AW_PAGE_CONFIG, AW_REG_RSTN, AW_RESET_VAL);
        k_busy_wait(2000);
        bb_spi_write_single(chip, AW_PAGE_CONFIG, AW_REG_GCR, 0x01);
        bb_spi_write_single(chip, AW_PAGE_CONFIG, AW_REG_GCCR, 0xFF);

        /* Scaling all max */
        uint8_t buf[AW_PWM_CHANNELS];
        memset(buf, 0xFF, sizeof(buf));
        bb_spi_write(chip, AW_PAGE_SCALE, 0x00, buf, AW_PWM_CHANNELS);

        /* Set PWM to requested color pattern (repeating R,G,B) */
        for (int i = 0; i < AW_PWM_CHANNELS; i += 3) {
            buf[i] = r;
            buf[i+1] = (i+1 < AW_PWM_CHANNELS) ? g : 0;
            buf[i+2] = (i+2 < AW_PWM_CHANNELS) ? b : 0;
        }
        bb_spi_write(chip, AW_PAGE_PWM, 0x00, buf, AW_PWM_CHANNELS);
    }

    irq_unlock(key);
}

/* ── Main diagnostic thread ──────────────────────────────────────── */

static void rgb_diag_thread(void *p1, void *p2, void *p3) {
    ARG_UNUSED(p1); ARG_UNUSED(p2); ARG_UNUSED(p3);

    k_msleep(3000);
    LOG_INF("=== RGB DIAGNOSTIC: cycling all SPI modes ===");

    /* Power on PC2 (try HIGH first) */
    REG_GPIO_PC_IE &= ~PC2_BIT;
    REG_GPIO_PC_OEN &= ~PC2_BIT;
    REG_GPIO_PC_OUT |= PC2_BIT;
    k_msleep(50);
    LOG_INF("PC2 driven HIGH");

    int cycle = 0;
    while (1) {
        int mode = cycle % 7;
        cycle++;

        /* Configure mode */
        switch (mode) {
            case 0: /* RED = Mode 0, normal pins, PC2 HIGH */
                cpol = false; cpha = false;
                clk_bit = PE1_BIT; mosi_bit = PE2_BIT;
                REG_GPIO_PC_OUT |= PC2_BIT;
                LOG_INF("[%d] RED: Mode0 CPOL=0 CPHA=0, PE1=CLK PE2=MOSI, PC2=HIGH", cycle);
                aw_init_and_set_color(0xFF, 0x00, 0x00);
                break;

            case 1: /* GREEN = Mode 1, normal pins, PC2 HIGH */
                cpol = false; cpha = true;
                clk_bit = PE1_BIT; mosi_bit = PE2_BIT;
                REG_GPIO_PC_OUT |= PC2_BIT;
                LOG_INF("[%d] GREEN: Mode1 CPOL=0 CPHA=1, PE1=CLK PE2=MOSI, PC2=HIGH", cycle);
                aw_init_and_set_color(0x00, 0xFF, 0x00);
                break;

            case 2: /* BLUE = Mode 2, normal pins, PC2 HIGH */
                cpol = true; cpha = false;
                clk_bit = PE1_BIT; mosi_bit = PE2_BIT;
                REG_GPIO_PC_OUT |= PC2_BIT;
                LOG_INF("[%d] BLUE: Mode2 CPOL=1 CPHA=0, PE1=CLK PE2=MOSI, PC2=HIGH", cycle);
                aw_init_and_set_color(0x00, 0x00, 0xFF);
                break;

            case 3: /* WHITE = Mode 3, normal pins, PC2 HIGH */
                cpol = true; cpha = true;
                clk_bit = PE1_BIT; mosi_bit = PE2_BIT;
                REG_GPIO_PC_OUT |= PC2_BIT;
                LOG_INF("[%d] WHITE: Mode3 CPOL=1 CPHA=1, PE1=CLK PE2=MOSI, PC2=HIGH", cycle);
                aw_init_and_set_color(0xFF, 0xFF, 0xFF);
                break;

            case 4: /* PURPLE = Mode 0, SWAPPED pins, PC2 HIGH */
                cpol = false; cpha = false;
                clk_bit = PE2_BIT; mosi_bit = PE1_BIT;  /* SWAPPED! */
                REG_GPIO_PC_OUT |= PC2_BIT;
                LOG_INF("[%d] PURPLE: Mode0 SWAPPED PE2=CLK PE1=MOSI, PC2=HIGH", cycle);
                aw_init_and_set_color(0xFF, 0x00, 0xFF);
                break;

            case 5: /* YELLOW = Mode 0, normal pins, PC2 LOW (inverted power) */
                cpol = false; cpha = false;
                clk_bit = PE1_BIT; mosi_bit = PE2_BIT;
                REG_GPIO_PC_OUT &= ~PC2_BIT;  /* INVERTED! */
                LOG_INF("[%d] YELLOW: Mode0 normal pins, PC2=LOW (inverted)", cycle);
                k_msleep(50);
                aw_init_and_set_color(0xFF, 0xFF, 0x00);
                break;

            case 6: /* CYAN = Mode 3, normal pins, PC2 LOW (inverted power) */
                cpol = true; cpha = true;
                clk_bit = PE1_BIT; mosi_bit = PE2_BIT;
                REG_GPIO_PC_OUT &= ~PC2_BIT;  /* INVERTED! */
                LOG_INF("[%d] CYAN: Mode3 normal pins, PC2=LOW (inverted)", cycle);
                k_msleep(50);
                aw_init_and_set_color(0x00, 0xFF, 0xFF);
                break;
        }

        /* Hold for 5 seconds before next mode */
        k_msleep(5000);
    }
}

/* ── Stubs for public API (required by header) ───────────────────── */
void crush80_rgb_set_led(uint8_t index, uint8_t r, uint8_t g, uint8_t b) {}
void crush80_rgb_set_all(uint8_t r, uint8_t g, uint8_t b) {}
void crush80_rgb_toggle(void) {}
bool crush80_rgb_is_on(void) { return true; }

/* ── System init ─────────────────────────────────────────────────── */

static int crush80_rgb_sys_init(void) {
    k_thread_create(&rgb_thread_data, rgb_stack,
                    K_THREAD_STACK_SIZEOF(rgb_stack),
                    rgb_diag_thread, NULL, NULL, NULL,
                    RGB_THREAD_PRIORITY, 0, K_NO_WAIT);
    k_thread_name_set(&rgb_thread_data, "rgb_diag");
    LOG_INF("crush80_rgb: DIAGNOSTIC MODE — cycling SPI modes");
    return 0;
}

SYS_INIT(crush80_rgb_sys_init, APPLICATION, 99);
