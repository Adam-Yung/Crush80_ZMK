# zmk/drivers/led_strip/led_strip_b91_spi.c

WS2812 strip driver over the B91 PSPI and DMA channel 4. Overview, risks and hardware model: `docs/features/rgb.md`.

**Why SPI bytes instead of bit-banging:** 6 MHz SPI, one byte per WS2812 bit (`0xF0`/`0xC0`), gives the 0.4 µs / 0.8 µs pulse shapes with no CPU timing and no interrupt lock.

**Why the clock is not routed to a pin:** PSPI CLK would be PB5, a matrix column. Only MOSI (PB7) is muxed; the peripheral clocks internally.

**Why `irq_lock()` only around the power GPIO:** PC0, PC1 and PC4 are matrix columns on the same GPIO port; the read-modify-write of the output register must not race the matrix scan.

**Timeout path:** semaphore wait bounded by 4/3 µs per byte plus 2 ms. On expiry: DMA channel stopped, PSPI reset through the reset register, interrupt re-enabled, LED power cut, `-ETIMEDOUT`. The next frame retries. This is the property the 2026-08-27 driver lacked.

**Power:** off whenever the whole frame is black (also what makes deep sleep dark); on with a 2 ms settle before the first frame.
