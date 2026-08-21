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
echo "[1/7] Installing system packages (needs sudo)..."
sudo apt-get update -qq
sudo apt-get install -y -q \
    git cmake ninja-build python3-pip wget xz-utils \
    libusb-1.0-0-dev libhidapi-dev file protobuf-compiler
echo "    System packages installed."

# ── 2. Python tools ─────────────────────────────────────────────────────────
echo "[2/7] Installing Python tools..."
pip3 install --break-system-packages -r "$REPO_DIR/requirements.txt"
echo "    Python tools installed. west: $(west --version 2>/dev/null || echo 'check PATH')"

# Add ~/.local/bin to PATH for this session and future shells
if ! echo "$PATH" | grep -q "$HOME/.local/bin"; then
    export PATH="$HOME/.local/bin:$PATH"
    echo "export PATH=\$HOME/.local/bin:\$PATH" >> "$HOME/.bashrc"
    echo "    Added ~/.local/bin to PATH."
fi

# ── 3. Zephyr SDK 0.17.0 ────────────────────────────────────────────────────
echo "[3/7] Zephyr SDK 0.17.0..."
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
echo "[4/7] West workspace at $WORKSPACE_DIR..."
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
echo "[5/7] Telink BLE blob..."
cd "$WORKSPACE_DIR"
bash fetch_ble_blob.sh

# ── 6. Zephyr Python requirements + cmake registration ───────────────────────
echo "[6/7] Zephyr Python requirements and cmake package..."
pip3 install --break-system-packages -r "$WORKSPACE_DIR/zephyr/scripts/requirements.txt" -q
cmake -P "$WORKSPACE_DIR/zephyr/share/zephyr-package/cmake/zephyr_export.cmake"

# ── 7. Go toolchain + mcumgr (required for firmware flashing) ────────────────
echo "[7/7] Go toolchain and mcumgr..."
GO_VERSION="1.22.5"
GO_DIR="/usr/local/go"
if [ -x "$GO_DIR/bin/go" ]; then
    echo "    Go already installed: $($GO_DIR/bin/go version)"
else
    echo "    Installing Go $GO_VERSION..."
    wget -q --show-progress "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz" -O /tmp/go.tar.gz
    sudo rm -rf "$GO_DIR"
    sudo tar -C /usr/local -xzf /tmp/go.tar.gz
    rm /tmp/go.tar.gz
    echo "    Go installed: $($GO_DIR/bin/go version)"
fi

export PATH="$GO_DIR/bin:$HOME/go/bin:$PATH"
if ! echo "$PATH" | grep -q "$GO_DIR/bin"; then
    echo "export PATH=$GO_DIR/bin:\$HOME/go/bin:\$PATH" >> "$HOME/.bashrc"
fi

if [ -x "$HOME/go/bin/mcumgr" ]; then
    echo "    mcumgr already installed."
else
    echo "    Installing mcumgr..."
    "$GO_DIR/bin/go" install github.com/apache/mynewt-mcumgr-cli/mcumgr@latest
    echo "    mcumgr installed: $HOME/go/bin/mcumgr"
fi

# ── Apply patches ────────────────────────────────────────────────────────────
echo "Applying patches..."
bash "$REPO_DIR/patches/apply-patches.sh" "$WORKSPACE_DIR"

# ── Write workspace path for build.sh ────────────────────────────────────────
echo "WORKSPACE_DIR=$WORKSPACE_DIR" > "$REPO_DIR/.workspace_path"

echo ""
echo "=============================================="
echo "  Setup complete!"
echo ""
echo "  Next: bash build.sh"
echo "  Then: bash flash.sh"
echo "=============================================="
