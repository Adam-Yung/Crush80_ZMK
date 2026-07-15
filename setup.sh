#!/bin/bash
# One-time environment setup for Wobkey Crush 80 ZMK firmware.
# Run this once from the repo root in WSL Ubuntu 24.04.
# Requires sudo for apt packages.
#
# Usage: bash setup.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE_DIR="$HOME/Projects/crush80-workspace"
SDK_DIR="$HOME/zephyr-sdk-0.17.0"
SDK_URL="https://github.com/zephyrproject-rtos/sdk-ng/releases/download/v0.17.0/zephyr-sdk-0.17.0_linux-x86_64.tar.xz"

echo "=============================================="
echo "  Crush 80 ZMK firmware environment setup"
echo "=============================================="
echo ""

# ── 1. System packages ──────────────────────────────────────────────────────
echo "[1/6] Installing system packages (needs sudo)..."
sudo apt-get update -qq
sudo apt-get install -y -q \
    git cmake ninja-build python3-pip wget xz-utils \
    libusb-1.0-0-dev file protobuf-compiler
echo "    System packages installed."

# ── 2. Python tools ─────────────────────────────────────────────────────────
echo "[2/6] Installing Python tools..."
pip3 install --break-system-packages -r "$REPO_DIR/requirements.txt"
echo "    Python tools installed. west: $(west --version 2>/dev/null || echo 'check PATH')"

# Add ~/.local/bin to PATH for this session and future shells
if ! echo "$PATH" | grep -q "$HOME/.local/bin"; then
    export PATH="$HOME/.local/bin:$PATH"
    echo "export PATH=\$HOME/.local/bin:\$PATH" >> "$HOME/.bashrc"
    echo "    Added ~/.local/bin to PATH."
fi

# ── 3. Zephyr SDK 0.17.0 ────────────────────────────────────────────────────
echo "[3/6] Zephyr SDK 0.17.0..."
if [ -f "$SDK_DIR/riscv64-zephyr-elf/bin/riscv64-zephyr-elf-gcc" ]; then
    echo "    SDK already present at $SDK_DIR — skipping download."
else
    echo "    Downloading (~500 MB)..."
    cd "$HOME"
    wget -q --show-progress "$SDK_URL"
    tar xf zephyr-sdk-0.17.0_linux-x86_64.tar.xz
    rm zephyr-sdk-0.17.0_linux-x86_64.tar.xz
    echo "    Extracted. Running setup..."
    cd "$SDK_DIR"
    ./setup.sh -t riscv64-zephyr-elf -h
fi

# ── 4. West workspace ────────────────────────────────────────────────────────
echo "[4/6] West workspace at $WORKSPACE_DIR..."
if [ -d "$WORKSPACE_DIR/.west" ]; then
    echo "    Workspace already initialised — running west update..."
    cd "$WORKSPACE_DIR"
    export PATH="$HOME/.local/bin:$PATH"
    west update
else
    mkdir -p "$WORKSPACE_DIR"
    # Copy our zmk module into the workspace location
    cp -r "$REPO_DIR/zmk"            "$WORKSPACE_DIR/"
    cp -r "$REPO_DIR/conf"           "$WORKSPACE_DIR/"
    cp -r "$REPO_DIR/patches"        "$WORKSPACE_DIR/"
    cp    "$REPO_DIR/fetch_ble_blob.sh" "$WORKSPACE_DIR/"
    cp    "$REPO_DIR/build.sh"       "$WORKSPACE_DIR/build_from_workspace.sh"
    cd "$WORKSPACE_DIR"
    export PATH="$HOME/.local/bin:$PATH"
    west init -l zmk
    west update
fi

# ── 5. Telink BLE blob ───────────────────────────────────────────────────────
echo "[5/6] Telink BLE blob..."
cd "$WORKSPACE_DIR"
bash fetch_ble_blob.sh

# ── 6. Zephyr Python requirements + cmake registration ───────────────────────
echo "[6/6] Zephyr Python requirements and cmake package..."
pip3 install --break-system-packages -r "$WORKSPACE_DIR/zephyr/scripts/requirements.txt" -q
cmake -P "$WORKSPACE_DIR/zephyr/share/zephyr-package/cmake/zephyr_export.cmake"

# ── Apply patches ────────────────────────────────────────────────────────────
echo "Applying patches..."
cd "$WORKSPACE_DIR/zmk-src"
git apply "$WORKSPACE_DIR/patches/zmk-src/0001-zmk-usb-no-vbus-detect.patch" 2>/dev/null \
    && echo "    ZMK patch applied." || echo "    ZMK patch already applied."
cd "$WORKSPACE_DIR/modules/hal/hal_telink"
git apply "$WORKSPACE_DIR/patches/hal_telink/0001-exclude-sys-for-BT_HCI_B91.patch" 2>/dev/null \
    && echo "    hal_telink patch applied." || echo "    hal_telink patch already applied."

# ── Write workspace path for build.sh ────────────────────────────────────────
echo "WORKSPACE_DIR=$WORKSPACE_DIR" > "$REPO_DIR/.workspace_path"

echo ""
echo "=============================================="
echo "  Setup complete!"
echo ""
echo "  Next: bash build.sh"
echo "  Then: bash flash.sh"
echo "=============================================="
