#!/bin/bash
# Crush80 ZMK Firmware Update Script
# Usage: bash update.sh [--build]
#
# Prerequisites:
#   - Keyboard is in bootloader mode (press Fn+Esc)
#   - mcumgr is installed (go install github.com/apache/mynewt-mcumgr-cli/mcumgr@latest)
#   - Firmware has been built (bash build.sh)
#
# What this does:
#   1. (optional) Rebuilds firmware if --build is passed
#   2. Waits for MCUboot serial device to appear
#   3. Flashes dist/crush80-zmk-app.signed.bin via mcumgr
#   4. Resets the keyboard

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
FIRMWARE="$REPO_DIR/dist/crush80-zmk-app.signed.bin"
DO_BUILD=false

for arg in "$@"; do
    case $arg in
        --build) DO_BUILD=true ;;
        --help|-h)
            echo "Usage: bash update.sh [--build]"
            echo ""
            echo "  --build    Rebuild firmware before flashing"
            echo ""
            echo "Steps:"
            echo "  1. Press Fn+Esc on the keyboard (enters bootloader)"
            echo "  2. Run: bash update.sh"
            echo "  3. Keyboard reboots with new firmware in ~5 seconds"
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
echo "Waiting for MCUboot serial device..."
echo "  (Press Fn+Esc on the keyboard if you haven't already)"
echo ""

SERIAL_PORT=""
WAIT_SECS=15

for i in $(seq 1 $WAIT_SECS); do
    case "$(uname)" in
        Darwin)
            SERIAL_PORT=$(find /dev -name "cu.usbmodem*" 2>/dev/null | head -1)
            ;;
        Linux)
            SERIAL_PORT=$(find /dev -name "ttyACM*" 2>/dev/null | head -1)
            ;;
    esac

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

# Flash firmware
CONN="dev=$SERIAL_PORT,baud=115200"

echo "Uploading firmware..."
$MCUMGR --conntype serial --connstring "$CONN" image upload "$FIRMWARE"
echo ""

echo "Confirming image..."
$MCUMGR --conntype serial --connstring "$CONN" image confirm ""
echo ""

echo "Resetting keyboard..."
$MCUMGR --conntype serial --connstring "$CONN" reset
echo ""

echo "=== Update complete! ==="
echo "  Keyboard will reboot with new firmware in ~2 seconds."
echo "  If it doesn't come back within 30s, MCUboot will auto-revert."
