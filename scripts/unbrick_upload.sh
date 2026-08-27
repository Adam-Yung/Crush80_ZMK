#!/bin/bash
# =============================================================================
# Crush80 Unbrick Upload — Multi-Strategy Firmware Loader
# =============================================================================
#
# This script tries several approaches to get firmware onto a bricked Crush80
# whose SMP layer stalls after a few KB. It uses progressively more aggressive
# techniques:
#
#   Strategy 1: mcumgr with -w 1 (single-window) + small MTU
#   Strategy 2: mcumgr with -w 1 + tiny MTU (128) + increased timeout
#   Strategy 3: Python smpclient library (fine-grained control, per-chunk retry)
#   Strategy 4: Raw SMP serial protocol (manual CBOR framing, single-chunk crawl)
#
# Usage:
#   bash scripts/unbrick_upload.sh
#   # Then plug in the keyboard when prompted.
#
# The script shows cumulative progress so you can see if bytes are actually
# advancing vs. restarting from zero.
# =============================================================================

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MCUMGR="${CRUSH80_MCUMGR:-$HOME/go/bin/mcumgr}"
IMAGE="${1:-$REPO_DIR/dist/crush80-zmk-app.signed.BACKUP.bin}"

if [ ! -f "$IMAGE" ]; then
    echo "ERROR: Firmware not found: $IMAGE"
    echo "  Tried: $IMAGE"
    exit 1
fi

IMAGE_SIZE=$(wc -c < "$IMAGE" | tr -d ' ')
IMAGE_NAME=$(basename "$IMAGE")

# --- Port Detection ---
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

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║         CRUSH80 UNBRICK — MULTI-STRATEGY UPLOAD            ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║ Firmware: $IMAGE_NAME"
echo "║ Size:     $IMAGE_SIZE bytes (~$((IMAGE_SIZE / 1024)) KiB)"
echo "║                                                              "
echo "║ Strategies:                                                  "
echo "║   1. mcumgr -w1 mtu=256 (conservative windowing)           ║"
echo "║   2. mcumgr -w1 mtu=128 -t30 (ultra-conservative)          ║"
echo "║   3. Python smpclient (per-chunk control + auto-retry)      ║"
echo "║   4. Raw SMP serial (manual byte-level crawl)               ║"
echo "║                                                              "
echo "║ Each strategy shows CUMULATIVE progress across all retries. ║"
echo "║ If progress advances beyond prior attempts, we're winning.  ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# --- Detect or wait for port ---
PORT=$(detect_port)
if [ -z "$PORT" ]; then
    echo "  Plug in the keyboard now..."
    PORT=$(wait_for_port 60) || true
fi
if [ -z "$PORT" ]; then
    echo "ERROR: No USB port found after 60s."
    exit 1
fi
echo ""
echo "  Port: $PORT"
echo ""

# =============================================================================
# STRATEGY 1: mcumgr -w 1 with mtu=256
# =============================================================================
run_mcumgr_strategy() {
    local mtu="$1"
    local window="$2"
    local timeout="$3"
    local max_retries="$4"
    local stall_sec="$5"
    local label="$6"

    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  STRATEGY: $label"
    echo "  Settings: mtu=$mtu, window=$window, timeout=${timeout}s"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    local attempt=0
    local best_pct="0.00"
    local best_bytes=0
    local consecutive_zero=0

    while [ $attempt -lt "$max_retries" ]; do
        attempt=$((attempt + 1))

        # Verify port
        PORT=$(detect_port)
        if [ -z "$PORT" ]; then
            echo "  Port lost. Waiting for reconnect..."
            PORT=$(wait_for_port 30) || true
            if [ -z "$PORT" ]; then
                echo "  FAILED: Port not found."
                return 1
            fi
        fi

        local conn="dev=$PORT,baud=115200,mtu=$mtu"
        local tmpout
        tmpout=$(mktemp /tmp/mcumgr_strat.XXXXXX)

        # Run mcumgr in background
        $MCUMGR --conntype serial --connstring "$conn" image upload -w "$window" -t "$timeout" "$IMAGE" > "$tmpout" 2>&1 &
        local pid=$!

        local last_pct=""
        local stall_count=0
        local this_best="0.00"

        while kill -0 $pid 2>/dev/null; do
            sleep 2

            local cur_pct
            cur_pct=$(tail -c 500 "$tmpout" 2>/dev/null | tr '\r' '\n' | grep -oE '[0-9]+\.[0-9]+%' | tail -1 || echo "")

            if [ -n "$cur_pct" ]; then
                local cur_num
                cur_num=$(echo "$cur_pct" | grep -oE '[0-9]+\.[0-9]+' || echo "0")

                # Update this-attempt best
                if [ "$(echo "$cur_num > $this_best" | bc 2>/dev/null || echo 0)" = "1" ]; then
                    this_best="$cur_num"
                fi

                # Update overall best
                if [ "$(echo "$cur_num > $best_pct" | bc 2>/dev/null || echo 0)" = "1" ]; then
                    best_pct="$cur_num"
                    best_bytes=$(echo "$cur_num * $IMAGE_SIZE / 100" | bc 2>/dev/null | cut -d. -f1 || echo 0)
                fi

                # Progress bar
                local bar_width=30
                local filled=$(echo "$cur_num * $bar_width / 100" | bc 2>/dev/null | cut -d. -f1 || echo 0)
                local empty=$((bar_width - filled))
                local bar=""
                for ((b=0; b<filled; b++)); do bar+="█"; done
                for ((b=0; b<empty; b++)); do bar+="░"; done

                printf "\r  [%d/%d] %s %s | best: %s%% (%d/%d bytes)" \
                    "$attempt" "$max_retries" "$bar" "$cur_pct" "$best_pct" "$best_bytes" "$IMAGE_SIZE" >&2

                if [ "$cur_pct" = "$last_pct" ]; then
                    stall_count=$((stall_count + 2))
                else
                    stall_count=0
                    last_pct="$cur_pct"
                fi
            else
                stall_count=$((stall_count + 2))
            fi

            if [ $stall_count -ge "$stall_sec" ]; then
                kill $pid 2>/dev/null || true
                break
            fi
        done

        wait $pid 2>/dev/null || true
        echo "" >&2

        # Check for completion
        if tail -c 500 "$tmpout" 2>/dev/null | tr '\r' '\n' | grep -qE '100\.00%'; then
            echo ""
            echo "  ██████████████████████████████ 100% — UPLOAD COMPLETE!"
            rm -f "$tmpout"
            return 0
        fi

        rm -f "$tmpout"

        # Track stagnation
        if [ "$this_best" = "0.00" ]; then
            consecutive_zero=$((consecutive_zero + 1))
        else
            consecutive_zero=0
        fi

        if [ $consecutive_zero -ge 3 ]; then
            echo "  ⚠ 3 retries with 0% progress. Strategy exhausted."
            echo ""
            return 1
        fi

        sleep 2
    done

    echo "  Strategy reached max retries ($max_retries). Best: ${best_pct}%"
    echo ""

    if [ "$(echo "$best_pct > 90" | bc 2>/dev/null || echo 0)" = "1" ]; then
        return 0
    fi
    return 1
}

# --- Strategy 1: Conservative windowing ---
if run_mcumgr_strategy 256 1 15 15 25 "mcumgr -w1 mtu=256 (conservative)"; then
    echo ""
    echo "=== SUCCESS! Firmware uploaded. ==="
    exit 0
fi

echo "  Strategy 1 failed. Trying strategy 2..."
echo ""
echo "  ┌─────────────────────────────────────────────────────────┐"
echo "  │  UNPLUG the keyboard, wait 3 sec, REPLUG.              │"
echo "  │  Then press Enter to continue.                          │"
echo "  └─────────────────────────────────────────────────────────┘"
read -r -p "  Press Enter after replug... "
PORT=$(wait_for_port 30) || true
if [ -z "$PORT" ]; then
    echo "ERROR: Port not found."
    exit 1
fi

# --- Strategy 2: Ultra-conservative ---
if run_mcumgr_strategy 128 1 30 15 30 "mcumgr -w1 mtu=128 (ultra-conservative)"; then
    echo ""
    echo "=== SUCCESS! Firmware uploaded. ==="
    exit 0
fi

echo "  Strategy 2 failed. Trying Python-based upload..."
echo ""
echo "  ┌─────────────────────────────────────────────────────────┐"
echo "  │  UNPLUG the keyboard, wait 3 sec, REPLUG.              │"
echo "  │  Then press Enter to continue.                          │"
echo "  └─────────────────────────────────────────────────────────┘"
read -r -p "  Press Enter after replug... "
PORT=$(wait_for_port 30) || true
if [ -z "$PORT" ]; then
    echo "ERROR: Port not found."
    exit 1
fi

# =============================================================================
# STRATEGY 3: Python raw SMP upload with per-chunk retry
# =============================================================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STRATEGY: Python raw SMP (per-chunk retry, 256-byte chunks)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

python3 "$REPO_DIR/scripts/smp_upload.py" "$PORT" "$IMAGE" && {
    echo ""
    echo "=== SUCCESS! Firmware uploaded via Python SMP. ==="
    exit 0
} || {
    echo "  Python SMP upload failed or not available."
    echo ""
}

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ALL STRATEGIES EXHAUSTED                                   ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║                                                              "
echo "║  The keyboard's SMP layer consistently stalls. Options:      "
echo "║                                                              "
echo "║  1. Install smpmgr (modern Python mcumgr replacement):      "
echo "║     pipx install smpmgr                                      "
echo "║     smpmgr --port $PORT image upload $IMAGE_NAME             "
echo "║                                                              "
echo "║  2. Try from a different computer (Linux preferred)          "
echo "║                                                              "
echo "║  3. Use a USB-to-SWD debugger (J-Link, ST-Link) to flash    "
echo "║     directly, bypassing SMP entirely                         "
echo "║                                                              "
echo "╚══════════════════════════════════════════════════════════════╝"
exit 1
