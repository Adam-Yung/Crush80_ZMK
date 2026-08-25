/*
 * Crush80 RGB LED Driver — AW20216S via HSPI Hardware
 *
 * Uses the B91's HSPI hardware peripheral to communicate with the AW20216S.
 * PE1 (CLK) and PE2 (MOSI) are temporarily switched from GPIO mode (kscan)
 * to HSPI alternate function mode during each SPI transfer, then restored.
 *
 * Pin assignments:
 *   PE0 = CS chip 0 (GPIO manual, active low) — shared with kscan col 0
 *   PE1 = HSPI CLK (FUNC_C alt) — shared with kscan col 1
 *   PE2 = HSPI MOSI (FUNC_C alt) — shared with kscan col 2
 *   PC0 = CS chip 1 (GPIO manual, active low) — shared with kscan col 13
 *   PC2 = LED power MOSFET (GPIO, active high) — dedicated
 *
 * Safety: all pin switching happens under irq_lock (kscan cannot scan).
 * The thread starts 2s after boot (USB/BLE already up).
 * If anything goes wrong, MCUmgr is still accessible for recovery.
 */

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <string.h>

#include "crush80_rgb.h"

LOG_MODULE_REGISTER(crush80_rgb, LOG_LEVEL_INF);

/* ── B91 GPIO registers ──────────────────────────────────────────────── */

#define REG_GPIO_PE_OUT   (*(volatile uint8_t *)0x80140321)
#define REG_GPIO_PE_OEN   (*(volatile uint8_t *)0x80140322)
#define REG_GPIO_PE_IE    (*(volatile uint8_t *)0x80140323)
#define REG_GPIO_PE_FUNC  (*(volatile uint8_t *)0x80140326)  /* GPIO function: 1=GPIO, 0=alt */

#define REG_GPIO_PC_OUT   (*(volatile uint8_t *)0x80140311)
#define REG_GPIO_PC_OEN   (*(volatile uint8_t *)0x80140312)
#define REG_GPIO_PC_IE    (*(volatile uint8_t *)0x80140313)

/* Pin bitmasks */
#define PE0_BIT  0x01  /* CS chip 0 */
#define PE1_BIT  0x02  /* HSPI CLK */
#define PE2_BIT  0x04  /* HSPI MOSI */
#define PC0_BIT  0x01  /* CS chip 1 */
#define PC2_BIT  0x04  /* LED power MOSFET */

/* ── HSPI hardware registers (base 0x81FFFFC0) ───────────────────────── */

#define HSPI_BASE          0x81FFFFC0

#define REG_HSPI_MODE0     (*(volatile uint8_t *)(HSPI_BASE + 0x00))
#define REG_HSPI_MODE1     (*(volatile uint8_t *)(HSPI_BASE + 0x01))  /* clock divider */
#define REG_HSPI_MODE2     (*(volatile uint8_t *)(HSPI_BASE + 0x02))
#define REG_HSPI_TX_CNT0   (*(volatile uint8_t *)(HSPI_BASE + 0x03))
#define REG_HSPI_TX_CNT1   (*(volatile uint8_t *)(HSPI_BASE + 0x20))  /* different offset for HSPI! */
#define REG_HSPI_TX_CNT2   (*(volatile uint8_t *)(HSPI_BASE + 0x21))
#define REG_HSPI_TRANS0    (*(volatile uint8_t *)(HSPI_BASE + 0x05))
#define REG_HSPI_TRANS1    (*(volatile uint8_t *)(HSPI_BASE + 0x06))  /* cmd reg = TRIGGER */
#define REG_HSPI_TRANS2    (*(volatile uint8_t *)(HSPI_BASE + 0x07))
#define REG_HSPI_DATA(n)   (*(volatile uint8_t *)(HSPI_BASE + 0x08 + (n)))
#define REG_HSPI_FIFO_NUM  (*(volatile uint8_t *)(HSPI_BASE + 0x0C))
#define REG_HSPI_FIFO_ST   (*(volatile uint8_t *)(HSPI_BASE + 0x0D))
#define REG_HSPI_IRQ_ST    (*(volatile uint8_t *)(HSPI_BASE + 0x0E))
#define REG_HSPI_STATUS    (*(volatile uint8_t *)(HSPI_BASE + 0x0F))
#define REG_HSPI_XIP_CTRL  (*(volatile uint8_t *)(HSPI_BASE + 0x14))

/* HSPI clock enable */
#define REG_CLK_EN0        (*(volatile uint8_t *)0x801401E4)
#define CLK0_HSPI_EN       BIT(0)

/* HSPI MODE0 bits */
#define HSPI_MASTER_MODE   BIT(7)

/* HSPI FIFO_ST bits */
#define HSPI_TXF_FULL      BIT(6)

/* HSPI STATUS bits */
#define HSPI_BUSY          BIT(7)

/* ── AW20216S protocol ───────────────────────────────────────────────── */

/*
 * Command byte: [1010][page(3 bits)][W/R]
 * Page 0 = config, Page 1 = PWM, Page 2 = scaling
 */
#define AW_CMD_WRITE(page)  (0xA0 | (((page) & 0x07) << 1))

#define AW_PAGE_CONFIG  0
#define AW_PAGE_PWM     1
#define AW_PAGE_SCALE   2

#define AW_REG_GCR      0x00  /* Global config: bit0=CHIPEN */
#define AW_REG_GCCR     0x01  /* Global current 0x00-0xFF */
#define AW_REG_RSTN     0x2F  /* Software reset: write 0xAE */
#define AW_RESET_VAL    0xAE

#define AW_PWM_CHANNELS 216

/* ── Frame buffer ────────────────────────────────────────────────────── */

static uint8_t chip0_pwm[AW_PWM_CHANNELS];
static uint8_t chip1_pwm[AW_PWM_CHANNELS];
static bool rgb_enabled = true;
static bool rgb_initialized;

/* Thread */
#define RGB_STACK_SIZE     1536
#define RGB_THREAD_PRIORITY 10
#define RGB_REFRESH_MS     33

static K_THREAD_STACK_DEFINE(rgb_stack, RGB_STACK_SIZE);
static struct k_thread rgb_thread_data;

/* ── PE function mux register ────────────────────────────────────────── */

/*
 * reg_gpio_pe_fuc_l at 0x80140350 contains 2-bit function select per pin:
 *   PE0=[1:0], PE1=[3:2], PE2=[5:4], PE3=[7:6]
 * Values: 0=FUNC_A, 1=FUNC_B, 2=FUNC_C (HSPI), 3=FUNC_D
 *
 * Just clearing the GPIO function bit (0x80140326) enters alt-mode,
 * but WITHOUT the correct mux value the pin routes to FUNC_A (I2C), not HSPI.
 */
#define REG_GPIO_PE_FUC_L  (*(volatile uint8_t *)0x80140350)

#define PE1_FUNC_SHIFT  2
#define PE2_FUNC_SHIFT  4
#define PE1_FUNC_MASK   (0x03 << PE1_FUNC_SHIFT)  /* bits [3:2] */
#define PE2_FUNC_MASK   (0x03 << PE2_FUNC_SHIFT)  /* bits [5:4] */
#define FUNC_C_VAL      0x02

/* ── Pin management ──────────────────────────────────────────────────── */

static inline void pins_to_hspi(void) {
    /* 1. Set PE1/PE2 func_mux to FUNC_C (HSPI CLK / MOSI) */
    REG_GPIO_PE_FUC_L = (REG_GPIO_PE_FUC_L & ~(PE1_FUNC_MASK | PE2_FUNC_MASK))
                        | (FUNC_C_VAL << PE1_FUNC_SHIFT)
                        | (FUNC_C_VAL << PE2_FUNC_SHIFT);
    /* 2. Disable GPIO function → enter alt mode */
    REG_GPIO_PE_FUNC &= ~(PE1_BIT | PE2_BIT);
    /* 3. Enable input (required for HSPI output driver per SDK convention) */
    REG_GPIO_PE_IE |= (PE1_BIT | PE2_BIT);
    /* 4. Clear OEN (output enable) — stock firmware does this explicitly.
     * On B91, OEN=0 means output driver active. Even in alt-function mode,
     * the pin won't drive unless OEN is cleared. */
    REG_GPIO_PE_OEN &= ~(PE1_BIT | PE2_BIT);
}

static inline void pins_to_gpio(void) {
    /* Restore PE1/PE2 to GPIO mode for kscan */
    REG_GPIO_PE_IE &= ~(PE1_BIT | PE2_BIT);
    REG_GPIO_PE_FUNC |= (PE1_BIT | PE2_BIT);
    /* Clear func_mux back to 0 (safe default for GPIO mode) */
    REG_GPIO_PE_FUC_L &= ~(PE1_FUNC_MASK | PE2_FUNC_MASK);
    REG_GPIO_PE_OUT |= (PE1_BIT | PE2_BIT);   /* drive HIGH (kscan idle) */
}

/* ── HSPI hardware SPI ───────────────────────────────────────────────── */

static void hspi_init(void) {
    /* Enable HSPI peripheral clock */
    REG_CLK_EN0 |= CLK0_HSPI_EN;

    /* Set pad_mul_sel bit 1 (required for PE alternate functions) */
    (*(volatile uint8_t *)0x80140355) |= BIT(1);

    /* Log pre-init state of critical registers for diagnosis */
    uint8_t xip_before = REG_HSPI_XIP_CTRL;
    uint8_t mode0_before = REG_HSPI_MODE0;
    uint8_t trans0_before = REG_HSPI_TRANS0;

    /* Master mode, SPI Mode 3 (CPOL=1, CPHA=1), MSB first
     * QMK PR#17263 changed AW20216S default to Mode 3.
     * Zephyr AW20216S driver also uses SPI_MODE_CPOL|SPI_MODE_CPHA. */
    REG_HSPI_MODE0 = HSPI_MASTER_MODE | BIT(6) | BIT(5);  /* 0xE0 = master + mode 3 */

    /* Clock divider: spi_clock = source_clock / (2 * (div + 1))
     * AW20216S requires 1-10 MHz. With 48 MHz source:
     * div=5 → 48M/(2*6) = 4 MHz (safe middle of 1-10 MHz range) */
    REG_HSPI_MODE1 = 5;

    /* Disable command phase, set CS high time = 0 (minimum) */
    REG_HSPI_MODE2 = 0x00;

    /* Disable HSPI address phase — without this the hardware inserts
     * 1-4 address bytes before data, corrupting the AW20216S protocol.
     * Also disables XIP mode and clears all other bits. */
    REG_HSPI_XIP_CTRL = 0x00;

    /* No DMA, no interrupts */
    REG_HSPI_TRANS2 = 0x00;

    /* Set WRITE_ONLY transmode + no dummy */
    REG_HSPI_TRANS0 = (0x01 << 4);

    /* Clear FIFOs */
    REG_HSPI_FIFO_ST |= BIT(2) | BIT(3);  /* RXF_CLR | TXF_CLR */

    LOG_INF("HSPI pre-init: XIP=0x%02x MODE0=0x%02x TRANS0=0x%02x",
            xip_before, mode0_before, trans0_before);
    LOG_INF("HSPI post-init: MODE0=0x%02x MODE2=0x%02x XIP=0x%02x TRANS0=0x%02x",
            REG_HSPI_MODE0, REG_HSPI_MODE2, REG_HSPI_XIP_CTRL, REG_HSPI_TRANS0);
}

static void hspi_write_bytes(const uint8_t *data, uint16_t len) {
    /* Clear TX FIFO */
    REG_HSPI_FIFO_ST |= BIT(3);

    /* Set TX byte count (24-bit, len-1 format) */
    REG_HSPI_TX_CNT0 = (uint8_t)((len - 1) & 0xFF);
    REG_HSPI_TX_CNT1 = (uint8_t)(((len - 1) >> 8) & 0xFF);
    REG_HSPI_TX_CNT2 = (uint8_t)(((len - 1) >> 16) & 0xFF);

    /* Set transfer mode: write-only (0x1 << 4) */
    REG_HSPI_TRANS0 = (REG_HSPI_TRANS0 & 0x0F) | (0x01 << 4);

    /* TRIGGER: write command register starts the transfer */
    REG_HSPI_TRANS1 = 0x00;

    /* Feed data to TX FIFO — hardware clocks it out as we feed */
    for (uint16_t i = 0; i < len; i++) {
        while (REG_HSPI_FIFO_ST & HSPI_TXF_FULL) {}
        REG_HSPI_DATA(i & 3) = data[i];
    }

    /* Wait for transfer to complete */
    while (REG_HSPI_STATUS & HSPI_BUSY) {}
}

/* ── GPIO bit-bang SPI (diagnostic bypass of HSPI hardware) ──────────── */

/*
 * Bit-bang SPI Mode 3 (CPOL=1, CPHA=1) at ~2-4 MHz using direct GPIO writes.
 * CLK idles HIGH. Data sampled on rising edge, changed on falling edge.
 * At 48 MHz CPU, each register write takes ~1 cycle = ~21ns.
 * A full bit (2 writes) = ~42ns → ~24 MHz theoretical max.
 * With loop overhead: ~2-4 MHz actual — within AW20216S 1-10 MHz spec.
 */
static void bitbang_byte(uint8_t byte) {
    for (int bit = 7; bit >= 0; bit--) {
        /* Falling edge: change data */
        REG_GPIO_PE_OUT &= ~PE1_BIT;  /* CLK LOW */
        if (byte & (1 << bit)) {
            REG_GPIO_PE_OUT |= PE2_BIT;   /* MOSI HIGH */
        } else {
            REG_GPIO_PE_OUT &= ~PE2_BIT;  /* MOSI LOW */
        }
        /* Rising edge: data sampled by slave */
        REG_GPIO_PE_OUT |= PE1_BIT;   /* CLK HIGH */
    }
}

static void aw_write(uint8_t chip, uint8_t page, uint8_t reg,
                     const uint8_t *data, uint16_t len) {
    /* Ensure PE1/PE2 are in GPIO output mode (not HSPI) */
    REG_GPIO_PE_FUNC |= (PE1_BIT | PE2_BIT);
    REG_GPIO_PE_OEN &= ~(PE1_BIT | PE2_BIT);
    REG_GPIO_PE_OUT |= PE1_BIT;  /* CLK idles HIGH (Mode 3) */

    /* Assert CS via GPIO */
    if (chip == 0) {
        REG_GPIO_PE_OUT &= ~PE0_BIT;
    } else {
        REG_GPIO_PC_OUT &= ~PC0_BIT;
    }
    for (volatile int d = 0; d < 20; d++) {}

    /* Send: [cmd_byte][reg_addr][data...] */
    bitbang_byte(AW_CMD_WRITE(page));
    bitbang_byte(reg);
    for (uint16_t i = 0; i < len; i++) {
        bitbang_byte(data[i]);
    }

    for (volatile int d = 0; d < 20; d++) {}

    /* Deassert CS */
    REG_GPIO_PE_OUT |= PE0_BIT;
    REG_GPIO_PC_OUT |= PC0_BIT;

    for (volatile int d = 0; d < 20; d++) {}
}

static inline void aw_write_single(uint8_t chip, uint8_t page,
                                   uint8_t reg, uint8_t val) {
    aw_write(chip, page, reg, &val, 1);
}

/* ── AW20216S initialization ─────────────────────────────────────────── */

static void aw_chip_init(uint8_t chip) {
    aw_write_single(chip, AW_PAGE_CONFIG, AW_REG_RSTN, AW_RESET_VAL);
    k_busy_wait(2000);

    aw_write_single(chip, AW_PAGE_CONFIG, AW_REG_GCR, 0x01);
    aw_write_single(chip, AW_PAGE_CONFIG, AW_REG_GCCR, 0xFF);

    /* All scaling to max */
    uint8_t scaling[AW_PWM_CHANNELS];
    memset(scaling, 0xFF, sizeof(scaling));
    aw_write(chip, AW_PAGE_SCALE, 0x00, scaling, AW_PWM_CHANNELS);

    /* All PWM off */
    uint8_t zeros[AW_PWM_CHANNELS];
    memset(zeros, 0x00, sizeof(zeros));
    aw_write(chip, AW_PAGE_PWM, 0x00, zeros, AW_PWM_CHANNELS);
}

/* ── LED power control ───────────────────────────────────────────────── */

static void led_power_on(void) {
    REG_GPIO_PC_IE &= ~PC2_BIT;
    REG_GPIO_PC_OEN &= ~PC2_BIT;
    REG_GPIO_PC_OUT |= PC2_BIT;
    k_msleep(50);
    LOG_INF("PC2 power ON (HIGH) (OUT=0x%02x OEN=0x%02x)", REG_GPIO_PC_OUT, REG_GPIO_PC_OEN);
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

    /* GPIO bit-bang: aw_write handles pin mode internally */
    aw_write(0, AW_PAGE_PWM, 0x00, chip0_pwm, AW_PWM_CHANNELS);
    aw_write(1, AW_PAGE_PWM, 0x00, chip1_pwm, AW_PWM_CHANNELS);

    /* Restore pins for kscan */
    REG_GPIO_PE_OUT |= (PE1_BIT | PE2_BIT);

    irq_unlock(key);
}

/* ── Public API ──────────────────────────────────────────────────────── */

void crush80_rgb_set_led(uint8_t index, uint8_t r, uint8_t g, uint8_t b) {
    if (index >= CRUSH80_LED_COUNT_TOTAL) {
        return;
    }
    uint16_t ch_offset = (uint16_t)index * 3;
    if (index < 72) {
        if (ch_offset + 2 < AW_PWM_CHANNELS) {
            chip0_pwm[ch_offset + 0] = r;
            chip0_pwm[ch_offset + 1] = g;
            chip0_pwm[ch_offset + 2] = b;
        }
    } else {
        uint16_t offset = (uint16_t)(index - 72) * 3;
        if (offset + 2 < AW_PWM_CHANNELS) {
            chip1_pwm[offset + 0] = r;
            chip1_pwm[offset + 1] = g;
            chip1_pwm[offset + 2] = b;
        }
    }
}

void crush80_rgb_set_all(uint8_t r, uint8_t g, uint8_t b) {
    for (uint8_t i = 0; i < CRUSH80_LED_COUNT_TOTAL; i++) {
        crush80_rgb_set_led(i, r, g, b);
    }
}

void crush80_rgb_toggle(void) {
    rgb_enabled = !rgb_enabled;
    if (!rgb_enabled) {
        memset(chip0_pwm, 0, sizeof(chip0_pwm));
        memset(chip1_pwm, 0, sizeof(chip1_pwm));
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

    k_msleep(2000);

    LOG_INF("crush80_rgb: powering on LED rail");
    led_power_on();

    LOG_INF("crush80_rgb: configuring GPIO bit-bang SPI + initializing AW20216S");

    unsigned int key = irq_lock();

    /* GPIO bit-bang mode: keep PE1/PE2 in GPIO mode, ensure output enabled */
    REG_GPIO_PE_FUNC |= (PE1_BIT | PE2_BIT);  /* GPIO mode */
    REG_GPIO_PE_OEN &= ~(PE1_BIT | PE2_BIT | PE0_BIT);  /* output enable */
    REG_GPIO_PE_OUT |= (PE1_BIT | PE0_BIT);   /* CLK HIGH idle, CS HIGH */
    REG_GPIO_PC_OEN &= ~PC0_BIT;             /* PC0 CS output */
    REG_GPIO_PC_OUT |= PC0_BIT;              /* PC0 CS HIGH */

    LOG_INF("GPIO bitbang: PE_FUNC=0x%02x PE_OEN=0x%02x PE_OUT=0x%02x",
            REG_GPIO_PE_FUNC, REG_GPIO_PE_OEN, REG_GPIO_PE_OUT);
    aw_chip_init(0);
    LOG_INF("After chip0 init (bitbang): done");
    aw_chip_init(1);

    irq_unlock(key);

    irq_unlock(key);

    rgb_initialized = true;
    LOG_INF("crush80_rgb: init complete, PE_FUNC=0x%02x", REG_GPIO_PE_FUNC);

    /* Test pattern: all PWM to max */
    memset(chip0_pwm, 0xFF, sizeof(chip0_pwm));
    memset(chip1_pwm, 0xFF, sizeof(chip1_pwm));

    LOG_INF("crush80_rgb: starting first frame");
    rgb_update_frame();
    LOG_INF("crush80_rgb: first frame done, entering loop");

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
