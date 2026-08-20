#!/bin/bash
# Flash Wobkey Crush 80 ZMK firmware.
# Run from repo root in WSL: bash flash.sh
#
# Prerequisites:
#   - Keyboard plugged in via USB-C, in USB mode (not BT/2.4G)
#   - Build artifacts in dist/  (run bash build.sh first)
#   - udev rules installed:
#       sudo cp docs/99-wobkey-crush80.rules /etc/udev/rules.d/
#       sudo udevadm control --reload
#
# Usage:
#   bash flash.sh          — full flash (Stage 1 + Stage 2)
#   bash flash.sh stage1   — OTA bridge only (needed for first-time flash)
#   bash flash.sh stage2   — ZMK app only (requires Stage 1 already done)
#   bash flash.sh restore  — revert to stock firmware

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
STAGE="${1:-all}"

export PATH="/usr/bin:/usr/local/bin:$HOME/.local/bin:$PATH"

# ── Locate dist/ artifacts ───────────────────────────────────────────────────
DIST="$REPO_DIR/dist"
if [ ! -f "$DIST/crush80-zmk-app.signed.bin" ]; then
    echo "ERROR: dist/ not found or incomplete. Run: bash build.sh"
    exit 1
fi

# ── Locate mcumgr ────────────────────────────────────────────────────────────
MCUMGR="$HOME/go/bin/mcumgr"
if [ ! -x "$MCUMGR" ]; then
    echo "mcumgr not found. Installing..."
    go install github.com/apache/mynewt-mcumgr-cli/mcumgr@latest
fi

# ── Helper: find the keyboard serial port ────────────────────────────────────
find_serial_port() {
    for dev in /dev/ttyACM0 /dev/ttyACM1 /dev/ttyUSB0; do
        if [ -e "$dev" ]; then
            echo "$dev"
            return 0
        fi
    done
    echo ""
}

mcumgr_upload() {
    local port="$1"
    local image="$2"
    echo "  Uploading $image..."
    "$MCUMGR" --conntype serial --connstring "dev=$port,baud=115200" \
        image upload "$image"
    echo "  Confirming..."
    "$MCUMGR" --conntype serial --connstring "dev=$port,baud=115200" \
        image confirm
    echo "  Resetting..."
    "$MCUMGR" --conntype serial --connstring "dev=$port,baud=115200" \
        reset
}

# ── Stage 1: OTA bridge ──────────────────────────────────────────────────────
if [ "$STAGE" = "all" ] || [ "$STAGE" = "stage1" ]; then
    echo ""
    echo "========================================"
    echo "  Stage 1: Flashing OTA bridge"
    echo "  (keyboard must be in USB mode)"
    echo "========================================"
    echo ""
    python3 "$REPO_DIR/scripts/flash_ota.py" "$DIST/crush80-ota-bridge.bin"
    echo ""
    echo "  OTA bridge flashed. Waiting 5s for USB re-enumeration..."
    sleep 5
fi

# ── Stage 2: ZMK application ─────────────────────────────────────────────────
if [ "$STAGE" = "all" ] || [ "$STAGE" = "stage2" ]; then
    echo ""
    echo "========================================"
    echo "  Stage 2: Flashing ZMK application"
    echo "========================================"
    echo ""
    PORT="$(find_serial_port)"
    if [ -z "$PORT" ]; then
        echo "ERROR: No serial device found."
        echo "  The keyboard should appear as /dev/ttyACM0 after Stage 1."
        echo "  Check: ls /dev/ttyACM*"
        exit 1
    fi
    echo "  Found keyboard at $PORT"
    mcumgr_upload "$PORT" "$DIST/crush80-zmk-app.signed.bin"
    echo ""
    echo "  ZMK application flashed."
    echo "  The keyboard will reboot and appear as 'Crush 80' over USB and Bluetooth."
fi

# ── Restore to stock firmware ─────────────────────────────────────────────────
if [ "$STAGE" = "restore" ]; then
    echo ""
    echo "========================================"
    echo "  Restoring stock Evision firmware"
    echo "========================================"
    echo ""
    # Delegate to restore_stock.sh which handles firmware path prompting
    RESTORE_ARGS=""
    if [ -n "${2:-}" ] && [ -f "${2:-}" ]; then
        RESTORE_ARGS="$2"
    fi
    bash "$REPO_DIR/restore_stock.sh" $RESTORE_ARGS
fi

echo ""
echo "Done."
