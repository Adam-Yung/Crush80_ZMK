#!/bin/bash
# Install ZMK firmware on a Crush 80 running stock Evision firmware.
#
# Two-stage process (all over USB, no EVK/SWS needed):
#   1. OTA-flash a monolithic "bridge" firmware via the stock OTA protocol
#      (B91 boot ROM dual-bank boot: bridge runs from bank 1 at 0x40000)
#   2. Bridge exposes USB CDC ACM + mcumgr SMP; upload ZMK app via mcumgr
#
# Prerequisites:
#   - Keyboard connected via USB, running stock firmware (VID 320f:5055)
#   - Build artifacts in dist/:  bash build.sh
#   - mcumgr installed:  setup.sh handles this, or: go install github.com/apache/mynewt-mcumgr-cli/mcumgr@latest
#
# Usage:
#   ./install_zmk.sh              # interactive (asks for confirmation)
#   ./install_zmk.sh -y           # non-interactive (skip confirmation)
#   ./install_zmk.sh --bridge path/to/bridge.bin --zmk path/to/zmk.signed.bin

set -euo pipefail
cd "$(dirname "$0")"

# ── Colors (disabled when stdout is not a terminal) ──────────
if [[ -t 1 ]]; then
    BOLD='\033[1m' RED='\033[0;31m' GREEN='\033[0;32m'
    YELLOW='\033[1;33m' CYAN='\033[0;36m' NC='\033[0m'
else
    BOLD='' RED='' GREEN='' YELLOW='' CYAN='' NC=''
fi
info()   { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()     { echo -e "${GREEN}[ OK ]${NC} $*"; }
warn()   { echo -e "${YELLOW}[WARN]${NC} $*" >&2; }
err()    { echo -e "${RED}[ERR ]${NC} $*" >&2; }
die()    { err "$@"; exit 1; }
header() { echo -e "\n${BOLD}$*${NC}"; }

# ── Defaults ─────────────────────────────────────────────────
BRIDGE_IMAGE="dist/crush80-ota-bridge.bin"
ZMK_IMAGE="dist/crush80-zmk-app.signed.bin"
SERIAL_PORT="${SERIAL_PORT:-/dev/ttyACM0}"
STOCK_VID="320f"
STOCK_PID="5055"
ZMK_VID="1d50"
ZMK_PID="615e"
AUTO_YES=0

# ── Parse arguments ──────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --bridge)    BRIDGE_IMAGE="$2"; shift 2 ;;
        --zmk)       ZMK_IMAGE="$2"; shift 2 ;;
        --port)      SERIAL_PORT="$2"; shift 2 ;;
        -y|--yes)    AUTO_YES=1; shift ;;
        --help|-h)
            echo "Usage: $0 [-y] [--bridge OTA_IMAGE] [--zmk ZMK_SIGNED_IMAGE] [--port /dev/ttyACMx]"
            exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done

# ── Validate prerequisites ───────────────────────────────────
for f in "$BRIDGE_IMAGE" "$ZMK_IMAGE"; do
    [[ -f "$f" ]] || die "Required file not found: $f (run: bash build.sh)"
done

MCUMGR="${MCUMGR:-$(command -v mcumgr 2>/dev/null || echo "$HOME/go/bin/mcumgr")}"
[[ -x "$MCUMGR" ]] || die "mcumgr not found. Install: go install github.com/apache/mynewt-mcumgr-cli/mcumgr@latest"

check_usb() {
    lsusb -d "$1:$2" >/dev/null 2>&1
}

wait_for_usb() {
    local vid="$1" pid="$2" desc="$3" timeout="${4:-30}"
    info "Waiting for $desc..."
    local elapsed=0
    while ! check_usb "$vid" "$pid"; do
        sleep 1
        elapsed=$((elapsed + 1))
        if [[ $elapsed -ge $timeout ]]; then
            die "Timeout waiting for $desc after ${timeout}s"
        fi
    done
    ok "$desc detected (${elapsed}s)"
}

wait_for_serial() {
    local port="$1" timeout="${2:-15}"
    info "Waiting for serial port $port..."
    local elapsed=0
    while [[ ! -e "$port" ]]; do
        sleep 1
        elapsed=$((elapsed + 1))
        if [[ $elapsed -ge $timeout ]]; then
            die "Timeout waiting for $port after ${timeout}s"
        fi
    done
    sleep 2
    ok "Serial port ready"
}

# ── Recovery guidance on failure ─────────────────────────────
cleanup_msg() {
    local rc=$?
    [[ $rc -eq 0 ]] && return
    echo ""
    warn "Installation did not complete."
    if check_usb "$ZMK_VID" "$ZMK_PID"; then
        info "Bridge/ZMK firmware is running. You can retry Stage 2:"
        info "  $MCUMGR --conntype serial --connstring dev=$SERIAL_PORT,baud=115200 image upload $ZMK_IMAGE"
    else
        info "Try unplugging the keyboard, waiting 5s, and re-running this script."
    fi
}
trap cleanup_msg EXIT

# ── Step 0: Check current state ──────────────────────────────
START_TIME=$SECONDS

header "=== Crush 80: Install ZMK ==="

if check_usb "$ZMK_VID" "$ZMK_PID"; then
    info "Keyboard is already running ZMK (or bridge) firmware."
    info "To update ZMK, use: bash flash.sh stage2"
    info "To reinstall from scratch, first restore stock: bash restore_stock.sh"
    exit 0
fi

if ! check_usb "$STOCK_VID" "$STOCK_PID"; then
    die "Keyboard not found. Expected stock firmware (${STOCK_VID}:${STOCK_PID}) on USB."
fi

info "Stock firmware detected."
info "  Bridge: $BRIDGE_IMAGE ($(stat -c%s "$BRIDGE_IMAGE" 2>/dev/null || stat -f%z "$BRIDGE_IMAGE") bytes)"
info "  ZMK:    $ZMK_IMAGE ($(stat -c%s "$ZMK_IMAGE" 2>/dev/null || stat -f%z "$ZMK_IMAGE") bytes)"

if [[ $AUTO_YES -eq 0 ]]; then
    echo ""
    info "This will replace the stock firmware with ZMK."
    info "You can restore the original later with: bash restore_stock.sh"
    read -rp "Proceed? [y/N] " confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        info "Aborted."
        exit 0
    fi
fi

# ── Stage 1: OTA flash the bridge firmware ───────────────────
header "=== Stage 1/2: OTA flash bridge firmware ==="
python3 scripts/flash_ota.py --force --yes "$BRIDGE_IMAGE"

info "Bridge flashed. Keyboard will reboot..."
wait_for_usb "$ZMK_VID" "$ZMK_PID" "bridge firmware" 30
wait_for_serial "$SERIAL_PORT" 15

# ── Stage 2: Upload ZMK via mcumgr ──────────────────────────
header "=== Stage 2/2: Upload ZMK application via mcumgr ==="
info "Uploading $ZMK_IMAGE..."
"$MCUMGR" --conntype serial --connstring "dev=$SERIAL_PORT,baud=115200" \
    image upload "$ZMK_IMAGE"

info "Confirming image..."
"$MCUMGR" --conntype serial --connstring "dev=$SERIAL_PORT,baud=115200" \
    image confirm

info "Resetting keyboard..."
"$MCUMGR" --conntype serial --connstring "dev=$SERIAL_PORT,baud=115200" \
    reset

# Wait for ZMK to come up after reset
sleep 3
wait_for_usb "$ZMK_VID" "$ZMK_PID" "ZMK firmware" 30

ELAPSED=$((SECONDS - START_TIME))
echo ""
ok "Installation complete (${ELAPSED}s)"
info "Keyboard is running ZMK firmware."
info "To restore stock firmware: bash restore_stock.sh"
