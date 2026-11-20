/*
 * Copyright (c) 2025 scholzri
 * SPDX-License-Identifier: Apache-2.0
 *
 * Telink B91 WS2812 LED strip over PSPI MOSI (PB7) and DMA channel 4.
 */

#define DT_DRV_COMPAT telink_b91_spi_led_strip

#include "b91_pspi.h"

#include <zephyr/device.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/led_strip.h>
#include <zephyr/irq.h>
#include <zephyr/irq_multilevel.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/sys_io.h>

#define STRIP_NODE DT_INST(0, DT_DRV_COMPAT)
#define NUM_LEDS DT_PROP(STRIP_NODE, chain_length)
#define PSPI_IRQ (IRQ_TO_L2(B91_PSPI_IRQ_SRC) | 11)
#define PSPI_IRQ_PRIORITY 2
#define DMA_CHANNEL B91_DMA_CH_BASE(4)

/* PSPI reset and clock gate from the B91 HAL's soc.h. */
#define B91_RST1 0x801401E1UL
#define B91_CLK_EN1 0x801401E5UL
#define B91_PSPI_ENABLE BIT(6)

/* Memory increments, and the fixed PSPI FIFO destination requests 32-bit words. */
#define DMA_CONFIG ((B91_DMA_REQ_PSPI_TX << 4) | (2 << 14) | BIT(18) | (2 << 20) | (2 << 22))

static const struct gpio_dt_spec strip_power = GPIO_DT_SPEC_GET(STRIP_NODE, power_gpios);
static uint8_t __aligned(4) spi_buf[NUM_LEDS * WS2812_SPI_BYTES_PER_LED];
static K_MUTEX_DEFINE(strip_lock);
static K_SEM_DEFINE(transfer_done, 0, 1);
static bool powered;

static void pspi_setup(void)
{
	sys_write8(B91_PSPI_MODE0_MASTER, B91_PSPI_MODE0);
	sys_write8(B91_PSPI_CLK_DIV, B91_PSPI_MODE1);
	sys_write8(0, B91_PSPI_MODE2);
	sys_write8(B91_PSPI_TRANS0_WRITE_ONLY, B91_PSPI_TRANS0);
	sys_write8(B91_PSPI_END_INT, B91_PSPI_IRQ_STATE);
	sys_write8(B91_PSPI_TRANS2_TX_DMA_EN | B91_PSPI_TRANS2_END_INT_EN,
		   B91_PSPI_TRANS2);
}

static void pspi_end_isr(const void *arg)
{
	ARG_UNUSED(arg);

	if (sys_read8(B91_PSPI_IRQ_STATE) & B91_PSPI_END_INT) {
		sys_write8(B91_PSPI_END_INT, B91_PSPI_IRQ_STATE);
		k_sem_give(&transfer_done);
	}
}

static int set_power(bool on)
{
	/* PC0, PC1 and PC4 are matrix columns on the same GPIO port. */
	unsigned int key = irq_lock();
	int rc = gpio_pin_set_dt(&strip_power, on);
	irq_unlock(key);

	if (rc == 0) {
		powered = on;
	}
	return rc;
}

static void encode_color(uint8_t **dest, uint8_t value)
{
	for (int bit = 7; bit >= 0; --bit) {
		*(*dest)++ = (value & BIT(bit)) ? WS2812_SPI_ONE : WS2812_SPI_ZERO;
	}
}

static int strip_send(size_t nbytes)
{
	/* PSPI count is bytes minus one. 24 bytes per LED is word-aligned. */
	uint32_t count = nbytes - 1U;
	sys_write8(count & 0xFF, B91_PSPI_TX_CNT0);
	sys_write8((count >> 8) & 0xFF, B91_PSPI_TX_CNT1);
	sys_write8((count >> 16) & 0xFF, B91_PSPI_TX_CNT2);
	sys_write8(sys_read8(B91_PSPI_FIFO_STATE) | B91_PSPI_FIFO_CLR_TX,
		   B91_PSPI_FIFO_STATE);

	sys_write32(b91_dma_addr(spi_buf), DMA_CHANNEL + B91_DMA_SRC_ADDR);
	sys_write32(B91_PSPI_DATA0, DMA_CHANNEL + B91_DMA_DST_ADDR);
	sys_write32(nbytes / 4U, DMA_CHANNEL + B91_DMA_SIZE);

	sys_write8(B91_PSPI_END_INT, B91_PSPI_IRQ_STATE);
	k_sem_reset(&transfer_done);
	sys_write32(DMA_CONFIG | BIT(0), DMA_CHANNEL + B91_DMA_CTRL);
	sys_write8(0, B91_PSPI_TRANS1);

	/* Eight SPI clocks per encoded bit at 6 MHz plus time for the IRQ. */
	if (k_sem_take(&transfer_done, K_USEC(DIV_ROUND_UP(nbytes * 4, 3) + 2000)) != 0) {
		irq_disable(PSPI_IRQ);
		sys_write32(DMA_CONFIG, DMA_CHANNEL + B91_DMA_CTRL);
		uint8_t reset = sys_read8(B91_RST1) | B91_PSPI_ENABLE;
		sys_write8(reset & ~B91_PSPI_ENABLE, B91_RST1);
		sys_write8(reset, B91_RST1);
		pspi_setup();
		irq_enable(PSPI_IRQ);
		/* Clear any incomplete frame and let the next update retry. */
		set_power(false);
		return -ETIMEDOUT;
	}

	/* Only the calling work queue waits. Matrix, USB and BLE IRQs stay enabled. */
	k_usleep(WS2812_RESET_US);
	return 0;
}

static int strip_update_rgb(const struct device *dev, struct led_rgb *pixels, size_t count)
{
	if (!device_is_ready(dev)) {
		return -ENODEV;
	}
	if (count != NUM_LEDS) {
		return -EINVAL;
	}

	k_mutex_lock(&strip_lock, K_FOREVER);

	uint8_t *encoded = spi_buf;
	bool visible = false;
	for (size_t i = 0; i < count; ++i) {
		const struct led_rgb *pixel = &pixels[i];
		visible |= (pixel->r | pixel->g | pixel->b) != 0U;
		encode_color(&encoded, pixel->g);
		encode_color(&encoded, pixel->r);
		encode_color(&encoded, pixel->b);
	}

	int rc = 0;
	if (visible != powered) {
		rc = set_power(visible);
		if (rc == 0 && visible) {
			/* Let the LED supply settle before clocking the first frame. */
			k_msleep(2);
		}
	}
	if (rc == 0 && visible) {
		rc = strip_send(count * WS2812_SPI_BYTES_PER_LED);
	}

	k_mutex_unlock(&strip_lock);
	return rc;
}

static size_t strip_length(const struct device *dev)
{
	ARG_UNUSED(dev);
	return NUM_LEDS;
}

static int strip_init(const struct device *dev)
{
	ARG_UNUSED(dev);

	if (!gpio_is_ready_dt(&strip_power)) {
		return -ENODEV;
	}

	int rc = gpio_pin_configure_dt(&strip_power, GPIO_OUTPUT_INACTIVE);
	if (rc != 0) {
		return rc;
	}

	/* Enable PSPI without routing its clock to PB5, a matrix column. */
	sys_write8(sys_read8(B91_CLK_EN1) | B91_PSPI_ENABLE, B91_CLK_EN1);
	pspi_setup();
	uint8_t mux = sys_read8(B91_GPIO_PB_FUC_H);
	sys_write8((mux & ~B91_PB7_FUC_MASK) | B91_PB7_FUC_PSPI_MOSI, B91_GPIO_PB_FUC_H);
	sys_write8(sys_read8(B91_GPIO_PB_GPIO) & ~BIT(7), B91_GPIO_PB_GPIO);

	irq_connect_dynamic(PSPI_IRQ, PSPI_IRQ_PRIORITY, pspi_end_isr, NULL, 0);
	irq_enable(PSPI_IRQ);
	return 0;
}

static DEVICE_API(led_strip, strip_api) = {
	.update_rgb = strip_update_rgb,
	.length = strip_length,
};

DEVICE_DT_DEFINE(STRIP_NODE, strip_init, NULL, NULL, NULL, POST_KERNEL,
		 CONFIG_LED_STRIP_INIT_PRIORITY, &strip_api);
