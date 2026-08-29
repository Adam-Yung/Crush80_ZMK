/*
 * Crush80 RGB DIAGNOSTIC — Kscan disabled + CS reset test
 *
 * THIS FIRMWARE DISABLES THE KEYBOARD MATRIX.
 * The keyboard will NOT type. This is intentional — it isolates
 * PE0/PE1/PE2 from kscan interference to test if that's why LEDs fail.
 *
 * If LEDs light up with this firmware → kscan SPI corruption confirmed.
 * If LEDs still don't light up → hardware issue (wrong pins / no chip).
 */

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/logging/log.h>
#include <string.h>

#include "crush80_rgb.h"

LOG_MODULE_REGISTER(crush80_rgb, LOG_LEVEL_INF);

/* GPIO registers */
#define REG_GPIO_PE_OUT   (*(volatile uint8_t *)0x80140321)
#define REG_GPIO_PE_OEN   (*(volatile uint8_t *)0x80140322)
#define REG_GPIO_PE_IE    (*(volatile uint8_t *)0x80140323)
#define REG_GPIO_PC_OUT   (*(volatile uint8_t *)0x80140311)
#define REG_GPIO_PC_OEN   (*(volatile uint8_t *)0x80140312)
#define REG_GPIO_PC_IE    (*(volatile uint8_t *)0x80140313)

#define PE0_BIT  0x01  /* CS chip 0 */
#define PE1_BIT  0x02  /* CLK */
#define PE2_BIT  0x04  /* MOSI */
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
#define RGB_THREAD_PRIORITY 5  /* Higher priority than kscan */

static K_THREAD_STACK_DEFINE(rgb_stack, RGB_STACK_SIZE);
static struct k_thread rgb_thread_data;

/* ── SPI Bit-bang (Mode 0: CPOL=0, CPHA=0 — AW20216S default) ──── */

static void bb_write_byte(uint8_t data) {
    for (int i = 7; i >= 0; i--) {
        /* Set MOSI */
        if (data & (1 << i)) {
            REG_GPIO_PE_OUT |= PE2_BIT;
        } else {
            REG_GPIO_PE_OUT &= ~PE2_BIT;
        }
        __asm__ volatile("nop; nop;");
        /* Rising edge (data latched by AW20216S) */
        REG_GPIO_PE_OUT |= PE1_BIT;
        __asm__ volatile("nop; nop; nop; nop;");
        /* Falling edge */
        REG_GPIO_PE_OUT &= ~PE1_BIT;
        __asm__ volatile("nop; nop;");
    }
}

static void spi_reset_state_machine(uint8_t chip) {
    /*
     * Flush any garbage state in the AW20216S SPI receiver.
     * Toggle CS: HIGH → LOW → HIGH clears the internal bit counter.
     */
    if (chip == 0) {
        REG_GPIO_PE_OUT |= PE0_BIT;   /* CS0 HIGH */
    } else {
        REG_GPIO_PC_OUT |= PC0_BIT;   /* CS1 HIGH */
    }
    for (volatile int d = 0; d < 100; d++) {}
    if (chip == 0) {
        REG_GPIO_PE_OUT &= ~PE0_BIT;  /* CS0 LOW */
    } else {
        REG_GPIO_PC_OUT &= ~PC0_BIT;  /* CS1 LOW */
    }
    for (volatile int d = 0; d < 20; d++) {}
    if (chip == 0) {
        REG_GPIO_PE_OUT |= PE0_BIT;   /* CS0 HIGH — state machine reset */
    } else {
        REG_GPIO_PC_OUT |= PC0_BIT;   /* CS1 HIGH */
    }
    for (volatile int d = 0; d < 100; d++) {}
}

static void spi_write(uint8_t chip, uint8_t page, uint8_t reg,
                      const uint8_t *data, uint16_t len) {
    /* Ensure CLK is idle LOW (Mode 0) */
    REG_GPIO_PE_OUT &= ~PE1_BIT;
    REG_GPIO_PE_OUT &= ~PE2_BIT;

    /* Assert CS */
    if (chip == 0) {
        REG_GPIO_PE_OUT &= ~PE0_BIT;
    } else {
        REG_GPIO_PC_OUT &= ~PC0_BIT;
    }
    for (volatile int d = 0; d < 30; d++) {}

    /* Command byte + register + data */
    bb_write_byte(AW_CMD_WRITE(page));
    bb_write_byte(reg);
    for (uint16_t i = 0; i < len; i++) {
        bb_write_byte(data[i]);
    }

    for (volatile int d = 0; d < 30; d++) {}

    /* Deassert CS */
    REG_GPIO_PE_OUT |= PE0_BIT;
    REG_GPIO_PC_OUT |= PC0_BIT;
    for (volatile int d = 0; d < 50; d++) {}
}

static void spi_write_single(uint8_t chip, uint8_t page, uint8_t reg, uint8_t val) {
    spi_write(chip, page, reg, &val, 1);
}

/* ── Main diagnostic thread ──────────────────────────────────────── */

static void rgb_test_thread(void *p1, void *p2, void *p3) {
    ARG_UNUSED(p1); ARG_UNUSED(p2); ARG_UNUSED(p3);

    LOG_INF("=== LED TEST: KSCAN DISABLED, EXCLUSIVE PIN ACCESS ===");
    k_msleep(2000);

    /* Step 1: Disable kscan by taking over PE0/PE1/PE2 as outputs */
    LOG_INF("Step 1: Configuring PE0/PE1/PE2 as dedicated SPI outputs");
    REG_GPIO_PE_OEN &= ~(PE0_BIT | PE1_BIT | PE2_BIT);  /* Output enable */
    REG_GPIO_PE_IE &= ~(PE0_BIT | PE1_BIT | PE2_BIT);   /* Disable input */
    /* Set idle state: CS HIGH, CLK LOW, MOSI LOW */
    REG_GPIO_PE_OUT |= PE0_BIT;    /* CS0 HIGH */
    REG_GPIO_PE_OUT &= ~PE1_BIT;   /* CLK LOW (Mode 0 idle) */
    REG_GPIO_PE_OUT &= ~PE2_BIT;   /* MOSI LOW */

    /* Also set PC0 as output for CS1 */
    REG_GPIO_PC_OEN &= ~PC0_BIT;
    REG_GPIO_PC_OUT |= PC0_BIT;    /* CS1 HIGH */

    /* Step 2: Power on LED rail (PC2 HIGH) */
    LOG_INF("Step 2: Powering LED rail (PC2 HIGH)");
    REG_GPIO_PC_IE &= ~PC2_BIT;
    REG_GPIO_PC_OEN &= ~PC2_BIT;
    REG_GPIO_PC_OUT |= PC2_BIT;
    k_msleep(100);  /* Let power stabilize fully */

    /* Step 3: Reset SPI state machines on both chips */
    LOG_INF("Step 3: Resetting AW20216S SPI state machines");
    spi_reset_state_machine(0);
    spi_reset_state_machine(1);
    k_msleep(10);

    /* Step 4: Initialize AW20216S chips */
    LOG_INF("Step 4: Initializing AW20216S (software reset + enable)");
    for (uint8_t chip = 0; chip < 2; chip++) {
        spi_reset_state_machine(chip);

        /* Software reset */
        spi_write_single(chip, AW_PAGE_CONFIG, AW_REG_RSTN, AW_RESET_VAL);
        k_msleep(5);

        /* Enable chip */
        spi_write_single(chip, AW_PAGE_CONFIG, AW_REG_GCR, 0x01);
        k_msleep(1);

        /* Global current max */
        spi_write_single(chip, AW_PAGE_CONFIG, AW_REG_GCCR, 0xFF);

        /* All scaling to max */
        uint8_t buf[AW_PWM_CHANNELS];
        memset(buf, 0xFF, sizeof(buf));
        spi_write(chip, AW_PAGE_SCALE, 0x00, buf, AW_PWM_CHANNELS);

        LOG_INF("  Chip %d initialized", chip);
    }

    /* Step 5: Set all LEDs to full white */
    LOG_INF("Step 5: Setting all PWM channels to 0xFF (full white)");
    for (uint8_t chip = 0; chip < 2; chip++) {
        uint8_t buf[AW_PWM_CHANNELS];
        memset(buf, 0xFF, sizeof(buf));
        spi_write(chip, AW_PAGE_PWM, 0x00, buf, AW_PWM_CHANNELS);
    }

    LOG_INF("=== DONE. If LEDs are ON → kscan interference was the problem.");
    LOG_INF("=== If LEDs are OFF → hardware issue (wrong pins or no chip).");
    LOG_INF("=== KEYBOARD WILL NOT TYPE (kscan disabled). Reflash to restore.");

    /* Keep refreshing PWM every 100ms */
    while (1) {
        for (uint8_t chip = 0; chip < 2; chip++) {
            uint8_t buf[AW_PWM_CHANNELS];
            memset(buf, 0xFF, sizeof(buf));
            spi_write(chip, AW_PAGE_PWM, 0x00, buf, AW_PWM_CHANNELS);
        }
        k_msleep(100);
    }
}

/* ── Stubs ───────────────────────────────────────────────────────── */
void crush80_rgb_set_led(uint8_t index, uint8_t r, uint8_t g, uint8_t b) {}
void crush80_rgb_set_all(uint8_t r, uint8_t g, uint8_t b) {}
void crush80_rgb_toggle(void) {}
bool crush80_rgb_is_on(void) { return true; }

/* ── System init ─────────────────────────────────────────────────── */

static int crush80_rgb_sys_init(void) {
    k_thread_create(&rgb_thread_data, rgb_stack,
                    K_THREAD_STACK_SIZEOF(rgb_stack),
                    rgb_test_thread, NULL, NULL, NULL,
                    RGB_THREAD_PRIORITY, 0, K_NO_WAIT);
    k_thread_name_set(&rgb_thread_data, "rgb_test");
    LOG_INF("crush80_rgb: KSCAN-DISABLED LED TEST");
    return 0;
}

SYS_INIT(crush80_rgb_sys_init, APPLICATION, 99);
