#!/bin/bash
# Build all Wobkey Crush 80 ZMK firmware targets.
# Run from repo root: bash build.sh
# Supports macOS and Linux.
#
# Outputs go to dist/ (gitignored):
#   dist/crush80-ota-bridge.bin    ← flash first via flash_ota.py
#   dist/crush80-zmk-app.signed.bin ← flash second via mcumgr
#   dist/crush80-mcuboot.bin       ← only needed for SWS/hardware recovery
#
# Options:
#   bash build.sh --skip-bridge    skip OTA bridge build (faster rebuild)
#   bash build.sh --skip-mcuboot   skip MCUboot build

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SKIP_BRIDGE=false
SKIP_MCUBOOT=true   # MCUboot: built separately or use pre-built copy
                    # Build explicitly with: bash build.sh --build-mcuboot

for arg in "$@"; do
    case $arg in
        --skip-bridge)    SKIP_BRIDGE=true ;;
        --skip-mcuboot)   SKIP_MCUBOOT=true ;;
        --build-mcuboot)  SKIP_MCUBOOT=false ;;
    esac
done

# ── Locate west workspace ────────────────────────────────────────────────────
if [ -f "$REPO_DIR/.workspace_path" ]; then
    # shellcheck source=/dev/null
    source "$REPO_DIR/.workspace_path"
elif [ -d "$HOME/Projects/crush80-workspace/.west" ]; then
    WORKSPACE_DIR="$HOME/Projects/crush80-workspace"
else
    echo "ERROR: West workspace not found. Run: bash setup.sh"
    exit 1
fi

export PATH="/usr/bin:/usr/local/bin:$HOME/.local/bin:$HOME/go/bin:$PATH"
# West may be installed in Python user site
WEST_USER_BIN="$(python3 -m site --user-base 2>/dev/null)/bin"
[[ -d "$WEST_USER_BIN" ]] && export PATH="$WEST_USER_BIN:$PATH"

export ZEPHYR_SDK_INSTALL_DIR="$HOME/zephyr-sdk-0.17.0"

echo "Workspace: $WORKSPACE_DIR"
echo "Repo:      $REPO_DIR"

# ── Sync board files into workspace ──────────────────────────────────────────
echo ""
echo "Syncing board files..."
cp -r "$REPO_DIR/zmk/boards/crush80/"* "$WORKSPACE_DIR/zmk/boards/crush80/"
cp -r "$REPO_DIR/zmk/drivers/led/"*    "$WORKSPACE_DIR/zmk/drivers/led/"
cp -r "$REPO_DIR/zmk/dts/bindings/led/"* "$WORKSPACE_DIR/zmk/dts/bindings/led/"
echo "  Done."

cd "$WORKSPACE_DIR"

CONF="$REPO_DIR/conf/app.conf"
OVERLAY="$WORKSPACE_DIR/conf/mcumgr.overlay"

# Crush 80 specific overrides:
#   app.conf already sets CONFIG_ZMK_KEYBOARD_NAME but this override
#   ensures the name is correct even if app.conf is not the primary conf.
OVERRIDE_CONF="$(mktemp /tmp/crush80_override.XXXXXX.conf)"
cat > "$OVERRIDE_CONF" << 'EOF'
CONFIG_ZMK_KEYBOARD_NAME="Crush 80"
EOF

# ── MCUboot ──────────────────────────────────────────────────────────────────
if [ "$SKIP_MCUBOOT" = false ]; then
    echo ""
    echo "[1/3] Building MCUboot..."
    west build \
        -s bootloader/mcuboot/boot/zephyr \
        -b crush80 \
        -d build-mcuboot \
        --pristine \
        -- \
        -DEXTRA_CONF_FILE="$WORKSPACE_DIR/conf/mcuboot.conf" \
        -DDTC_OVERLAY_FILE="$WORKSPACE_DIR/conf/mcuboot.overlay" \
        -DBOARD_ROOT="$WORKSPACE_DIR/zmk"
    echo "  MCUboot: OK"
fi

# ── OTA bridge ───────────────────────────────────────────────────────────────
if [ "$SKIP_BRIDGE" = false ]; then
    echo ""
    echo "[2/3] Building OTA bridge..."
    # Bridge uses only ota-bridge.conf — NOT app.conf (which enables MCUboot)
    BRIDGE_OVERRIDE="$(mktemp /tmp/crush80_bridge.XXXXXX.conf)"
    printf 'CONFIG_ZMK_KEYBOARD_NAME="Crush 80 Bridge"\n' > "$BRIDGE_OVERRIDE"
    west build \
        -s zmk-src/app \
        -b crush80 \
        -d build-bridge \
        --pristine \
        -- \
        -DEXTRA_CONF_FILE="$WORKSPACE_DIR/conf/ota-bridge.conf;$BRIDGE_OVERRIDE" \
        -DDTC_OVERLAY_FILE="$OVERLAY" \
        -DBOARD_ROOT="$WORKSPACE_DIR/zmk"
    rm -f "$BRIDGE_OVERRIDE"
    echo "  OTA bridge: OK"
fi

# ── ZMK application ──────────────────────────────────────────────────────────
echo ""
echo "[3/3] Building ZMK application..."
west build \
    -s zmk-src/app \
    -b crush80 \
    -d build-crush80 \
    --pristine \
    -- \
    -DEXTRA_CONF_FILE="$CONF;$OVERRIDE_CONF" \
    -DDTC_OVERLAY_FILE="$OVERLAY" \
    -DBOARD_ROOT="$WORKSPACE_DIR/zmk"
echo "  ZMK app: OK"

rm -f "$OVERRIDE_CONF"

# ── Collect artifacts into dist/ ─────────────────────────────────────────────
echo ""
echo "Collecting artifacts to dist/..."
DIST="$WORKSPACE_DIR/dist"
mkdir -p "$DIST"

[ "$SKIP_BRIDGE"   = false ] && \
    cp "build-bridge/zephyr/zmk.bin"         "$DIST/crush80-ota-bridge.bin"
cp     "build-crush80/zephyr/zmk.signed.bin" "$DIST/crush80-zmk-app.signed.bin"
cp     "build-crush80/zephyr/zmk.bin"        "$DIST/crush80-zmk-app.bin"
if [ "$SKIP_MCUBOOT" = false ]; then
    cp "build-mcuboot/zephyr/zephyr.bin" "$DIST/crush80-mcuboot.bin"
elif [ -f "build-mcuboot/zephyr/zephyr.bin" ]; then
    cp "build-mcuboot/zephyr/zephyr.bin" "$DIST/crush80-mcuboot.bin"
fi

# Also copy to repo dist/ for easy Windows access
mkdir -p "$REPO_DIR/dist"
cp "$DIST"/*.bin "$REPO_DIR/dist/" 2>/dev/null || true

echo ""
echo "=============================================="
echo "  Build complete!"
echo ""
echo "  dist/crush80-ota-bridge.bin      ← flash first"
echo "  dist/crush80-zmk-app.signed.bin  ← flash second"
echo ""
echo "  Next: bash flash.sh"
echo "=============================================="
