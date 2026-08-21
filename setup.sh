#!/bin/bash
# One-time environment setup for Wobkey Crush 80 ZMK firmware.
# Supports macOS (arm64/x86_64) and Linux (Ubuntu/Debian).
#
# Usage: bash setup.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE_DIR="$HOME/Projects/crush80-workspace"
SDK_VERSION="0.17.0"
SDK_DIR="$HOME/zephyr-sdk-$SDK_VERSION"

OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Darwin)
        case "$ARCH" in
            arm64)  SDK_PLATFORM="macos-aarch64" ;;
            x86_64) SDK_PLATFORM="macos-x86_64" ;;
            *)      echo "ERROR: Unsupported macOS architecture: $ARCH"; exit 1 ;;
        esac
        ;;
    Linux)
        case "$ARCH" in
            x86_64)  SDK_PLATFORM="linux-x86_64" ;;
            aarch64) SDK_PLATFORM="linux-aarch64" ;;
            *)       echo "ERROR: Unsupported Linux architecture: $ARCH"; exit 1 ;;
        esac
        ;;
    *)
        echo "ERROR: Unsupported OS: $OS"
        exit 1
        ;;
esac

SDK_URL="https://github.com/zephyrproject-rtos/sdk-ng/releases/download/v${SDK_VERSION}/zephyr-sdk-${SDK_VERSION}_${SDK_PLATFORM}.tar.xz"

echo "=============================================="
echo "  Crush 80 ZMK firmware environment setup"
echo "  OS: $OS ($ARCH)"
echo "=============================================="
echo ""

# ── 1. System packages ──────────────────────────────────────────────────────
echo "[1/7] Installing system packages..."
if [[ "$OS" == "Darwin" ]]; then
    BREW_PACKAGES=(cmake ninja dtc protobuf python3 wget xz)
    MISSING=()
    for pkg in "${BREW_PACKAGES[@]}"; do
        if ! brew list "$pkg" &>/dev/null; then
            MISSING+=("$pkg")
        fi
    done
    if [[ ${#MISSING[@]} -gt 0 ]]; then
        echo "    Installing: ${MISSING[*]}"
        brew install "${MISSING[@]}"
    else
        echo "    All Homebrew packages already installed."
    fi
else
    sudo apt-get update -qq
    sudo apt-get install -y -q \
        git cmake ninja-build python3-pip wget xz-utils \
        libusb-1.0-0-dev libhidapi-dev file protobuf-compiler \
        device-tree-compiler
fi
echo "    System packages: OK"

# ── 2. Python tools ─────────────────────────────────────────────────────────
echo "[2/7] Installing Python tools..."
if [[ "$OS" == "Darwin" ]]; then
    pip3 install -r "$REPO_DIR/requirements.txt"
else
    pip3 install --break-system-packages -r "$REPO_DIR/requirements.txt"
fi
echo "    Python tools installed."

# Ensure west is on PATH
if ! command -v west &>/dev/null; then
    WEST_BIN="$(python3 -c 'import site; print(site.getusersitepackages().replace("lib/python", "bin").split("/lib")[0] + "/bin")' 2>/dev/null || echo "$HOME/.local/bin")"
    if [[ -x "$WEST_BIN/west" ]]; then
        export PATH="$WEST_BIN:$PATH"
    elif [[ -x "$HOME/.local/bin/west" ]]; then
        export PATH="$HOME/.local/bin:$PATH"
    elif [[ -x "$(python3 -m site --user-base)/bin/west" ]]; then
        export PATH="$(python3 -m site --user-base)/bin:$PATH"
    fi
fi

if command -v west &>/dev/null; then
    echo "    west: $(west --version)"
else
    echo "    WARNING: west not found on PATH. You may need to add its bin dir to PATH."
    echo "    Try: export PATH=\"\$(python3 -m site --user-base)/bin:\$PATH\""
fi

# ── 3. Zephyr SDK ───────────────────────────────────────────────────────────
echo "[3/7] Zephyr SDK $SDK_VERSION ($SDK_PLATFORM)..."
if [[ -f "$SDK_DIR/riscv64-zephyr-elf/bin/riscv64-zephyr-elf-gcc" ]]; then
    echo "    SDK already present at $SDK_DIR — skipping download."
else
    echo "    Downloading (~500 MB)..."
    cd "$HOME"
    wget -q --show-progress "$SDK_URL" -O "zephyr-sdk-${SDK_VERSION}_${SDK_PLATFORM}.tar.xz"
    echo "    Extracting..."
    tar xf "zephyr-sdk-${SDK_VERSION}_${SDK_PLATFORM}.tar.xz"
    rm "zephyr-sdk-${SDK_VERSION}_${SDK_PLATFORM}.tar.xz"
    echo "    Running SDK setup (RISC-V toolchain)..."
    cd "$SDK_DIR"
    ./setup.sh -t riscv64-zephyr-elf -h
    echo "    SDK installed."
fi

# ── 4. West workspace ────────────────────────────────────────────────────────
echo "[4/7] West workspace at $WORKSPACE_DIR..."
if [[ -d "$WORKSPACE_DIR/.west" ]]; then
    echo "    Workspace already initialised — running west update..."
    cd "$WORKSPACE_DIR"
    west update
else
    mkdir -p "$WORKSPACE_DIR"
    cp -r "$REPO_DIR/zmk"               "$WORKSPACE_DIR/"
    cp -r "$REPO_DIR/conf"              "$WORKSPACE_DIR/"
    cp -r "$REPO_DIR/patches"           "$WORKSPACE_DIR/"
    cp    "$REPO_DIR/fetch_ble_blob.sh" "$WORKSPACE_DIR/" 2>/dev/null || true
    cd "$WORKSPACE_DIR"
    west init -l zmk
    west update
fi
echo "    West workspace: OK"

# ── 5. Telink BLE blob ───────────────────────────────────────────────────────
echo "[5/7] Telink BLE blob..."
cd "$WORKSPACE_DIR"
if [[ -f "$WORKSPACE_DIR/fetch_ble_blob.sh" ]]; then
    bash fetch_ble_blob.sh
else
    echo "    fetch_ble_blob.sh not found — skipping (may need manual download)."
fi

# ── 6. Zephyr Python requirements + cmake registration ───────────────────────
echo "[6/7] Zephyr Python requirements and cmake package..."
if [[ -f "$WORKSPACE_DIR/zephyr/scripts/requirements.txt" ]]; then
    if [[ "$OS" == "Darwin" ]]; then
        pip3 install -r "$WORKSPACE_DIR/zephyr/scripts/requirements.txt" -q
    else
        pip3 install --break-system-packages -r "$WORKSPACE_DIR/zephyr/scripts/requirements.txt" -q
    fi
fi
if [[ -f "$WORKSPACE_DIR/zephyr/share/zephyr-package/cmake/zephyr_export.cmake" ]]; then
    cmake -P "$WORKSPACE_DIR/zephyr/share/zephyr-package/cmake/zephyr_export.cmake"
fi

# ── 7. Go toolchain + mcumgr ─────────────────────────────────────────────────
echo "[7/7] Go toolchain and mcumgr..."
if command -v go &>/dev/null; then
    echo "    Go already installed: $(go version)"
else
    if [[ "$OS" == "Darwin" ]]; then
        echo "    Installing Go via Homebrew..."
        brew install go
    else
        GO_VERSION="1.22.5"
        echo "    Installing Go $GO_VERSION..."
        wget -q --show-progress "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz" -O /tmp/go.tar.gz
        sudo rm -rf /usr/local/go
        sudo tar -C /usr/local -xzf /tmp/go.tar.gz
        rm /tmp/go.tar.gz
        export PATH="/usr/local/go/bin:$HOME/go/bin:$PATH"
    fi
fi

if [[ -x "$HOME/go/bin/mcumgr" ]]; then
    echo "    mcumgr already installed."
else
    echo "    Installing mcumgr..."
    go install github.com/apache/mynewt-mcumgr-cli/mcumgr@latest
    echo "    mcumgr installed: $HOME/go/bin/mcumgr"
fi

# ── Apply patches ────────────────────────────────────────────────────────────
echo "Applying patches..."
if [[ -f "$REPO_DIR/patches/apply-patches.sh" ]]; then
    bash "$REPO_DIR/patches/apply-patches.sh" "$WORKSPACE_DIR"
fi

# ── Write workspace path for build.sh ────────────────────────────────────────
echo "WORKSPACE_DIR=$WORKSPACE_DIR" > "$REPO_DIR/.workspace_path"

echo ""
echo "=============================================="
echo "  Setup complete!"
echo ""
echo "  Workspace: $WORKSPACE_DIR"
echo "  SDK:       $SDK_DIR"
echo ""
echo "  Next: bash build.sh"
echo "  Then: bash flash.sh"
echo "=============================================="
