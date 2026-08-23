/*
 * Crush 80 LED/Matrix pin-sharing coordinator.
 *
 * PE0, PE1, PE2 are shared between the matrix scan (as column GPIOs)
 * and the AW20216S LED controller (as HSPI CS/CLK/MOSI).
 *
 * This module provides acquire/release functions that:
 * - acquire: pauses kscan, reconfigures PE0/PE1/PE2 to HSPI function
 * - release: restores PE0/PE1/PE2 to GPIO function, resumes kscan
 *
 * The RGB thread calls these around each SPI frame (~60Hz).
 * Total pin-hold time is ~3-5ms per frame (negligible for typing).
 */

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/kscan.h>
#include <zephyr/sys/util.h>

#include <zephyr/logging/log.h>
LOG_MODULE_REGISTER(led_sync, CONFIG_AW20216S_LOG_LEVEL);

/*
 * B91 GPIO function registers (direct register access for speed).
 * On B91, each port has a "function high" register that controls
 * the alternate function of pins 4-7 (high nibble uses func_h,
 * low nibble uses func_l). PE0-PE2 are in the low nibble.
 *
 * Register addresses (from Telink B91 SDK):
 *   reg_gpio_pe_fuc_l = *(volatile uint8_t*)(0x80140336)
 *   reg_gpio_pe_fuc_h = *(volatile uint8_t*)(0x80140337)
 *   reg_gpio_pe_oen   = *(volatile uint8_t*)(0x80140322)
 *   reg_gpio_pe_ie    = *(volatile uint8_t*)(0x80140323)
 *   reg_gpio_pe_out   = *(volatile uint8_t*)(0x80140321)
 *
 * PE function encoding for FUNC_C (HSPI):
 *   func_l bits [1:0] for PE0 = 0b10 (FUNC_C)
 *   func_l bits [3:2] for PE1 = 0b10 (FUNC_C)
 *   func_l bits [5:4] for PE2 = 0b10 (FUNC_C)
 *   So func_l |= 0x2A for PE0,PE1,PE2 as FUNC_C
 *   And func_l &= ~0x2A for PE0,PE1,PE2 as GPIO (FUNC_A = 0b00)
 */

#define REG_GPIO_PE_FUC_L   (*(volatile uint8_t *)0x80140336)
#define REG_GPIO_PE_OEN     (*(volatile uint8_t *)0x80140322)
#define REG_GPIO_PE_IE      (*(volatile uint8_t *)0x80140323)
#define REG_GPIO_PE_OUT     (*(volatile uint8_t *)0x80140321)

#define PE012_FUNC_C_MASK   0x2A  /* bits [5:4]=10, [3:2]=10, [1:0]=10 */
#define PE012_PIN_MASK      0x07  /* PE0|PE1|PE2 = bits 0,1,2 */

static const struct device *kscan_dev;
static struct k_mutex sync_mutex;
static bool pins_held_for_spi;

int crush80_led_sync_init(void)
{
	kscan_dev = DEVICE_DT_GET(DT_NODELABEL(kscan0));
	if (!device_is_ready(kscan_dev)) {
		LOG_ERR("kscan device not ready");
		return -ENODEV;
	}

	k_mutex_init(&sync_mutex);
	pins_held_for_spi = false;

	LOG_INF("LED/matrix pin-sharing coordinator initialized");
	return 0;
}

/*
 * Acquire PE0/PE1/PE2 for SPI (LED update).
 * Must be called before any AW20216S SPI transaction.
 */
int crush80_led_acquire(void)
{
	k_mutex_lock(&sync_mutex, K_FOREVER);

	if (pins_held_for_spi) {
		k_mutex_unlock(&sync_mutex);
		return 0;
	}

	/* 1. Disable kscan to stop driving columns */
	kscan_disable_callback(kscan_dev);

	/* 2. Small delay for any in-progress scan to complete */
	k_busy_wait(50);

	/* 3. Switch PE0/PE1/PE2 from GPIO to HSPI (FUNC_C) */
	/* Disable output enable on PE0/PE1/PE2 (set OEN bits = high-Z) */
	REG_GPIO_PE_OEN |= PE012_PIN_MASK;
	/* Set function to FUNC_C (HSPI) */
	REG_GPIO_PE_FUC_L |= PE012_FUNC_C_MASK;

	pins_held_for_spi = true;
	k_mutex_unlock(&sync_mutex);
	return 0;
}

/*
 * Release PE0/PE1/PE2 back to GPIO (matrix scan).
 * Must be called after AW20216S SPI transaction completes.
 */
int crush80_led_release(void)
{
	k_mutex_lock(&sync_mutex, K_FOREVER);

	if (!pins_held_for_spi) {
		k_mutex_unlock(&sync_mutex);
		return 0;
	}

	/* 1. Switch PE0/PE1/PE2 back to GPIO (FUNC_A = clear func bits) */
	REG_GPIO_PE_FUC_L &= ~PE012_FUNC_C_MASK;
	/* Re-enable output on PE0/PE1/PE2 (clear OEN bits = output enabled) */
	REG_GPIO_PE_OEN &= ~PE012_PIN_MASK;

	/* 2. Re-enable kscan */
	kscan_enable_callback(kscan_dev);

	pins_held_for_spi = false;
	k_mutex_unlock(&sync_mutex);
	return 0;
}

SYS_INIT(crush80_led_sync_init, APPLICATION, 91);
