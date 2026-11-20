#!/bin/bash
# Build all Wobkey Crush 80 ZMK firmware targets.
# Run from repo root: bash build.sh
# Supports macOS and Linux.
#
# Outputs go to dist/ (gitignored):
#   dist/crush80-ota-bridge.bin    ← flash first via flash_ota.py
#   dist/crush80-zmk-app.signed.bin ← flash second via mcumgr
#   dist/crush80-zmk-app-rgb.signed.bin ← optional Reboot Pro RGB app
#   dist/crush80-mcuboot.bin       ← only needed for SWS/hardware recovery
#
# Options:
#   bash build.sh --skip-bridge    skip OTA bridge build (faster rebuild)
#   bash build.sh --skip-mcuboot   skip MCUboot build
#   bash build.sh --rgb            build the Reboot Pro RGB app

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SKIP_BRIDGE=false
SKIP_MCUBOOT=true   # MCUboot: built separately or use pre-built copy
                    # Build explicitly with: bash build.sh --build-mcuboot
ENABLE_RGB=false

for arg in "$@"; do
    case $arg in
        --skip-bridge)    SKIP_BRIDGE=true ;;
        --skip-mcuboot)   SKIP_MCUBOOT=true ;;
        --build-mcuboot)  SKIP_MCUBOOT=false ;;
        --rgb)            ENABLE_RGB=true ;;
    esac
done

# ── Sync keymap config from dotfiles ────────────────────────────────────────
# Priority:
#   1. CRUSH80_KEYMAP env var (explicit path to a .keymap file)
#   2. Dotfiles directory (~/.config/DOTFILES/keybindings/crush80-zmk/)
#   3. Repo default (keymaps/stock.keymap)
DOTFILES_ZMK="${CRUSH80_ZMK_CONFIG:-$HOME/.config/DOTFILES/keybindings/crush80-zmk}"
KEYMAP=

if [ -n "${CRUSH80_KEYMAP:-}" ] && [ -f "$CRUSH80_KEYMAP" ]; then
    echo "Using keymap from CRUSH80_KEYMAP: $CRUSH80_KEYMAP"
    KEYMAP=$CRUSH80_KEYMAP
    # If CRUSH80_APP_CONF is also set, use that
    if [ -n "${CRUSH80_APP_CONF:-}" ] && [ -f "$CRUSH80_APP_CONF" ]; then
        cp "$CRUSH80_APP_CONF" "$REPO_DIR/conf/app.conf"
    fi
elif [ -d "$DOTFILES_ZMK" ]; then
    echo "Syncing config from $DOTFILES_ZMK..."
    [ -f "$DOTFILES_ZMK/crush80.keymap" ] && KEYMAP="$DOTFILES_ZMK/crush80.keymap"
    [ -f "$DOTFILES_ZMK/app.conf" ] && cp "$DOTFILES_ZMK/app.conf" "$REPO_DIR/conf/app.conf"
elif [ -f "$REPO_DIR/keymaps/stock.keymap" ]; then
    echo "No custom keymap configured — using keymaps/stock.keymap"
    KEYMAP="$REPO_DIR/keymaps/stock.keymap"
fi

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

[ -d "$REPO_DIR/.venv/bin" ] && export PATH="$REPO_DIR/.venv/bin:$PATH"
export PATH="$PATH:$HOME/miniforge3/bin:$HOME/.local/bin:$HOME/go/bin:/usr/local/bin:/usr/bin"
# West may be installed in the Python user site outside a virtual environment.
if ! command -v west >/dev/null; then
    WEST_USER_BIN="$(python3 -c 'import site; print(site.getuserbase())')/bin"
    export PATH="$PATH:$WEST_USER_BIN"
fi

export ZEPHYR_SDK_INSTALL_DIR="${ZEPHYR_SDK_INSTALL_DIR:-$HOME/zephyr-sdk-0.17.0}"
export ZEPHYR_TOOLCHAIN_VARIANT="${ZEPHYR_TOOLCHAIN_VARIANT:-zephyr}"

echo "Workspace: $WORKSPACE_DIR"
echo "Repo:      $REPO_DIR"

# ── Sync board files into workspace ──────────────────────────────────────────
echo ""
echo "Syncing board files..."
cp -r "$REPO_DIR/zmk/boards/crush80/"* "$WORKSPACE_DIR/zmk/boards/crush80/"
if [ -n "$KEYMAP" ]; then
    cp "$KEYMAP" "$WORKSPACE_DIR/zmk/boards/crush80/crush80.keymap"
fi

# Sync platform drivers
for d in usb bluetooth sensor watchdog led_strip; do
    mkdir -p "$WORKSPACE_DIR/zmk/drivers/$d"
    cp -r "$REPO_DIR/zmk/drivers/$d/"* "$WORKSPACE_DIR/zmk/drivers/$d/"
done

# Sync DTS bindings for platform drivers
for d in usb bluetooth sensor watchdog led-strip; do
    mkdir -p "$WORKSPACE_DIR/zmk/dts/bindings/$d"
    cp -r "$REPO_DIR/zmk/dts/bindings/$d/"* "$WORKSPACE_DIR/zmk/dts/bindings/$d/"
done

# Sync module root files (CMakeLists.txt, Kconfig, module.yml, src/, include/)
cp "$REPO_DIR/zmk/CMakeLists.txt" "$WORKSPACE_DIR/zmk/"
cp "$REPO_DIR/zmk/Kconfig" "$WORKSPACE_DIR/zmk/"
mkdir -p "$WORKSPACE_DIR/zmk/zephyr"
cp "$REPO_DIR/zmk/zephyr/module.yml" "$WORKSPACE_DIR/zmk/zephyr/"
mkdir -p "$WORKSPACE_DIR/zmk/src" "$WORKSPACE_DIR/zmk/include"
cp "$REPO_DIR/zmk/src/"* "$WORKSPACE_DIR/zmk/src/" 2>/dev/null || true
cp -r "$REPO_DIR/zmk/include/"* "$WORKSPACE_DIR/zmk/include/" 2>/dev/null || true

# Sync conf files
cp "$REPO_DIR/conf/"* "$WORKSPACE_DIR/conf/"

echo "  Done."

cd "$WORKSPACE_DIR"

CONF="$REPO_DIR/conf/app.conf"
OVERLAY="$WORKSPACE_DIR/conf/mcumgr.overlay"
APP_BUILD_DIR=build-crush80
APP_NAME=crush80-zmk-app
APP_OVERLAYS=$OVERLAY
RGB_CPPFLAGS=
if [ "$ENABLE_RGB" = true ]; then
    CONF="$CONF;$WORKSPACE_DIR/conf/rgb.conf"
    APP_OVERLAYS="$OVERLAY;$WORKSPACE_DIR/conf/rgb.overlay"
    APP_BUILD_DIR=build-crush80-rgb
    APP_NAME=crush80-zmk-app-rgb
    RGB_CPPFLAGS=-DCRUSH80_RGB_KEYMAP
fi

# Crush 80 specific overrides:
#   app.conf already sets CONFIG_ZMK_KEYBOARD_NAME but this override
#   ensures the name is correct even if app.conf is not the primary conf.
OVERRIDE_CONF="$(mktemp /tmp/crush80_override_XXXXXX)"
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
        -DBOARD_ROOT="$WORKSPACE_DIR/zmk" \
        -DDTS_ROOT="$WORKSPACE_DIR/zmk"
    echo "  MCUboot: OK"
fi

# ── OTA bridge ───────────────────────────────────────────────────────────────
if [ "$SKIP_BRIDGE" = false ]; then
    echo ""
    echo "[2/3] Building OTA bridge..."
    # Bridge uses only ota-bridge.conf — NOT app.conf (which enables MCUboot)
    BRIDGE_OVERRIDE="$(mktemp /tmp/crush80_bridge_XXXXXX)"
    printf 'CONFIG_ZMK_KEYBOARD_NAME="Crush 80 Bridge"\n' > "$BRIDGE_OVERRIDE"
    west build \
        -s zmk-src/app \
        -b crush80 \
        -d build-bridge \
        --pristine \
        -- \
        -DEXTRA_CONF_FILE="$WORKSPACE_DIR/conf/ota-bridge.conf;$BRIDGE_OVERRIDE" \
        -DDTC_OVERLAY_FILE="$OVERLAY" \
        -DBOARD_ROOT="$WORKSPACE_DIR/zmk" \
        -DDTS_ROOT="$WORKSPACE_DIR/zmk"
    rm -f "$BRIDGE_OVERRIDE"
    echo "  OTA bridge: OK"
fi

# ── ZMK application ──────────────────────────────────────────────────────────
echo ""
echo "[3/3] Building ZMK application..."
west build \
    -s zmk-src/app \
    -b crush80 \
    -d "$APP_BUILD_DIR" \
    --pristine \
    -- \
    -DEXTRA_CONF_FILE="$CONF;$OVERRIDE_CONF" \
    -DDTC_OVERLAY_FILE="$APP_OVERLAYS" \
    -DDTS_EXTRA_CPPFLAGS="$RGB_CPPFLAGS" \
    -DBOARD_ROOT="$WORKSPACE_DIR/zmk" \
    -DDTS_ROOT="$WORKSPACE_DIR/zmk"
echo "  ZMK app: OK"

rm -f "$OVERRIDE_CONF"

# ── Collect artifacts into dist/ ─────────────────────────────────────────────
echo ""
echo "Collecting artifacts to dist/..."
DIST="$WORKSPACE_DIR/dist"
mkdir -p "$DIST"

[ "$SKIP_BRIDGE"   = false ] && \
    cp "build-bridge/zephyr/zmk.bin"         "$DIST/crush80-ota-bridge.bin"
cp "$APP_BUILD_DIR/zephyr/zmk.signed.bin" "$DIST/$APP_NAME.signed.bin"
cp "$APP_BUILD_DIR/zephyr/zmk.bin" "$DIST/$APP_NAME.bin"
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
if [ "$SKIP_BRIDGE" = false ]; then
    echo "  dist/crush80-ota-bridge.bin"
fi
if [ "$SKIP_MCUBOOT" = false ]; then
    echo "  dist/crush80-mcuboot.bin"
fi
echo "  dist/$APP_NAME.signed.bin"
echo "=============================================="
