/*
 * UART mcumgr RX kickstart — workaround for B91 CDC-ACM init race.
 *
 * Problem: the mcumgr UART transport calls uart_irq_rx_enable() during
 * SYS_INIT, but on B91 the USB CDC-ACM bulk OUT endpoint isn't ready
 * until the host completes SET_CONFIGURATION. The initial rx_enable is
 * silently dropped, leaving the RX chain permanently dead.
 *
 * Fix: a dedicated thread that waits for USB to settle, then repeatedly
 * re-enables RX interrupts on the mcumgr UART until data can flow.
 *
 * Copyright (c) 2026
 * SPDX-License-Identifier: Apache-2.0
 */

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(uart_mcumgr_kick, LOG_LEVEL_INF);

#if DT_HAS_CHOSEN(zephyr_uart_mcumgr)
#define MCUMGR_UART_DEV DEVICE_DT_GET(DT_CHOSEN(zephyr_uart_mcumgr))
#else
#define MCUMGR_UART_DEV NULL
#endif

#define KICK_INITIAL_DELAY_MS  1500
#define KICK_INTERVAL_MS       2000
#define KICK_COUNT             5

static void uart_mcumgr_kick_thread(void *p1, void *p2, void *p3)
{
	ARG_UNUSED(p1);
	ARG_UNUSED(p2);
	ARG_UNUSED(p3);

	const struct device *dev = MCUMGR_UART_DEV;

	if (dev == NULL || !device_is_ready(dev)) {
		LOG_WRN("mcumgr UART device not ready");
		return;
	}

	k_sleep(K_MSEC(KICK_INITIAL_DELAY_MS));

	for (int i = 0; i < KICK_COUNT; i++) {
		LOG_INF("mcumgr UART RX kick %d/%d", i + 1, KICK_COUNT);
		uart_irq_rx_enable(dev);
		k_sleep(K_MSEC(KICK_INTERVAL_MS));
	}

	LOG_INF("mcumgr UART RX kick sequence complete");
}

K_THREAD_DEFINE(uart_kick_tid, 512,
		uart_mcumgr_kick_thread, NULL, NULL, NULL,
		K_PRIO_PREEMPT(14), 0, 0);
