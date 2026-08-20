#!/bin/bash
# Restore stock Evision firmware on a Crush 80 running ZMK.
#
# Uses the custom flash_mgmt mcumgr group to write the original firmware
# directly to flash offset 0x0, then resets. All over USB CDC ACM.
#
# Prerequisites:
#   - Keyboard connected via USB, running ZMK firmware (VID 1d50:615e)
#   - Stock firmware .bin file (download from Wobkey's official site)
#   - mcumgr installed (setup.sh handles this)
#
# Usage:
#   ./restore_stock.sh                          # interactive (prompts for firmware path)
#   ./restore_stock.sh path/to/firmware.bin     # specify firmware file
#   ./restore_stock.sh -y path/to/firmware.bin  # non-interactive
#   ./restore_stock.sh --port /dev/ttyACM1      # custom serial port

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
FIRMWARE=""
SERIAL_PORT="${SERIAL_PORT:-/dev/ttyACM0}"
AUTO_YES=0
STOCK_VID="320f"
STOCK_PID="5055"
ZMK_VID="1d50"
ZMK_PID="615e"

# ── Parse arguments ──────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --port)      SERIAL_PORT="$2"; shift 2 ;;
        -y|--yes)    AUTO_YES=1; shift ;;
        --help|-h)
            echo "Usage: $0 [-y] [firmware.bin] [--port /dev/ttyACMx]"
            echo ""
            echo "If no firmware file is specified, you will be prompted to enter the path."
            echo "Download the latest Crush 80 firmware from Wobkey's official site."
            exit 0 ;;
        -*) die "Unknown option: $1" ;;
        *)  FIRMWARE="$1"; shift ;;
    esac
done

# ── Prompt for firmware path if not provided ─────────────────
if [[ -z "$FIRMWARE" ]]; then
    echo ""
    info "No firmware file specified."
    info "Download the latest Crush 80 firmware from Wobkey's official site:"
    info "  https://wobkey.com/pages/support (or check your email for the download link)"
    echo ""
    info "The file is typically named 'code_2M.bin' or 'Crush80_vX.X.bin'."
    echo ""
    read -rp "Enter path to the stock firmware .bin file: " FIRMWARE
    [[ -n "$FIRMWARE" ]] || die "No path entered. Aborting."
fi

# Expand tilde and resolve path
FIRMWARE="${FIRMWARE/#\~/$HOME}"
[[ -f "$FIRMWARE" ]] || die "Firmware file not found: $FIRMWARE"

# ── Locate mcumgr ────────────────────────────────────────────
MCUMGR="${MCUMGR:-$(command -v mcumgr 2>/dev/null || echo "$HOME/go/bin/mcumgr")}"
[[ -x "$MCUMGR" ]] || die "mcumgr not found. Install: go install github.com/apache/mynewt-mcumgr-cli/mcumgr@latest"

# ── Helpers ──────────────────────────────────────────────────
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
            die "Timeout waiting for $desc after ${timeout}s."
        fi
    done
    ok "$desc detected (${elapsed}s)"
}

# ── Check current state ─────────────────────────────────────
START_TIME=$SECONDS

header "=== Crush 80: Restore Stock Firmware ==="

if check_usb "$STOCK_VID" "$STOCK_PID"; then
    ok "Keyboard is already running stock firmware."
    exit 0
fi

if ! check_usb "$ZMK_VID" "$ZMK_PID"; then
    die "Keyboard not found. Expected ZMK firmware (${ZMK_VID}:${ZMK_PID}) on USB."
fi

info "ZMK firmware detected."
info "  Firmware: $FIRMWARE ($(stat -c%s "$FIRMWARE" 2>/dev/null || stat -f%z "$FIRMWARE") bytes)"
info "  Port: $SERIAL_PORT"

if [[ $AUTO_YES -eq 0 ]]; then
    echo ""
    warn "This will erase ZMK and write the stock Evision firmware."
    warn "If interrupted mid-write, the keyboard may require EVK/SWS to recover."
    read -rp "Proceed? [y/N] " confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        info "Aborted."
        exit 0
    fi
fi

# ── Wait for serial port ─────────────────────────────────────
if [[ ! -e "$SERIAL_PORT" ]]; then
    info "Serial port $SERIAL_PORT not found, scanning..."
    for dev in /dev/ttyACM0 /dev/ttyACM1 /dev/ttyUSB0; do
        if [[ -e "$dev" ]]; then
            SERIAL_PORT="$dev"
            info "Found: $SERIAL_PORT"
            break
        fi
    done
    [[ -e "$SERIAL_PORT" ]] || die "No serial port found. Is the keyboard connected?"
fi

# ── Write firmware via mcumgr flash_mgmt ─────────────────────
header "Writing stock firmware to flash 0x0..."
info "This writes directly to flash and resets. Do NOT unplug the keyboard."
echo ""

"$MCUMGR" --conntype serial --connstring "dev=$SERIAL_PORT,baud=115200" \
    flash-mgmt write 0x0 "$FIRMWARE"

info "Resetting keyboard..."
"$MCUMGR" --conntype serial --connstring "dev=$SERIAL_PORT,baud=115200" \
    reset

# Wait for stock firmware to appear
wait_for_usb "$STOCK_VID" "$STOCK_PID" "stock firmware" 30

ELAPSED=$((SECONDS - START_TIME))
echo ""
ok "Restore complete (${ELAPSED}s)"
info "Keyboard is running stock Evision firmware (${STOCK_VID}:${STOCK_PID})."
info "To reinstall ZMK: bash install_zmk.sh"
