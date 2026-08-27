#!/bin/bash
# Resilient mcumgr firmware upload for a flaky/bricked Crush80.
#
# The keyboard's SMP layer stalls after ~10-20 KiB. Killing mcumgr and
# retrying (WITHOUT unplugging) lets mcumgr resume from the last offset
# because the device keeps upload state in RAM.
#
# IMPORTANT: Do NOT unplug during upload. Each unplug resets progress to 0.
# Only unplug if told to (after upload completes, or if all retries fail).
#
# Usage:
#   bash scripts/resilient_upload.sh [firmware.signed.bin]
#   bash scripts/resilient_upload.sh --recovery [firmware.signed.bin]

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MCUMGR="${CRUSH80_MCUMGR:-$HOME/go/bin/mcumgr}"
STALL_TIMEOUT=20
MAX_RETRIES=100
ZERO_PROGRESS_LIMIT=5  # if N retries in a row make no new progress, suggest unplug
MTU=256              # smaller MTU to avoid buffer overflows on device
WINDOW=1             # single outstanding chunk — prevents stalls from lost ACKs

if [ "${1:-}" = "--recovery" ]; then
    shift || true
fi

IMAGE="${1:-$REPO_DIR/dist/crush80-zmk-app.signed.BACKUP.bin}"
if [ ! -f "$IMAGE" ]; then
    echo "ERROR: Firmware not found: $IMAGE"
    exit 1
fi

IMAGE_SIZE=$(wc -c < "$IMAGE" | tr -d ' ')
echo "╔══════════════════════════════════════════════════════════╗"
echo "║          CRUSH80 RESILIENT FIRMWARE UPLOAD              ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║ File: $(basename "$IMAGE")"
echo "║ Size: $IMAGE_SIZE bytes (~$((IMAGE_SIZE / 1024)) KiB)"
echo "║ Stall timeout: ${STALL_TIMEOUT}s"
echo "║                                                          "
echo "║ DO NOT UNPLUG during upload! Progress resets if you do. ║"
echo "║ The script auto-retries on stalls. Just wait.           ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

detect_port() {
    python3 -c "import glob; p=glob.glob('/dev/cu.usbmodem*'); print(p[0] if p else '')" 2>/dev/null || echo ""
}

wait_for_port() {
    local timeout="${1:-60}"
    local i=0
    while [ $i -lt "$timeout" ]; do
        i=$((i + 1))
        local p
        p=$(detect_port)
        if [ -n "$p" ]; then
            sleep 1
            p=$(detect_port)
            if [ -n "$p" ]; then
                printf "\n" >&2
                echo "$p"
                return 0
            fi
        fi
        printf "\r  Waiting for USB port... %ds/%ds" "$i" "$timeout" >&2
        sleep 1
    done
    printf "\n" >&2
    return 1
}

# --- Initial port detection ---
PORT=$(detect_port)
if [ -z "$PORT" ]; then
    echo "Plug in the keyboard now..."
    PORT=$(wait_for_port 60) || true
fi
if [ -z "$PORT" ]; then
    echo "ERROR: No USB port found."
    exit 1
fi
echo "Port: $PORT"
echo ""
echo "Starting upload. On stall, script auto-retries (no action needed from you)."
echo ""

# --- Main upload loop ---
ATTEMPT=0
UPLOAD_DONE=false
BEST_PERCENT="0.00%"
BEST_NUMERIC=0
ZERO_PROGRESS_COUNT=0

while [ $ATTEMPT -lt $MAX_RETRIES ] && [ "$UPLOAD_DONE" = false ]; do
    ATTEMPT=$((ATTEMPT + 1))
    CONN="dev=$PORT,baud=115200,mtu=$MTU"

    echo "━━━ Attempt $ATTEMPT | Best so far: $BEST_PERCENT ━━━"

    TMPOUT=$(mktemp /tmp/mcumgr_upload.XXXXXX)

    $MCUMGR --conntype serial --connstring "$CONN" image upload -w $WINDOW -t 15 "$IMAGE" > "$TMPOUT" 2>&1 &
    MCUMGR_PID=$!

    LAST_PERCENT=""
    STALL_COUNT=0
    THIS_ATTEMPT_PROGRESS=false

    while true; do
        if ! kill -0 $MCUMGR_PID 2>/dev/null; then
            break
        fi

        sleep 2

        CURRENT_PERCENT=$(tail -c 500 "$TMPOUT" 2>/dev/null | tr '\r' '\n' | grep -oE '[0-9]+\.[0-9]+%' | tail -1 || echo "")

        if [ "$CURRENT_PERCENT" = "$LAST_PERCENT" ] || [ -z "$CURRENT_PERCENT" ]; then
            STALL_COUNT=$((STALL_COUNT + 2))
            if [ $STALL_COUNT -ge $STALL_TIMEOUT ]; then
                echo "  STALL at ${CURRENT_PERCENT:-?} for ${STALL_TIMEOUT}s — retrying..."
                kill $MCUMGR_PID 2>/dev/null || true
                break
            fi
        else
            STALL_COUNT=0
            LAST_PERCENT="$CURRENT_PERCENT"
            THIS_ATTEMPT_PROGRESS=true

            # Track best percentage seen
            CUR_NUM=$(echo "$CURRENT_PERCENT" | grep -oE '[0-9]+\.[0-9]+' || echo "0")
            if [ "$(echo "$CUR_NUM > $BEST_NUMERIC" | bc 2>/dev/null || echo 0)" = "1" ]; then
                BEST_NUMERIC=$CUR_NUM
                BEST_PERCENT="$CURRENT_PERCENT"
            fi

            # Visual progress bar with bytes
            CUR_BYTES=$(echo "$CUR_NUM * $IMAGE_SIZE / 100" | bc 2>/dev/null | cut -d. -f1 || echo "?")
            BEST_BYTES=$(echo "$BEST_NUMERIC * $IMAGE_SIZE / 100" | bc 2>/dev/null | cut -d. -f1 || echo "?")
            BAR_W=25
            FILLED=$(echo "$CUR_NUM * $BAR_W / 100" | bc 2>/dev/null | cut -d. -f1 || echo 0)
            BAR=""
            for ((bb=0; bb<FILLED; bb++)); do BAR+="█"; done
            for ((bb=FILLED; bb<BAR_W; bb++)); do BAR+="░"; done
            printf "\r  [%s] %s (%s B) | peak: %s (%s B)  " "$BAR" "$CURRENT_PERCENT" "$CUR_BYTES" "$BEST_PERCENT" "$BEST_BYTES" >&2
        fi
    done

    # Reap process
    wait $MCUMGR_PID 2>/dev/null || true

    # Check for 100%
    FINAL=$(tail -c 500 "$TMPOUT" 2>/dev/null | tr '\r' '\n' | grep -oE '100\.00%' | tail -1 || echo "")
    if [ -n "$FINAL" ]; then
        echo ""
        echo ""
        echo "  ████████████████████████████████████████ 100% DONE!"
        UPLOAD_DONE=true
    fi

    rm -f "$TMPOUT"

    if [ "$UPLOAD_DONE" = true ]; then
        break
    fi

    # Track zero-progress retries
    if [ "$THIS_ATTEMPT_PROGRESS" = false ]; then
        ZERO_PROGRESS_COUNT=$((ZERO_PROGRESS_COUNT + 1))
    else
        ZERO_PROGRESS_COUNT=0
    fi

    # Show clear delta between attempts
    CUR_BEST_BYTES=$(echo "$BEST_NUMERIC * $IMAGE_SIZE / 100" | bc 2>/dev/null | cut -d. -f1 || echo "0")
    if [ "$THIS_ATTEMPT_PROGRESS" = true ]; then
        echo "    ↑ advanced to ${BEST_PERCENT} (${CUR_BEST_BYTES}/${IMAGE_SIZE} bytes)"
    else
        echo "    ✗ no new progress (still at ${BEST_PERCENT})"
    fi
    echo ""

    # If too many retries with no progress, the SMP layer is truly dead
    if [ $ZERO_PROGRESS_COUNT -ge $ZERO_PROGRESS_LIMIT ]; then
        echo ""
        echo "  !! $ZERO_PROGRESS_LIMIT retries with no progress."
        echo "  !! SMP layer seems dead. UNPLUG now, wait 5s, REPLUG."
        echo "  !! (Progress will reset — this is a last resort.)"
        echo ""
        echo "  Waiting for unplug..."

        # Wait for port to disappear
        local_wait=0
        while [ $local_wait -lt 60 ]; do
            local_wait=$((local_wait + 1))
            p=$(detect_port)
            if [ -z "$p" ]; then
                break
            fi
            sleep 1
        done

        echo "  Waiting for replug..."
        sleep 3
        PORT=$(wait_for_port 60) || true
        if [ -z "$PORT" ]; then
            echo "ERROR: Port not found. Rerun script after plugging in."
            exit 1
        fi
        ZERO_PROGRESS_COUNT=0
        BEST_PERCENT="0.00%"
        BEST_NUMERIC=0
        echo "  Reconnected. Progress reset to 0%. Starting over..."
        echo ""
    else
        # Normal retry: just pause briefly, keep same port
        sleep 3
        # Verify port still exists
        PORT=$(detect_port)
        if [ -z "$PORT" ]; then
            echo "  Port disappeared! Waiting..."
            PORT=$(wait_for_port 60) || true
            if [ -z "$PORT" ]; then
                echo "ERROR: Port gone. Rerun script."
                exit 1
            fi
        fi
    fi
done

if [ "$UPLOAD_DONE" = false ]; then
    echo "ERROR: Upload did not complete after $MAX_RETRIES attempts."
    exit 1
fi

# --- Post-upload ---
echo ""
echo "=== Upload complete! Activating new firmware... ==="
echo ""
sleep 2

CONN="dev=$PORT,baud=115200"
HASH=$($MCUMGR --conntype serial --connstring "$CONN" image list 2>/dev/null | grep -A3 "slot=1" | grep hash | awk '{print $2}' || echo "")

if [ -n "$HASH" ]; then
    echo "Slot 1 hash: ${HASH:0:16}..."
    $MCUMGR --conntype serial --connstring "$CONN" image test "$HASH" 2>/dev/null || true
    echo "Resetting for MCUboot swap..."
    $MCUMGR --conntype serial --connstring "$CONN" reset 2>/dev/null || true
    echo "Waiting 14s for swap..."
    sleep 14
    PORT=$(detect_port)
    if [ -n "$PORT" ]; then
        CONN="dev=$PORT,baud=115200"
        $MCUMGR --conntype serial --connstring "$CONN" image confirm "" 2>/dev/null || true
        echo "Confirmed! Testing..."
        $MCUMGR --conntype serial --connstring "$CONN" echo "hello" 2>/dev/null && echo "KEYBOARD IS ALIVE!" || echo "No echo yet — try typing."
    else
        echo "Port not found after reset. Unplug/replug — MCUboot swaps on cold boot."
    fi
else
    echo "Could not get hash. Try: unplug, wait 5s, replug."
    echo "MCUboot should swap to new firmware on cold boot."
fi

echo ""
echo "=== Done ==="
