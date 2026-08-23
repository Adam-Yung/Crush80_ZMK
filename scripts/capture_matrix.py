#!/usr/bin/env python3
"""
Capture ZMK kscan debug log from serial console.
Parses the actual ZMK log format:
  zmk_physical_layouts_kscan_process_msgq: Row: X, col: Y, position: Z, pressed: true/false

Usage:
  python3 scripts/capture_matrix.py [/dev/cu.usbmodem1101] [duration_seconds]

Press keys on the keyboard one at a time (left-to-right, top-to-bottom).
Press Ctrl+C to stop and dump the captured map.
"""

import serial
import sys
import re
import time

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/cu.usbmodem1101"
DURATION = int(sys.argv[2]) if len(sys.argv) > 2 else 0
BAUD = 115200
LOG_FILE = "capture_matrix_log.txt"

PATTERN = re.compile(
    r"Row:\s*(\d+),\s*col:\s*(\d+),\s*position:\s*(\d+),\s*pressed:\s*(true|false)"
)

def main():
    print(f"Connecting to {PORT} at {BAUD} baud...")
    print("Press keys one at a time, left-to-right, top-to-bottom.")
    if DURATION:
        print(f"Will capture for {DURATION} seconds.")
    else:
        print("Press Ctrl+C to stop.\n")
    print(f"{'#':>3}  {'Row':>3}  {'Col':>3}  {'Pos':>4}  {'Event':<8}")
    print("-" * 35)

    presses = []
    count = 0

    try:
        ser = serial.Serial(PORT, BAUD, timeout=0.5)
        ser.dtr = True
        ser.rts = True
        time.sleep(1)
        ser.reset_input_buffer()

        start = time.time()

        with open(LOG_FILE, "w") as logf:
            logf.write("# Crush 80 matrix capture\n")
            logf.write("# Format: press_num row col position\n\n")

            while True:
                if DURATION and (time.time() - start > DURATION):
                    break

                line = ser.readline().decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                m = PATTERN.search(line)
                if m:
                    row = int(m.group(1))
                    col = int(m.group(2))
                    pos = int(m.group(3))
                    pressed = m.group(4) == "true"

                    if pressed:
                        count += 1
                        presses.append((row, col, pos))
                        line_out = f"{count:>3}  {row:>3}  {col:>3}  {pos:>4}  PRESS"
                        print(line_out)
                        logf.write(f"{count} {row} {col} {pos}\n")
                        logf.flush()

    except KeyboardInterrupt:
        pass
    except serial.SerialException as e:
        print(f"Serial error: {e}")
        sys.exit(1)

    print(f"\n\n{'='*60}")
    print(f"Captured {len(presses)} key presses:")
    print(f"{'='*60}")
    print(f"{'#':>3}  {'Row':>3}  {'Col':>3}  {'Position':>8}")
    print("-" * 30)
    for i, (r, c, p) in enumerate(presses):
        print(f"{i+1:>3}  {r:>3}  {c:>3}  {p:>8}")
    print(f"\nFull log saved to {LOG_FILE}")


if __name__ == "__main__":
    main()
