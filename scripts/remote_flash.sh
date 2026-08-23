#!/bin/bash
# Remote OTA Flash Script for Crush 80
# Run on the Linux machine where the keyboard is connected.
#
# This script:
#   1. Probes the system for Python environments
#   2. Creates a venv with hidapi installed
#   3. Checks the keyboard is visible on USB
#   4. Runs the OTA flash
#
# Usage:
#   bash scripts/remote_flash.sh              # full flash
#   bash scripts/remote_flash.sh --probe-only # just check environment + USB
#   bash scripts/remote_flash.sh --no-flash   # setup only, don't flash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$REPO_DIR/.venv"
FW_FILE="$REPO_DIR/dist/crush80-ota-bridge_ota.bin"

PROBE_ONLY=false
NO_FLASH=false
for arg in "$@"; do
    case "$arg" in
        --probe-only) PROBE_ONLY=true ;;
        --no-flash)   NO_FLASH=true ;;
    esac
done

echo "=============================================="
echo "  Crush 80 Remote OTA Flash"
echo "=============================================="
echo ""
echo "Repo:     $REPO_DIR"
echo "Firmware: $FW_FILE"
echo ""

# ─── Phase 1: Probe system ───────────────────────────────────────────────────
echo "── Phase 1: System Probe ──"
echo ""
echo "User:     $(whoami)"
echo "Hostname: $(hostname)"
echo "Kernel:   $(uname -r)"
echo ""

# Find best Python
PYTHON=""
echo "Searching for Python environments..."

# Priority 1: Conda in PATH
if command -v conda &>/dev/null; then
    CONDA_BASE="$(conda info --base 2>/dev/null)"
    echo "  [✓] Conda found at: $CONDA_BASE"
    PYTHON="$CONDA_BASE/bin/python3"
fi

# Priority 2: Miniconda/miniforge in home directory
if [ -z "$PYTHON" ]; then
    for candidate in "$HOME/miniconda3/bin/python3" "$HOME/miniforge3/bin/python3" "$HOME/anaconda3/bin/python3"; do
        if [ -x "$candidate" ]; then
            echo "  [✓] Found: $candidate"
            PYTHON="$candidate"
            break
        fi
    done
fi

# Priority 3: Linuxbrew python
if [ -z "$PYTHON" ]; then
    for candidate in /home/linuxbrew/.linuxbrew/bin/python3 /opt/homebrew/bin/python3; do
        if [ -x "$candidate" ]; then
            echo "  [✓] Brew python: $candidate"
            PYTHON="$candidate"
            break
        fi
    done
fi

# Priority 4: System python (last resort)
if [ -z "$PYTHON" ]; then
    if command -v python3 &>/dev/null; then
        PYTHON="$(command -v python3)"
        echo "  [!] Using system python: $PYTHON"
    else
        echo "  [✗] ERROR: No python3 found!"
        exit 1
    fi
fi

echo ""
echo "Selected Python: $PYTHON"
"$PYTHON" --version
echo ""

# Check if python supports venv
if ! "$PYTHON" -c "import venv" 2>/dev/null; then
    echo "  [!] venv module not available. Trying ensurepip..."
    if ! "$PYTHON" -c "import ensurepip" 2>/dev/null; then
        echo "  [✗] ERROR: Python has no venv or ensurepip. Install python3-venv:"
        echo "       sudo apt install python3-venv"
        exit 1
    fi
fi
echo "  [✓] venv module available"

# Check USB for keyboard
echo ""
echo "── USB Device Check ──"
echo ""
if command -v lsusb &>/dev/null; then
    CRUSH80=$(lsusb 2>/dev/null | grep -i "320f:5055" || true)
    if [ -n "$CRUSH80" ]; then
        echo "  [✓] Crush 80 found: $CRUSH80"
    else
        echo "  [✗] Crush 80 NOT found on USB (VID=320f PID=5055)"
        echo "      Is the keyboard plugged in and in USB mode?"
        lsusb 2>/dev/null | grep -i "320f" || echo "      No 320f devices at all."
        exit 1
    fi
else
    echo "  [!] lsusb not available, skipping USB check"
fi

# Check hidraw permissions
echo ""
echo "── HID Permissions ──"
echo ""
HIDRAW_OK=false
for dev in /dev/hidraw*; do
    if [ -r "$dev" ] && [ -w "$dev" ]; then
        HIDRAW_OK=true
        break
    fi
done
if [ "$HIDRAW_OK" = true ]; then
    echo "  [✓] /dev/hidraw* is read/write accessible"
else
    echo "  [!] /dev/hidraw* not directly writable"
    echo "      Will need: sudo chmod 666 /dev/hidraw* (temporary)"
    echo "      Or install udev rule for persistent access"
    echo ""
    echo "  Attempting to fix permissions now..."
    if sudo -n chmod 666 /dev/hidraw* 2>/dev/null; then
        echo "  [✓] Fixed (passwordless sudo worked)"
    else
        echo "  [!] Needs manual fix. Run:"
        echo "      sudo chmod 666 /dev/hidraw*"
        echo ""
        read -rp "  Fix permissions now? [Y/n] " fix_perms
        if [ "${fix_perms:-y}" != "n" ]; then
            sudo chmod 666 /dev/hidraw*
            echo "  [✓] Fixed"
        fi
    fi
fi

# Check firmware file
echo ""
echo "── Firmware Check ──"
echo ""
if [ -f "$FW_FILE" ]; then
    FW_SIZE=$(stat -c%s "$FW_FILE" 2>/dev/null || stat -f%z "$FW_FILE" 2>/dev/null)
    echo "  [✓] $FW_FILE ($FW_SIZE bytes)"
else
    echo "  [✗] ERROR: Firmware file not found: $FW_FILE"
    echo "      Copy it from the Mac: scp dist/crush80-ota-bridge_ota.bin home:$FW_FILE"
    exit 1
fi

if [ "$PROBE_ONLY" = true ]; then
    echo ""
    echo "── Probe complete. Everything looks good! ──"
    exit 0
fi

# ─── Phase 2: Set up venv ────────────────────────────────────────────────────
echo ""
echo "── Phase 2: Python Environment Setup ──"
echo ""

if [ -d "$VENV_DIR" ] && [ -f "$VENV_DIR/bin/python3" ]; then
    echo "  Existing venv found at $VENV_DIR"
    if "$VENV_DIR/bin/python3" -c "import hid" 2>/dev/null; then
        echo "  [✓] hidapi already installed"
    else
        echo "  Installing hidapi..."
        "$VENV_DIR/bin/pip" install hidapi 2>&1 | tail -3
    fi
else
    echo "  Creating venv at $VENV_DIR..."
    "$PYTHON" -m venv "$VENV_DIR"
    echo "  Installing hidapi..."
    "$VENV_DIR/bin/pip" install --upgrade pip 2>&1 | tail -1
    "$VENV_DIR/bin/pip" install hidapi 2>&1 | tail -3
fi

# Verify
if ! "$VENV_DIR/bin/python3" -c "import hid; print(f'  [✓] hidapi {hid.__version__} OK')" 2>/dev/null; then
    "$VENV_DIR/bin/python3" -c "import hid; print('  [✓] hidapi OK')"
fi

if [ "$NO_FLASH" = true ]; then
    echo ""
    echo "── Setup complete (--no-flash). Ready to flash with: ──"
    echo "   $VENV_DIR/bin/python3 $SCRIPT_DIR/flash_ota.py --verbose --delay 2 $FW_FILE"
    exit 0
fi

# ─── Phase 3: Flash ──────────────────────────────────────────────────────────
echo ""
echo "── Phase 3: OTA Flash ──"
echo ""

# Quick HID enumeration test
echo "Testing HID access..."
"$VENV_DIR/bin/python3" -c "
import hid
devices = hid.enumerate(0x320F, 0x5055)
print(f'  Found {len(devices)} HID interfaces for Crush 80')
ota = [d for d in devices if d.get('usage_page') == 0xFFEF]
if ota:
    print(f'  [✓] OTA interface found (usage_page=0xFFEF, iface={ota[0].get(\"interface_number\")})')
    # Test opening it
    dev = hid.device()
    try:
        dev.open_path(ota[0]['path'])
        dev.close()
        print('  [✓] OTA interface opens successfully!')
    except Exception as e:
        print(f'  [✗] Cannot open OTA interface: {e}')
        print('      Run: sudo chmod 666 /dev/hidraw*')
        import sys; sys.exit(1)
else:
    print('  [!] No dedicated OTA interface (0xFFEF) found')
    print('  Interfaces:')
    for d in devices:
        print(f'    usage_page=0x{d.get(\"usage_page\",0):04X} iface={d.get(\"interface_number\",-1)}')
    import sys; sys.exit(1)
"

if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: Cannot access OTA interface. Fix permissions and retry."
    exit 1
fi

echo ""
echo "Starting OTA flash with 2ms inter-packet delay..."
echo ""

"$VENV_DIR/bin/python3" "$SCRIPT_DIR/flash_ota.py" \
    --yes --verbose --delay 2 \
    "$FW_FILE"

EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "=============================================="
    echo "  OTA Flash SUCCEEDED!"
    echo ""
    echo "  Next steps:"
    echo "    1. Wait 5-10 seconds for the keyboard to reboot"
    echo "    2. Check if a new serial device appeared:"
    echo "       ls /dev/ttyACM*"
    echo "    3. If yes, the OTA bridge booted! Run Stage 2:"
    echo "       $VENV_DIR/bin/python3 $SCRIPT_DIR/flash_stage2.py --auto"
    echo "=============================================="
else
    echo "=============================================="
    echo "  OTA Flash FAILED (exit code $EXIT_CODE)"
    echo ""
    echo "  Try:"
    echo "    - Increase delay: --delay 5"
    echo "    - Unplug/replug keyboard and retry"
    echo "    - Check dmesg for USB errors: dmesg | tail -20"
    echo "=============================================="
fi

exit $EXIT_CODE
