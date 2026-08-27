#!/bin/bash
# Crush80 ZMK Firmware Update Script
# Usage: bash update.sh [--build] [--firmware PATH]
#
# Flashes ZMK firmware onto a running Crush80 keyboard via mcumgr DFU.
# The keyboard must already be running ZMK (with MCUmgr support).
#
# Firmware location (checked in order):
#   1. --firmware PATH argument
#   2. CRUSH80_FIRMWARE environment variable
#   3. dist/crush80-zmk-app.signed.bin (default)
#
# What this does:
#   1. (optional) Rebuilds firmware if --build is passed
#   2. Detects the keyboard serial port
#   3. Uploads firmware via mcumgr
#   4. Marks for test boot, prompts user to unplug/replug
#   5. Auto-confirm happens on next boot (mcuboot_confirm.c)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
FIRMWARE="${CRUSH80_FIRMWARE:-$REPO_DIR/dist/crush80-zmk-app.signed.bin}"
DO_BUILD=false

for arg in "$@"; do
    case $arg in
        --build) DO_BUILD=true ;;
        --firmware)
            shift
            FIRMWARE="$1"
            ;;
        --firmware=*)
            FIRMWARE="${arg#--firmware=}"
            ;;
        --help|-h)
            echo "Usage: bash update.sh [--build] [--firmware PATH]"
            echo ""
            echo "  --build           Rebuild firmware before flashing"
            echo "  --firmware PATH   Path to .signed.bin file"
            echo ""
            echo "Environment variables:"
            echo "  CRUSH80_FIRMWARE  Path to firmware .signed.bin (alternative to --firmware)"
            echo "  CRUSH80_KEYMAP    Path to .keymap file (used by --build)"
            echo ""
            echo "After flashing, UNPLUG and REPLUG the keyboard for MCUboot swap."
            exit 0
            ;;
    esac
done

# Find mcumgr
MCUMGR=""
if command -v mcumgr &>/dev/null; then
    MCUMGR="mcumgr"
elif [ -f "$HOME/go/bin/mcumgr" ]; then
    MCUMGR="$HOME/go/bin/mcumgr"
else
    echo "ERROR: mcumgr not found. Install with:"
    echo "  go install github.com/apache/mynewt-mcumgr-cli/mcumgr@latest"
    exit 1
fi

# Optional rebuild
if [ "$DO_BUILD" = true ]; then
    echo "Building firmware..."
    bash "$REPO_DIR/build.sh" --skip-bridge
    echo ""
fi

# Check firmware exists
if [ ! -f "$FIRMWARE" ]; then
    echo "ERROR: Firmware not found at $FIRMWARE"
    echo "       Run 'bash build.sh' first."
    exit 1
fi

echo "=== Crush80 ZMK Firmware Update ==="
echo ""
echo "Firmware: $FIRMWARE ($(wc -c < "$FIRMWARE" | tr -d ' ') bytes)"
echo ""

# Detect serial port (wait up to 15 seconds)
echo "Looking for keyboard serial port..."
echo "  (Make sure the keyboard is plugged in via USB)"
echo ""

SERIAL_PORT=""
WAIT_SECS=15

for i in $(seq 1 $WAIT_SECS); do
    SERIAL_PORT=$(python3 -c "import glob; p=glob.glob('/dev/cu.usbmodem*') or glob.glob('/dev/ttyACM*'); print(p[0] if p else '')" 2>/dev/null)

    if [ -n "$SERIAL_PORT" ]; then
        break
    fi

    printf "\r  Waiting... %d/%ds" "$i" "$WAIT_SECS"
    sleep 1
done

echo ""

if [ -z "$SERIAL_PORT" ]; then
    echo "ERROR: No serial device found after ${WAIT_SECS}s."
    echo "       Make sure the keyboard is in bootloader mode (Fn+Esc)."
    exit 1
fi

echo "  Found: $SERIAL_PORT"
echo ""

# Toggle DTR to wake mcumgr transport
python3 -c "
import serial, time
s = serial.Serial('$SERIAL_PORT', 115200, timeout=1)
s.dtr = True; time.sleep(0.5); s.close()
" 2>/dev/null || true

# Flash firmware
CONN="dev=$SERIAL_PORT,baud=115200"

echo "Uploading firmware..."
$MCUMGR --conntype serial --connstring "$CONN" image upload "$FIRMWARE"
echo ""

echo "Getting slot 1 hash..."
HASH=$($MCUMGR --conntype serial --connstring "$CONN" image list | grep -A2 "slot=1" | grep hash | awk '{print $2}')
if [ -z "$HASH" ]; then
    echo "ERROR: Could not find slot 1 hash. Upload may have failed."
    exit 1
fi
echo "  Hash: $HASH"

echo "Marking image for test boot..."
$MCUMGR --conntype serial --connstring "$CONN" image test "$HASH"
echo ""

echo "=== Upload complete! ==="
echo ""
echo "  IMPORTANT: Unplug the keyboard USB cable, wait 2 seconds, then plug back in."
echo "  MCUboot will swap to the new firmware on cold boot (~12 seconds)."
echo "  The firmware auto-confirms after successful boot."
echo ""
echo "  If something goes wrong, unplug/replug again — MCUboot reverts automatically"
echo "  if the new firmware fails to confirm within 11 seconds."
