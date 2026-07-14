/*
 * AW20216S LED Matrix Controller — Zephyr Driver
 * Wobkey Crush 80 — 154 per-key LEDs
 *
 * The AW20216S drives up to 216 individual LED channels over SPI.
 * Protocol: write 0xFD (page select), then page number, then registers.
 *   Page 0 (GCR): global config — enable, global current, sync mode
 *   Page 1 (PWM): 8-bit PWM per channel (0x00-0xD7 = channels 1-216)
 *   Page 2 (LED scaling): per-channel current scaling
 *
 * Confirmed: 0xFD 0x00 (page select) appears at 3 locations in Crush 80
 * firmware binary (offsets 0x046CE, 0x046E2, 0x046F6).
 *
 * SPI pins: UNKNOWN — DTS stub uses placeholder. Run Ghidra against
 * v2_patched.bin LED init at ~0xEF88 with RISCV:LE:32:AndeStar_v5 processor
 * to find the actual CS/CLK/MOSI pins, then update crush80.dts.
 *
 * LED index order: from firmware offset 0x1C260 (91-entry matrix→LED table).
 * Full 154-LED order must be validated at bring-up by driving LEDs 0,1,2...
 * and observing which physical key lights up.
 *
 * Copyright (c) 2025 — Apache 2.0
 */

#define DT_DRV_COMPAT wobkey_aw20216s

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/spi.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/sys/util.h>
#include <string.h>

#include <zephyr/logging/log.h>
LOG_MODULE_REGISTER(aw20216s, CONFIG_AW20216S_LOG_LEVEL);

/* -----------------------------------------------------------------------
 * AW20216S register map
 * ---------------------------------------------------------------------- */

/* Command register — always at address 0xFD */
#define AW20216S_REG_COMMAND     0xFD

/* Pages */
#define AW20216S_PAGE_GCR        0x00  /* Global configuration */
#define AW20216S_PAGE_PWM        0x01  /* Per-LED PWM (8-bit) */
#define AW20216S_PAGE_SCALING    0x02  /* Per-LED current scaling */

/* Global Configuration Registers (page 0) */
#define AW20216S_REG_GCR1        0x00  /* Configuration 1 */
#define   AW20216S_GCR1_ENABLE   BIT(0) /* Chip enable */
#define   AW20216S_GCR1_SYNC     BIT(6) /* Sync mode enable */
#define AW20216S_REG_GCR2        0x01  /* Configuration 2 */
#define AW20216S_REG_GCCR        0x01  /* Global current control (0x00-0xFF) */
#define AW20216S_REG_PHCR1       0x02  /* Phase control 1 */
#define AW20216S_REG_RESET       0x2F  /* Write 0xAE to software reset */
#define   AW20216S_RESET_VALUE   0xAE

/* PWM page: 0x00-0xD7 = channels SW1-CS1 through SW9-CS24
 * Channel layout: 9 rows (SW) × 24 columns (CS) = 216 channels
 * Address = (sw_row * 24) + cs_col, where sw_row in [0,8], cs_col in [0,23]
 */
#define AW20216S_PWM_CHANNELS    216
#define AW20216S_NUM_LEDS        154  /* Crush 80 per-key LEDs */

/* SPI write bit — AW20216S uses bit 7 of address: 0=write, 1=read */
#define AW20216S_WRITE_BIT       0x00
#define AW20216S_READ_BIT        0x80

/* -----------------------------------------------------------------------
 * Driver config and data structures
 * ---------------------------------------------------------------------- */

struct aw20216s_config {
	struct spi_dt_spec spi;
	struct gpio_dt_spec enable_gpio;  /* optional LED power enable */
	uint8_t num_leds;
	uint8_t global_current;           /* 0x00-0xFF, default 0x20 (~12%) */
};

struct aw20216s_data {
	/* Shadow buffer for PWM values — R, G, B per LED = 3 bytes */
	uint8_t pwm_buf[AW20216S_PWM_CHANNELS];
	bool    dirty;
};

/* -----------------------------------------------------------------------
 * LED channel mapping: logical LED index → (sw_row, cs_col) pair
 *
 * PLACEHOLDER: The actual mapping must be validated at bring-up by
 * lighting LED 0, 1, 2... and recording which physical key illuminates.
 * Use the firmware index table at offset 0x1C260 as a starting reference.
 *
 * The AW20216S on the Crush 80 PCB likely uses a 9-row × 17-column
 * subset (153 channels) covering all 154 LEDs.
 *
 * Format: {sw_row, cs_col} — row in [0,8], col in [0,23]
 * sw_row 0 = SW1 (first scan row), cs_col 0 = CS1 (first column)
 * PWM address = sw_row * 24 + cs_col
 *
 * TODO: Replace this placeholder with validated mapping from hardware bring-up.
 * Each entry corresponds to one physical key in left-to-right, top-to-bottom order.
 */
static const uint8_t crush80_led_sw[AW20216S_NUM_LEDS] = {
	/* Row 0 — function row (16 keys) */
	0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
	/* Row 1 — number row (16 keys) */
	1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,
	/* Row 2 — QWERTY row (16 keys) */
	2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,
	/* Row 3 — home row (13 keys) */
	3,3,3,3,3,3,3,3,3,3,3,3,3,
	/* Row 4 — shift row (14 keys) */
	4,4,4,4,4,4,4,4,4,4,4,4,4,4,
	/* Row 5 — bottom row (10 keys) */
	5,5,5,5,5,5,5,5,5,5,
	/* Side LEDs / underglow (if any) — placeholder zeros */
	8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,
	8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,
	8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,
};

static const uint8_t crush80_led_cs[AW20216S_NUM_LEDS] = {
	/* Row 0 */
	0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,
	/* Row 1 */
	0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,
	/* Row 2 */
	0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,
	/* Row 3 */
	0,1,2,3,4,5,6,7,8,9,10,11,12,
	/* Row 4 */
	0,1,2,3,4,5,6,7,8,9,10,11,12,13,
	/* Row 5 */
	0,1,2,3,4,5,6,7,8,9,
	/* Side LEDs */
	0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,
	16,17,18,19,20,21,22,23,0,1,2,3,4,5,6,7,8,9,
	10,11,12,13,14,15,16,17,18,19,20,21,22,23,0,1,2,
};

/* -----------------------------------------------------------------------
 * SPI helpers
 * ---------------------------------------------------------------------- */

static int aw20216s_write_reg(const struct device *dev,
			       uint8_t addr, uint8_t val)
{
	const struct aw20216s_config *cfg = dev->config;

	uint8_t buf[2] = {addr | AW20216S_WRITE_BIT, val};
	struct spi_buf tx = {.buf = buf, .len = 2};
	struct spi_buf_set tx_set = {.buffers = &tx, .count = 1};

	return spi_write_dt(&cfg->spi, &tx_set);
}

static int aw20216s_select_page(const struct device *dev, uint8_t page)
{
	return aw20216s_write_reg(dev, AW20216S_REG_COMMAND, page);
}

/*
 * Burst-write the entire PWM page in one SPI transaction.
 * This is far faster than 216 individual writes and is how
 * the original Evision firmware updates the LEDs.
 *
 * Transaction: [0x00 (addr=0, write)] [pwm_buf[0..215]]
 */
static int aw20216s_flush_pwm(const struct device *dev)
{
	const struct aw20216s_config *cfg = dev->config;
	struct aw20216s_data *data = dev->data;

	int ret = aw20216s_select_page(dev, AW20216S_PAGE_PWM);
	if (ret) {
		return ret;
	}

	/* Address byte (0x00) + 216 PWM bytes */
	uint8_t addr = 0x00 | AW20216S_WRITE_BIT;
	struct spi_buf tx[2] = {
		{.buf = &addr, .len = 1},
		{.buf = data->pwm_buf, .len = AW20216S_PWM_CHANNELS},
	};
	struct spi_buf_set tx_set = {.buffers = tx, .count = 2};

	return spi_write_dt(&cfg->spi, &tx_set);
}

/* -----------------------------------------------------------------------
 * LED public API
 * ---------------------------------------------------------------------- */

/*
 * Set one LED to an RGB color. Does NOT flush to hardware — call
 * aw20216s_update() after setting all desired LEDs.
 *
 * The AW20216S doesn't have an RGGB sub-pixel order — each channel is
 * independent. We use 3 consecutive channels per LED (R, G, B).
 * Channel address = sw_row * 24 + cs_col
 */
void aw20216s_set_rgb(const struct device *dev,
		       uint8_t led_idx, uint8_t r, uint8_t g, uint8_t b)
{
	struct aw20216s_data *data = dev->data;

	if (led_idx >= AW20216S_NUM_LEDS) {
		return;
	}

	uint8_t sw = crush80_led_sw[led_idx];
	uint8_t cs = crush80_led_cs[led_idx];

	/* Each physical LED uses 3 consecutive CS columns (R, G, B) */
	uint16_t base = sw * 24 + cs;
	if (base + 2 >= AW20216S_PWM_CHANNELS) {
		return;
	}

	data->pwm_buf[base + 0] = r;
	data->pwm_buf[base + 1] = g;
	data->pwm_buf[base + 2] = b;
	data->dirty = true;
}

/* Set all LEDs to one color */
void aw20216s_set_all_rgb(const struct device *dev,
			   uint8_t r, uint8_t g, uint8_t b)
{
	for (uint8_t i = 0; i < AW20216S_NUM_LEDS; i++) {
		aw20216s_set_rgb(dev, i, r, g, b);
	}
}

/* Push buffered PWM values to hardware */
int aw20216s_update(const struct device *dev)
{
	struct aw20216s_data *data = dev->data;

	if (!data->dirty) {
		return 0;
	}
	data->dirty = false;
	return aw20216s_flush_pwm(dev);
}

/* -----------------------------------------------------------------------
 * Initialization
 * ---------------------------------------------------------------------- */

static int aw20216s_init(const struct device *dev)
{
	const struct aw20216s_config *cfg = dev->config;
	struct aw20216s_data *data = dev->data;
	int ret;

	memset(data->pwm_buf, 0, sizeof(data->pwm_buf));
	data->dirty = false;

	if (!spi_is_ready_dt(&cfg->spi)) {
		LOG_ERR("SPI bus not ready");
		return -ENODEV;
	}

	/* Optional: drive LED power enable pin HIGH */
	if (cfg->enable_gpio.port) {
		ret = gpio_pin_configure_dt(&cfg->enable_gpio, GPIO_OUTPUT_ACTIVE);
		if (ret) {
			LOG_ERR("Failed to configure LED enable GPIO: %d", ret);
			return ret;
		}
		/* Short settling delay after power enable */
		k_sleep(K_MSEC(5));
	}

	/* Software reset */
	ret = aw20216s_select_page(dev, AW20216S_PAGE_GCR);
	if (ret) {
		return ret;
	}
	ret = aw20216s_write_reg(dev, AW20216S_REG_RESET, AW20216S_RESET_VALUE);
	if (ret) {
		return ret;
	}
	k_sleep(K_MSEC(2));

	/* Configure: enable chip, set global current */
	ret = aw20216s_select_page(dev, AW20216S_PAGE_GCR);
	if (ret) {
		return ret;
	}
	ret = aw20216s_write_reg(dev, AW20216S_REG_GCR1, AW20216S_GCR1_ENABLE);
	if (ret) {
		return ret;
	}
	ret = aw20216s_write_reg(dev, AW20216S_REG_GCCR, cfg->global_current);
	if (ret) {
		return ret;
	}

	/* Set all LED scaling to max (page 2) */
	ret = aw20216s_select_page(dev, AW20216S_PAGE_SCALING);
	if (ret) {
		return ret;
	}
	uint8_t addr = 0x00 | AW20216S_WRITE_BIT;
	uint8_t scaling[AW20216S_PWM_CHANNELS];
	memset(scaling, 0xFF, sizeof(scaling));
	struct spi_buf tx[2] = {
		{.buf = &addr, .len = 1},
		{.buf = scaling, .len = sizeof(scaling)},
	};
	struct spi_buf_set tx_set = {.buffers = tx, .count = 2};
	ret = spi_write_dt(&cfg->spi, &tx_set);
	if (ret) {
		return ret;
	}

	/* All LEDs off initially */
	memset(data->pwm_buf, 0, sizeof(data->pwm_buf));
	data->dirty = true;
	ret = aw20216s_update(dev);
	if (ret) {
		return ret;
	}

	LOG_INF("AW20216S initialized (%d LEDs, global_current=0x%02x)",
		cfg->num_leds, cfg->global_current);
	return 0;
}

/* -----------------------------------------------------------------------
 * Zephyr device instantiation
 * ---------------------------------------------------------------------- */

#define AW20216S_INIT(inst)							\
	static struct aw20216s_data aw20216s_data_##inst;			\
	static const struct aw20216s_config aw20216s_cfg_##inst = {		\
		.spi = SPI_DT_SPEC_INST_GET(inst,				\
			SPI_OP_MODE_MASTER | SPI_WORD_SET(8) |			\
			SPI_TRANSFER_MSB | SPI_MODE_CPOL | SPI_MODE_CPHA,	\
			0),							\
		.enable_gpio = GPIO_DT_SPEC_INST_GET_OR(inst, enable_gpios, {0}),\
		.num_leds    = DT_INST_PROP(inst, num_leds),			\
		.global_current = DT_INST_PROP_OR(inst, global_current, 0x20),	\
	};									\
	DEVICE_DT_INST_DEFINE(inst, aw20216s_init, NULL,			\
			      &aw20216s_data_##inst,				\
			      &aw20216s_cfg_##inst,				\
			      POST_KERNEL,					\
			      CONFIG_AW20216S_INIT_PRIORITY,			\
			      NULL);

DT_INST_FOREACH_STATUS_OKAY(AW20216S_INIT)
