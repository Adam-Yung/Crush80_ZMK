#!/bin/bash
# Flash any signed firmware binary to the Crush 80
# Usage: bash scripts/flash_bin.sh path/to/firmware.signed.bin
# For recovery (keyboard dead): bash scripts/flash_bin.sh --recovery path/to/firmware.signed.bin
set -e

MCUMGR="${CRUSH80_MCUMGR:-$HOME/go/bin/mcumgr}"
RECOVERY=false

if [ "$1" = "--recovery" ]; then
    RECOVERY=true
    shift
fi

IMAGE="${1:?Usage: bash scripts/flash_bin.sh [--recovery] <firmware.signed.bin>}"
if [ ! -f "$IMAGE" ]; then
    echo "ERROR: File not found: $IMAGE"
    exit 1
fi

echo "=== Flash: $(basename "$IMAGE") ($(wc -c < "$IMAGE" | tr -d ' ') bytes) ==="

if [ "$RECOVERY" = true ]; then
    echo ""
    echo "RECOVERY MODE: Unplug keyboard, then plug it in."
    echo "Waiting for USB port..."
    PORT=""
    for i in $(seq 1 120); do
        P=$(python3 -c "import glob; p=glob.glob('/dev/cu.usbmodem*'); print(p[0] if p else '')")
        if [ -n "$P" ]; then
            sleep 2
            P2=$(python3 -c "import glob; p=glob.glob('/dev/cu.usbmodem*'); print(p[0] if p else '')")
            if [ -n "$P2" ]; then
                PORT="$P2"
                break
            fi
        fi
        sleep 0.5
    done
    if [ -z "$PORT" ]; then
        echo "TIMEOUT. Try again - plug in faster after running script."
        exit 1
    fi
else
    PORT=$(python3 -c "import glob; p=glob.glob('/dev/cu.usbmodem*'); print(p[0] if p else '')")
    if [ -z "$PORT" ]; then
        echo "ERROR: Keyboard not found on USB. Use --recovery flag if keyboard is dead."
        exit 1
    fi
fi

CONN="dev=$PORT,baud=115200"
echo "Port: $PORT"
echo "Uploading..."
$MCUMGR --conntype serial --connstring "$CONN" image upload "$IMAGE"

HASH=$($MCUMGR --conntype serial --connstring "$CONN" image list | grep -A3 "slot=1" | grep hash | awk '{print $2}')
if [ -n "$HASH" ]; then
    echo "Swapping to: ${HASH:0:16}..."
    $MCUMGR --conntype serial --connstring "$CONN" image test "$HASH"
    $MCUMGR --conntype serial --connstring "$CONN" reset || true
    echo "Waiting 12s for MCUboot swap..."
    sleep 12
    $MCUMGR --conntype serial --connstring "$CONN" image confirm ""
fi

echo ""
echo "=== Done ==="
$MCUMGR --conntype serial --connstring "$CONN" echo "ok" 2>/dev/null && echo "Keyboard responding!" || echo "Note: keyboard may need manual confirm"
