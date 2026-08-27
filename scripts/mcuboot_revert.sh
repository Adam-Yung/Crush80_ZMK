#!/bin/bash
# Quick bootloader-trigger: runs image list + test in the 5-second SMP window
# Usage: bash scripts/mcuboot_revert.sh
# Must run IMMEDIATELY after plugging keyboard in (within 5 seconds)
set -e

PORT="${1:-$(python3 -c "import glob; p=glob.glob('/dev/cu.usbmodem*'); print(p[0] if p else '')" 2>/dev/null)}"
if [ -z "$PORT" ]; then
    echo "ERROR: No keyboard found on USB. Plug in and retry, or pass port as argument."
    exit 1
fi
echo "Using port: $PORT"
MCUMGR="$HOME/go/bin/mcumgr"
CONN="dev=$PORT,baud=115200"

echo "=== Quick MCUboot Revert ==="
echo "Sending commands fast (must complete in <5 seconds)..."
echo ""

# Step 1: List images to find slot 1 hash
echo "[1/2] Listing images..."
OUTPUT=$($MCUMGR --conntype serial --connstring "$CONN" -t 3 image list 2>&1)
echo "$OUTPUT"

# Extract slot 1 hash
HASH=$(echo "$OUTPUT" | grep -A3 "slot=1" | grep hash | awk '{print $2}')

if [ -z "$HASH" ]; then
    echo ""
    echo "ERROR: No image in slot 1. Need to upload firmware first."
    echo "Try the resilient uploader: python3 scripts/smp_resilient_upload.py"
    exit 1
fi

# Step 2: Mark slot 1 as pending
echo ""
echo "[2/2] Marking $HASH as pending..."
$MCUMGR --conntype serial --connstring "$CONN" -t 3 image test "$HASH"

echo ""
echo "=== SUCCESS ==="
echo "Now:"
echo "  1. UNPLUG keyboard for 10 seconds"
echo "  2. Plug back in (MCUboot will swap images)"
echo "  3. Wait 15 seconds"
echo "  4. Run: $MCUMGR --conntype serial --connstring '$CONN' image confirm ''"
