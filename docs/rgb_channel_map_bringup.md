# Per-Key RGB Channel Map Bring-Up

The AW20216S LED driver is written and the SPI pins are confirmed. The remaining
step before RGB works is mapping **which channel index lights which physical key**.

This guide walks through the bring-up procedure to fill in the
`crush80_led_sw[]` and `crush80_led_cs[]` lookup tables in
`zmk/drivers/led/aw20216s.c`.

---

## Background

The Crush 80 has two AW20216S chips sharing CLK and MOSI, each with its own CS:

| Chip | CS pin | Max channels |
|------|--------|-------------|
| Chip 0 | PE0 | 216 (9 rows × 24 cols) |
| Chip 1 | PC0 | 216 (9 rows × 24 cols) |

Each AW20216S channel is addressed as:
```
PWM_address = sw_row * 24 + cs_col
             where sw_row ∈ [0, 8],  cs_col ∈ [0, 23]
```

For an RGB LED with three leads (R, G, B), each colour occupies a separate channel.
A single-colour (white) LED occupies one channel.

The goal: for every physical key, determine `(chip, sw_row, cs_col)` for each
colour channel. Then update the lookup tables so `aw20216s_set_rgb(led_idx, r, g, b)`
drives the correct three channels.

---

## Step 1: Add the channel-scan test mode

Add the following to `zmk/drivers/led/aw20216s.c`, after the `aw20216s_init` function.
This replaces the normal RGB thread with a sequential scanner that lights one channel
at a time and prints the address over serial.

```c
/*
 * Channel scan test — compile with CONFIG_AW20216S_CHANNEL_SCAN=y
 * Lights each (chip, sw, cs) combination for SCAN_DWELL_MS, then advances.
 * Watch serial output to record which key lights up at each address.
 */
#ifdef CONFIG_AW20216S_CHANNEL_SCAN

#define SCAN_DWELL_MS  400   /* time each channel is lit — adjust to taste */

static void aw20216s_channel_scan_thread(void *p1, void *p2, void *p3)
{
    ARG_UNUSED(p1); ARG_UNUSED(p2); ARG_UNUSED(p3);

    const struct device *dev0 = DEVICE_DT_GET(DT_NODELABEL(aw20216s0));
    const struct device *dev1 = DEVICE_DT_GET(DT_NODELABEL(aw20216s1));

    if (!device_is_ready(dev0) || !device_is_ready(dev1)) {
        printk("AW20216S: device not ready\n");
        return;
    }

    k_sleep(K_SECONDS(2));  /* wait for USB serial to connect */
    printk("\n=== AW20216S CHANNEL SCAN ===\n");
    printk("Format: CHIP sw_row cs_col  PWM_addr\n");
    printk("Note which physical key lights up at each address.\n\n");

    for (int chip = 0; chip < 2; chip++) {
        const struct device *dev = (chip == 0) ? dev0 : dev1;
        for (int sw = 0; sw < 9; sw++) {
            for (int cs = 0; cs < 24; cs++) {
                uint16_t pwm_addr = sw * 24 + cs;

                /* All LEDs off */
                aw20216s_set_all_rgb(dev0, 0, 0, 0);
                aw20216s_set_all_rgb(dev1, 0, 0, 0);
                aw20216s_update(dev0);
                aw20216s_update(dev1);

                /* Light this single channel at full white */
                struct aw20216s_data *data = dev->data;
                if (pwm_addr < AW20216S_PWM_CHANNELS) {
                    data->pwm_buf[pwm_addr] = 255;
                    data->dirty = true;
                    aw20216s_update(dev);
                }

                printk("CHIP%d  SW%d  CS%02d  addr=0x%02X\n",
                       chip, sw, cs, pwm_addr);

                k_sleep(K_MSEC(SCAN_DWELL_MS));
            }
        }
    }

    printk("\n=== SCAN COMPLETE ===\n");
    /* Hold last channel lit */
    while (1) { k_sleep(K_SECONDS(10)); }
}

K_THREAD_DEFINE(aw20216s_scan_tid, 1024, aw20216s_channel_scan_thread,
                NULL, NULL, NULL, K_PRIO_PREEMPT(9), 0, 0);

#endif /* CONFIG_AW20216S_CHANNEL_SCAN */
```

Add the Kconfig option to `zmk/drivers/led/Kconfig`:
```kconfig
config AW20216S_CHANNEL_SCAN
    bool "AW20216S channel scan mode (bring-up only)"
    depends on AW20216S
    help
      Replaces normal RGB operation with a sequential channel scanner.
      Lights each (chip, sw_row, cs_col) for 400ms and prints the address
      over serial. Use during bring-up to build the channel map.
      Disable for production builds.
```

---

## Step 2: Build with scan mode enabled

Add to `build.sh` override section (or a temporary `conf/scan.conf` file):

```
CONFIG_AW20216S_CHANNEL_SCAN=y
CONFIG_AW20216S=y
CONFIG_LOG=y
CONFIG_UART_CONSOLE=y
```

Then build and flash:
```bash
# Build scan firmware
bash build.sh --skip-bridge

# Flash just the app (bridge already installed)
bash flash.sh stage2
```

---

## Step 3: Run the scan

Connect to the keyboard's USB serial port:
```bash
screen /dev/ttyACM0 115200
# or:
minicom -D /dev/ttyACM0 -b 115200
```

The scanner will print lines like:
```
CHIP0  SW0  CS00  addr=0x00
CHIP0  SW0  CS01  addr=0x01
CHIP0  SW0  CS02  addr=0x02
...
```

### Recording the map

Keep a physical keyboard diagram handy. For each line, note which LED lights up.
Use a spreadsheet or the template below.

You only need to record entries where an LED actually lights up — most addresses
will be dark (the PCB doesn't route all 432 possible channels).

**Scan speed tip:** Increase `SCAN_DWELL_MS` to 800 if 400ms feels rushed, or
decrease to 200 for faster scanning if the LEDs are easy to distinguish.

---

## Step 4: Cross-reference with firmware table

The original firmware has a LED index table at offset `0x1C260` in
`firmware/v2_patched.bin`. Run this to extract it:

```python
import struct

with open("firmware/v2_patched.bin", "rb") as f:
    fw = bytearray(f.read())

print("=== Firmware LED index table (0x1C260) ===")
print("Format: matrix_col → LED_index (0xFF = empty slot)")
for i in range(0, 91, 8):
    row = fw[0x1C260 + i : 0x1C260 + i + 8]
    print(f"  [{i:3d}] " + " ".join(f"{b:3d}" if b != 0xFF else " -- " for b in row))
```

This table shows the stock firmware's ordering. Use it as a cross-reference —
the stock firmware lit LEDs in this index order when cycling effects.

---

## Step 5: Build the lookup tables

Open `zmk/drivers/led/aw20216s.c` and find the placeholder tables:
```c
static const uint8_t crush80_led_sw[AW20216S_NUM_LEDS] = { ... };
static const uint8_t crush80_led_cs[AW20216S_NUM_LEDS] = { ... };
```

Replace the placeholder values with your recorded findings.

**Format:** `led_idx` is the logical LED index (0-153, ordered left-to-right,
top-to-bottom). For each key, you need to record which `(chip, sw_row, cs_col)`
maps to it.

For an RGB LED with separate R/G/B channels:
```c
/* Example: key ESC = chip 0, sw_row=0, cs_col=0 (Red)
 *                            sw_row=0, cs_col=1 (Green)
 *                            sw_row=0, cs_col=2 (Blue)
 * led_idx=0 → R channel: aw20216s_set_rgb(dev, 0, r, g, b)
 *   → sets pwm_buf[0*24+0]=r, pwm_buf[0*24+1]=g, pwm_buf[0*24+2]=b
 */
```

Currently the driver writes R to `base+0`, G to `base+1`, B to `base+2`
where `base = sw_row * 24 + cs_col`. Adjust the `+1`/`+2` offsets in
`aw20216s_set_rgb()` if the PCB wires colours differently.

---

## Step 6: Map template

Use this as a recording template during the scan. Fill in sw/cs for each key:

```
Key          led_idx  chip  sw  cs(R)  cs(G)  cs(B)
─────────────────────────────────────────────────────
ESC              0     ?    ?    ?      ?      ?
F1               1     ?    ?    ?      ?      ?
F2               2     ?    ?    ?      ?      ?
...
` (grave)       16     ?    ?    ?      ?      ?
1               17     ?    ?    ?      ?      ?
...
Tab             32     ?    ?    ?      ?      ?
Q               33     ?    ?    ?      ?      ?
...
CapsLk          48     ?    ?    ?      ?      ?
A               49     ?    ?    ?      ?      ?
...
LShift          61     ?    ?    ?      ?      ?
...
LCtrl           74     ?    ?    ?      ?      ?
```

---

## Step 7: Validate

After updating the tables, rebuild without `CONFIG_AW20216S_CHANNEL_SCAN`:

```bash
bash build.sh --skip-bridge
bash flash.sh stage2
```

Then press keys — the echo/ripple effect should light each key exactly where
you pressed, with the glow spreading from that key.

If a key lights the wrong LED: swap the `led_idx` entries for those two keys in
the lookup table.

If a key shows wrong colour (e.g., blue when expecting white): the R/G/B
channel offsets are wrong — swap the `+0`/`+1`/`+2` in `aw20216s_set_rgb()`.

---

## Notes on Two-Chip Operation

The 154-LED count splits across the two chips. The split point depends on the PCB
routing and cannot be determined without the scan. Likely splits:

- **Chip 0 (PE0):** function row + number row + QWERTY + home row = ~58 keys × 3 = ~174 channels (< 216 ✓)
- **Chip 1 (PC0):** shift row + bottom row + side LEDs = ~30+ keys × 3 = ~90+ channels (< 216 ✓)

Or the split may follow a physical PCB zone rather than keyboard rows.

The scan will reveal this automatically — once you see chip 0 channels going dark
and chip 1 starting, you'll know the split point.

---

## Quick reference: AW20216S register layout

| Page | Address | Contents |
|------|---------|----------|
| 0x00 (GCR) | 0x00 | Enable bit (bit 0) |
| 0x00 (GCR) | 0x01 | Global current (0x00–0xFF) |
| 0x00 (GCR) | 0x2F | Write 0xAE to reset |
| 0x01 (PWM) | 0x00–0xD7 | Per-channel brightness (0=off, 255=full) |
| 0x02 (scaling) | 0x00–0xD7 | Per-channel current scale (set all to 0xFF) |

Channel address in PWM page = `sw_row * 24 + cs_col`

Page select: write `0xFD` then page number before accessing any register.
(Confirmed: `0xFD 0x00` page select pattern found at 3 locations in stock firmware.)
