#!/bin/bash
# Flash Crush 80 ZMK firmware via mcumgr
# Usage: bash flash.sh [--build] [--skip-confirm]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
DIST="$REPO_DIR/dist"
PORT="/dev/cu.usbmodem1101"
MCUMGR="$HOME/go/bin/mcumgr"
CONN="dev=$PORT,baud=115200"

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
