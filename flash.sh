#!/bin/bash
# Flash Crush 80 ZMK firmware via mcumgr
# Usage: bash flash.sh [--build] [--skip-confirm]
#
# Environment variables (all optional, with sensible defaults):
#   CRUSH80_PORT       Serial port (default: /dev/cu.usbmodem1101)
#   CRUSH80_MCUMGR    Path to mcumgr binary (default: ~/go/bin/mcumgr)
#   CRUSH80_ZMK_CONFIG  ZMK config dir (used by build.sh if --build)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
DIST="$REPO_DIR/dist"
PORT="${CRUSH80_PORT:-$(python3 -c "import glob; p=glob.glob('/dev/cu.usbmodem*') or glob.glob('/dev/ttyACM*'); print(p[0] if p else '')" 2>/dev/null)}"
MCUMGR="${CRUSH80_MCUMGR:-$HOME/go/bin/mcumgr}"
CONN="dev=$PORT,baud=115200"

# Validate mcumgr exists
if [ ! -x "$MCUMGR" ]; then
    echo "ERROR: mcumgr not found at $MCUMGR"
    echo "Set CRUSH80_MCUMGR or install: go install github.com/apache/mynewt-mcumgr-cli/mcumgr@latest"
    exit 1
fi

# Auto-detect serial port if default doesn't exist
if [ ! -e "$PORT" ]; then
    DETECTED=$(python3 -c "import glob; p=glob.glob('/dev/cu.usbmodem*') or glob.glob('/dev/ttyACM*'); print(p[0] if p else '')" 2>/dev/null || true)
    if [ -n "$DETECTED" ]; then
        PORT="$DETECTED"
        CONN="dev=$PORT,baud=115200"
        echo "Auto-detected port: $PORT"
    else
        echo "ERROR: Keyboard not found at $PORT"
        read -rp "Enter serial port path (or plug in keyboard and retry): " user_port
        if [ -n "$user_port" ] && [ -e "$user_port" ]; then
            PORT="$user_port"
            CONN="dev=$PORT,baud=115200"
        else
            echo "No valid port. Exiting."
            exit 1
        fi
    fi
fi

# Parse args
BUILD=false
SKIP_CONFIRM=false
for arg in "$@"; do
    case $arg in
        --build) BUILD=true ;;
        --skip-confirm) SKIP_CONFIRM=true ;;
    esac
done

if [ "$BUILD" = true ]; then
    echo "Building..."
    bash "$REPO_DIR/build.sh" --skip-bridge --skip-mcuboot
fi

IMAGE="$DIST/crush80-zmk-app.signed.bin"
if [ ! -f "$IMAGE" ]; then
    echo "ERROR: $IMAGE not found. Run: bash build.sh --skip-bridge --skip-mcuboot"
    exit 1
fi

echo "Uploading $(basename "$IMAGE")..."
python3 -c "import serial,time; s=serial.Serial('$PORT',115200,timeout=0.5); s.dtr=True; time.sleep(0.3); s.close()" 2>/dev/null || true
$MCUMGR --conntype serial --connstring "$CONN" image upload "$IMAGE"

echo ""
echo "Getting slot 1 hash..."
HASH=$($MCUMGR --conntype serial --connstring "$CONN" image list | grep -A2 "slot=1" | grep hash | awk '{print $2}')
if [ -z "$HASH" ]; then
    echo "ERROR: Could not find slot 1 hash"
    exit 1
fi
echo "  Hash: $HASH"

echo "Marking image for test boot..."
$MCUMGR --conntype serial --connstring "$CONN" image test "$HASH"

echo "Resetting keyboard..."
$MCUMGR --conntype serial --connstring "$CONN" reset || true

if [ "$SKIP_CONFIRM" = false ]; then
    echo "Waiting 12s for MCUboot swap..."
    sleep 12
    echo "Confirming image..."
    $MCUMGR --conntype serial --connstring "$CONN" image confirm ""
fi

echo ""
echo "Done! Firmware updated successfully."
$MCUMGR --conntype serial --connstring "$CONN" echo "hello"
