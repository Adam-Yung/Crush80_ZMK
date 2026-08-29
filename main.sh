#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# Crush80 ZMK Master CLI
# ═══════════════════════════════════════════════════════════════════════════════
# One script to rule them all: setup, build, flash, recover, diagnose.
# Uses `gum` for beautiful TUI when available, falls back to bash builtins.
#
# Usage:
#   bash main.sh
# ═══════════════════════════════════════════════════════════════════════════════
set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
STOCK_VID="320f"
STOCK_PID="5055"
ZMK_VID="1d50"
ZMK_PID="615e"
HAS_GUM=false

# ── Color setup (disabled when stdout is not a terminal) ─────────────────────
if [[ -t 1 ]]; then
    BOLD='\033[1m'    DIM='\033[2m'
    RED='\033[0;31m'  GREEN='\033[0;32m'  YELLOW='\033[1;33m'
    CYAN='\033[0;36m' MAGENTA='\033[0;35m' NC='\033[0m'
else
    BOLD='' DIM='' RED='' GREEN='' YELLOW='' CYAN='' MAGENTA='' NC=''
fi

# ── Logging helpers ──────────────────────────────────────────────────────────
ui_info()  { echo -e "${CYAN}  [INFO]${NC} $*"; }
ui_ok()    { echo -e "${GREEN}  [ OK ]${NC} $*"; }
ui_warn()  { echo -e "${YELLOW}  [WARN]${NC} $*" >&2; }
ui_error() { echo -e "${RED}  [ERR ]${NC} $*" >&2; }
ui_step()  { echo -e "${MAGENTA}  [>>>>]${NC} ${BOLD}$*${NC}"; }
ui_dim()   { echo -e "${DIM}  $*${NC}"; }

press_enter() {
    echo ""
    read -rp "  Press Enter to continue..." _
}

# ── Trap: graceful Ctrl+C ───────────────────────────────────────────────────
cleanup() {
    echo ""
    ui_info "Interrupted. Returning to menu..."
}
trap cleanup INT

# ═══════════════════════════════════════════════════════════════════════════════
# UI ABSTRACTION LAYER — gum when available, bash builtins otherwise
# ═══════════════════════════════════════════════════════════════════════════════

detect_gum() {
    if command -v gum &>/dev/null; then
        HAS_GUM=true
    fi
}

ui_banner() {
    local text="$1"
    echo ""
    if $HAS_GUM; then
        gum style --border double --padding "1 3" --border-foreground 212 \
            --bold --foreground 212 "$text"
    else
        local len=${#text}
        local line=""
        for ((i = 0; i < len + 4; i++)); do line+="═"; done
        echo -e "${BOLD}${MAGENTA}"
        echo "  ╔${line}╗"
        echo "  ║  ${text}  ║"
        echo "  ╚${line}╝"
        echo -e "${NC}"
    fi
}

ui_choose() {
    local title="$1"
    shift
    local options=("$@")

    if $HAS_GUM; then
        local choice
        choice=$(printf '%s\n' "${options[@]}" | gum choose --header "$title" --cursor "▸ " \
            --header.foreground 212 --cursor.foreground 212 --selected.foreground 212) || return 1
        echo "$choice"
    else
        echo "" >&2
        echo -e "  ${BOLD}${title}${NC}" >&2
        echo "" >&2
        local i=1
        for opt in "${options[@]}"; do
            echo -e "    ${CYAN}${i})${NC} ${opt}" >&2
            ((i++))
        done
        echo "" >&2
        local selection
        while true; do
            read -rp "  Enter choice [1-${#options[@]}]: " selection
            if [[ "$selection" =~ ^[0-9]+$ ]] && (( selection >= 1 && selection <= ${#options[@]} )); then
                echo "${options[$((selection - 1))]}"
                return 0
            fi
            echo -e "  ${RED}Invalid choice. Try again.${NC}" >&2
        done
    fi
}

ui_confirm() {
    local prompt="$1"
    local default="${2:-no}"

    if $HAS_GUM; then
        if [[ "$default" == "yes" ]]; then
            gum confirm --default=yes "$prompt"
        else
            gum confirm "$prompt"
        fi
    else
        local hint="[y/N]"
        [[ "$default" == "yes" ]] && hint="[Y/n]"
        echo "" >&2
        read -rp "  ${prompt} ${hint} " answer
        case "$answer" in
            [Yy]*) return 0 ;;
            [Nn]*) return 1 ;;
            "")
                [[ "$default" == "yes" ]] && return 0
                return 1
                ;;
            *) return 1 ;;
        esac
    fi
}

ui_input() {
    local prompt="$1"
    local default="${2:-}"

    if $HAS_GUM; then
        if [[ -n "$default" ]]; then
            gum input --placeholder "$prompt" --value "$default"
        else
            gum input --placeholder "$prompt"
        fi
    else
        local result
        if [[ -n "$default" ]]; then
            read -rp "  ${prompt} [${default}]: " result
            echo "${result:-$default}"
        else
            read -rp "  ${prompt}: " result
            echo "$result"
        fi
    fi
}

ui_file_choose() {
    local title="$1"
    local directory="$2"
    local pattern="${3:-*.bin}"

    local files=()
    while IFS= read -r -d '' f; do
        files+=("$f")
    done < <(find "$directory" -maxdepth 1 -name "$pattern" -type f -print0 2>/dev/null | sort -z)

    if [[ ${#files[@]} -eq 0 ]]; then
        ui_warn "No ${pattern} files found in ${directory}/"
        return 1
    fi

    local labels=()
    for f in "${files[@]}"; do
        local name size
        name="$(basename "$f")"
        size="$(wc -c < "$f" 2>/dev/null | tr -d ' ')"
        labels+=("${name}  (${size} bytes)")
    done

    local chosen
    chosen=$(ui_choose "$title" "${labels[@]}") || return 1
    local idx=0
    for label in "${labels[@]}"; do
        if [[ "$label" == "$chosen" ]]; then
            echo "${files[$idx]}"
            return 0
        fi
        ((idx++))
    done
    return 1
}

ui_spin() {
    local msg="$1"
    shift
    if $HAS_GUM; then
        gum spin --spinner dot --title "$msg" -- "$@"
    else
        echo -e "  ${DIM}${msg}...${NC}"
        "$@"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# HARDWARE DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

check_usb() {
    local vid="$1" pid="$2"
    if command -v lsusb &>/dev/null; then
        lsusb -d "$vid:$pid" >/dev/null 2>&1
    elif [[ "$(uname)" == "Darwin" ]]; then
        system_profiler SPUSBDataType 2>/dev/null | grep -qi "0x${vid}.*0x${pid}" 2>/dev/null
    else
        return 1
    fi
}

detect_keyboard_state() {
    if check_usb "$ZMK_VID" "$ZMK_PID"; then
        echo "zmk"
    elif check_usb "$STOCK_VID" "$STOCK_PID"; then
        echo "stock"
    else
        echo "disconnected"
    fi
}

find_serial_port() {
    for dev in /dev/ttyACM0 /dev/ttyACM1 /dev/ttyUSB0; do
        if [[ -e "$dev" ]]; then echo "$dev"; return 0; fi
    done
    for dev in /dev/cu.usbmodem*; do
        if [[ -e "$dev" ]]; then echo "$dev"; return 0; fi
    done
    echo ""
}

find_mcumgr() {
    if command -v mcumgr &>/dev/null; then
        command -v mcumgr
    elif [[ -x "$HOME/go/bin/mcumgr" ]]; then
        echo "$HOME/go/bin/mcumgr"
    else
        echo ""
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# STARTUP DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

collect_firmware_files() {
    local files=()
    for dir in "$REPO_DIR/releases" "$REPO_DIR/dist"; do
        if [[ -d "$dir" ]]; then
            while IFS= read -r -d '' f; do
                files+=("$f")
            done < <(find "$dir" -maxdepth 1 -name "*.bin" -type f -print0 2>/dev/null)
        fi
    done
    printf '%s\n' "${files[@]}"
}

show_dashboard() {
    local kb_state serial_port workspace_path os_name

    os_name="$(uname -s)"
    kb_state="$(detect_keyboard_state)"
    serial_port="$(find_serial_port)"
    workspace_path=""
    if [[ -f "$REPO_DIR/.workspace_path" ]]; then
        workspace_path="$(cat "$REPO_DIR/.workspace_path")"
    fi

    local kb_label kb_color
    case "$kb_state" in
        zmk)          kb_label="Connected — ZMK firmware"; kb_color="$GREEN" ;;
        stock)        kb_label="Connected — Stock (Evision) firmware"; kb_color="$YELLOW" ;;
        disconnected) kb_label="Not detected"; kb_color="$RED" ;;
    esac

    echo ""
    echo -e "  ${BOLD}System Status${NC}"
    echo -e "  ${DIM}─────────────────────────────────────────────${NC}"
    echo -e "  OS:           ${BOLD}${os_name}${NC}"
    echo -e "  Keyboard:     ${kb_color}${kb_label}${NC}"
    if [[ -n "$serial_port" ]]; then
        echo -e "  Serial Port:  ${GREEN}${serial_port}${NC}"
    else
        echo -e "  Serial Port:  ${DIM}none${NC}"
    fi

    if [[ -n "$workspace_path" && -d "$workspace_path" ]]; then
        echo -e "  Workspace:    ${GREEN}${workspace_path}${NC}"
    else
        echo -e "  Workspace:    ${DIM}not set up${NC}"
    fi

    echo ""
    echo -e "  ${BOLD}Tools${NC}"
    echo -e "  ${DIM}─────────────────────────────────────────────${NC}"
    local tools=("python3" "west" "go" "mcumgr" "gum")
    for tool in "${tools[@]}"; do
        if [[ "$tool" == "mcumgr" ]]; then
            local mp
            mp="$(find_mcumgr)"
            if [[ -n "$mp" ]]; then
                echo -e "  ${GREEN}✓${NC} ${tool}  ${DIM}(${mp})${NC}"
            else
                echo -e "  ${RED}✗${NC} ${tool}"
            fi
        else
            local tp
            tp="$(command -v "$tool" 2>/dev/null || true)"
            if [[ -n "$tp" ]]; then
                echo -e "  ${GREEN}✓${NC} ${tool}  ${DIM}(${tp})${NC}"
            else
                echo -e "  ${RED}✗${NC} ${tool}"
            fi
        fi
    done

    local fw_files
    fw_files="$(collect_firmware_files)"
    echo ""
    echo -e "  ${BOLD}Available Firmware${NC}"
    echo -e "  ${DIM}─────────────────────────────────────────────${NC}"
    if [[ -z "$fw_files" ]]; then
        echo -e "  ${DIM}No firmware files found in releases/ or dist/${NC}"
    else
        while IFS= read -r f; do
            [[ -z "$f" ]] && continue
            local name size
            name="$(basename "$f")"
            size="$(wc -c < "$f" 2>/dev/null | tr -d ' ')"
            local dir_label
            if [[ "$f" == *"/releases/"* ]]; then
                dir_label="releases"
            else
                dir_label="dist"
            fi
            echo -e "  ${GREEN}•${NC} ${name}  ${DIM}(${size} bytes, ${dir_label}/)${NC}"
        done <<< "$fw_files"
    fi
    echo ""
}

# ═══════════════════════════════════════════════════════════════════════════════
# FIRMWARE FILE CHOOSER (shared by flash/recovery flows)
# ═══════════════════════════════════════════════════════════════════════════════

choose_firmware() {
    local title="${1:-Select firmware to flash}"
    local dirs=("$REPO_DIR/releases" "$REPO_DIR/dist")
    local files=()

    for dir in "${dirs[@]}"; do
        if [[ -d "$dir" ]]; then
            while IFS= read -r -d '' f; do
                files+=("$f")
            done < <(find "$dir" -maxdepth 1 -name "*.bin" -type f -print0 2>/dev/null | sort -z)
        fi
    done

    if [[ ${#files[@]} -eq 0 ]]; then
        ui_warn "No .bin firmware files found in releases/ or dist/."
        ui_info "Build firmware first: bash build.sh"
        return 1
    fi

    local labels=()
    for f in "${files[@]}"; do
        local name size dir_label
        name="$(basename "$f")"
        size="$(wc -c < "$f" 2>/dev/null | tr -d ' ')"
        if [[ "$f" == *"/releases/"* ]]; then dir_label="releases"; else dir_label="dist"; fi
        labels+=("[${dir_label}] ${name}  (${size} bytes)")
    done
    labels+=("Enter a custom path...")

    local chosen
    chosen=$(ui_choose "$title" "${labels[@]}") || return 1

    if [[ "$chosen" == "Enter a custom path..." ]]; then
        local custom
        custom=$(ui_input "Full path to .bin firmware file")
        custom="${custom/#\~/$HOME}"
        if [[ ! -f "$custom" ]]; then
            ui_error "File not found: $custom"
            return 1
        fi
        echo "$custom"
        return 0
    fi

    local idx=0
    for label in "${labels[@]}"; do
        if [[ "$label" == "$chosen" ]]; then
            echo "${files[$idx]}"
            return 0
        fi
        ((idx++))
    done
    return 1
}

# ═══════════════════════════════════════════════════════════════════════════════
# MENU 1: FIRST-TIME SETUP & INSTALL
# ═══════════════════════════════════════════════════════════════════════════════

menu_setup_install() {
    local choice
    choice=$(ui_choose "First-Time Setup & Install" \
        "Run environment setup (install tools, SDK, workspace)" \
        "Install ZMK on stock keyboard" \
        "Full setup + install (both of the above)" \
        "Back to main menu") || return 0

    case "$choice" in
        "Run environment setup"*)
            ui_step "Running setup.sh..."
            echo ""
            bash "$REPO_DIR/setup.sh"
            ui_ok "Environment setup complete."
            press_enter
            ;;
        "Install ZMK on stock"*)
            do_install_zmk
            press_enter
            ;;
        "Full setup + install"*)
            ui_step "Running setup.sh..."
            echo ""
            bash "$REPO_DIR/setup.sh"
            ui_ok "Environment setup complete."
            echo ""
            do_install_zmk
            press_enter
            ;;
        "Back"*) return 0 ;;
    esac
}

do_install_zmk() {
    local kb_state
    kb_state="$(detect_keyboard_state)"

    if [[ "$kb_state" == "zmk" ]]; then
        ui_warn "Keyboard is already running ZMK firmware."
        ui_info "Use 'Flash / Update Firmware' to update, or 'Revert to Stock' first."
        return 0
    fi
    if [[ "$kb_state" == "disconnected" ]]; then
        ui_error "Keyboard not detected on USB."
        ui_info "Connect the keyboard (running stock firmware) and try again."
        return 1
    fi

    local bridge="$REPO_DIR/dist/crush80-ota-bridge.bin"
    local app="$REPO_DIR/dist/crush80-zmk-app.signed.bin"

    if [[ ! -f "$bridge" || ! -f "$app" ]]; then
        ui_warn "Required build artifacts not found in dist/."
        ui_info "Need: crush80-ota-bridge.bin and crush80-zmk-app.signed.bin"
        if ui_confirm "Build them now?"; then
            ui_step "Building all firmware..."
            echo ""
            bash "$REPO_DIR/build.sh"
            ui_ok "Build complete."
            echo ""
        else
            ui_info "Run 'bash build.sh' first, then retry."
            return 1
        fi
    fi

    ui_step "Installing ZMK on stock keyboard..."
    echo ""
    bash "$REPO_DIR/install_zmk.sh"
    ui_ok "ZMK installation complete."
}

# ═══════════════════════════════════════════════════════════════════════════════
# MENU 2: BUILD FIRMWARE
# ═══════════════════════════════════════════════════════════════════════════════

menu_build() {
    local choice
    choice=$(ui_choose "Build Firmware" \
        "Build ZMK app only (fast, default)" \
        "Build everything (app + bridge + bootloader)" \
        "Build with custom keymap" \
        "Back to main menu") || return 0

    case "$choice" in
        "Build ZMK app only"*)
            ui_step "Building ZMK application (skipping bridge + MCUboot)..."
            echo ""
            bash "$REPO_DIR/build.sh" --skip-bridge --skip-mcuboot
            ui_ok "Build complete. Output: dist/crush80-zmk-app.signed.bin"
            press_enter
            ;;
        "Build everything"*)
            ui_step "Building all targets (app + bridge + MCUboot)..."
            echo ""
            bash "$REPO_DIR/build.sh" --build-mcuboot
            ui_ok "Full build complete. Check dist/ for all artifacts."
            press_enter
            ;;
        "Build with custom keymap"*)
            do_build_custom_keymap
            press_enter
            ;;
        "Back"*) return 0 ;;
    esac
}

do_build_custom_keymap() {
    local keymap_dir="$REPO_DIR/keymaps"
    local keymaps=()

    if [[ -d "$keymap_dir" ]]; then
        while IFS= read -r -d '' f; do
            keymaps+=("$(basename "$f")")
        done < <(find "$keymap_dir" -maxdepth 1 -name "*.keymap" -type f -print0 2>/dev/null | sort -z)
    fi

    if [[ ${#keymaps[@]} -eq 0 ]]; then
        ui_warn "No .keymap files found in keymaps/"
        local custom
        custom=$(ui_input "Full path to .keymap file")
        custom="${custom/#\~/$HOME}"
        if [[ ! -f "$custom" ]]; then
            ui_error "File not found: $custom"
            return 1
        fi
        ui_step "Building with keymap: $custom"
        echo ""
        CRUSH80_KEYMAP="$custom" bash "$REPO_DIR/build.sh" --skip-bridge --skip-mcuboot
    else
        keymaps+=("Enter a custom path...")
        local chosen
        chosen=$(ui_choose "Select keymap" "${keymaps[@]}") || return 0

        if [[ "$chosen" == "Enter a custom path..." ]]; then
            local custom
            custom=$(ui_input "Full path to .keymap file")
            custom="${custom/#\~/$HOME}"
            if [[ ! -f "$custom" ]]; then
                ui_error "File not found: $custom"
                return 1
            fi
            ui_step "Building with keymap: $custom"
            echo ""
            CRUSH80_KEYMAP="$custom" bash "$REPO_DIR/build.sh" --skip-bridge --skip-mcuboot
        else
            local keymap_path="${keymap_dir}/${chosen}"
            ui_step "Building with keymap: $chosen"
            echo ""
            CRUSH80_KEYMAP="$keymap_path" bash "$REPO_DIR/build.sh" --skip-bridge --skip-mcuboot
        fi
    fi

    ui_ok "Build complete. Output: dist/crush80-zmk-app.signed.bin"
}

# ═══════════════════════════════════════════════════════════════════════════════
# MENU 3: FLASH / UPDATE FIRMWARE
# ═══════════════════════════════════════════════════════════════════════════════

menu_flash() {
    local kb_state
    kb_state="$(detect_keyboard_state)"

    if [[ "$kb_state" == "disconnected" ]]; then
        ui_error "Keyboard not detected on USB."
        ui_info "Connect the keyboard and try again."
        press_enter
        return 0
    fi
    if [[ "$kb_state" == "stock" ]]; then
        ui_warn "Keyboard is running stock firmware."
        ui_info "Use 'First-Time Setup & Install' to install ZMK first."
        press_enter
        return 0
    fi

    local firmware
    firmware=$(choose_firmware "Select firmware to flash") || { press_enter; return 0; }

    local fname fsize
    fname="$(basename "$firmware")"
    fsize="$(wc -c < "$firmware" 2>/dev/null | tr -d ' ')"

    echo ""
    ui_info "Selected: ${fname} (${fsize} bytes)"
    echo ""
    ui_info "After flashing, you will need to UNPLUG and REPLUG the keyboard"
    ui_info "for MCUboot to swap to the new firmware."
    echo ""

    if ! ui_confirm "Flash this firmware?"; then
        ui_info "Cancelled."
        press_enter
        return 0
    fi

    ui_step "Flashing firmware..."
    echo ""
    bash "$REPO_DIR/update.sh" --firmware "$firmware"
    ui_ok "Flash complete. Follow the on-screen instructions to unplug/replug."
    press_enter
}

# ═══════════════════════════════════════════════════════════════════════════════
# MENU 4: REVERT TO STOCK FIRMWARE
# ═══════════════════════════════════════════════════════════════════════════════

menu_restore_stock() {
    local kb_state
    kb_state="$(detect_keyboard_state)"

    if [[ "$kb_state" == "disconnected" ]]; then
        ui_error "Keyboard not detected on USB."
        ui_info "Connect the keyboard (running ZMK) and try again."
        press_enter
        return 0
    fi
    if [[ "$kb_state" == "stock" ]]; then
        ui_ok "Keyboard is already running stock firmware."
        press_enter
        return 0
    fi

    echo ""
    ui_warn "This will erase ZMK and restore the original Evision firmware."
    ui_warn "If interrupted mid-write, the keyboard may require hardware recovery."
    ui_info "You can reinstall ZMK later with 'First-Time Setup & Install'."
    echo ""

    local stock_default="$REPO_DIR/firmware/Wobkey_Crush_80_Patched_Firmware/firmware/code_2M.bin"
    local firmware=""

    if [[ -f "$stock_default" ]]; then
        local choice
        choice=$(ui_choose "Select stock firmware" \
            "Use bundled stock firmware (code_2M.bin)" \
            "Browse for a different firmware file" \
            "Back to main menu") || return 0

        case "$choice" in
            "Use bundled"*)
                firmware="$stock_default"
                ;;
            "Browse"*)
                firmware=$(ui_input "Full path to stock firmware .bin file")
                firmware="${firmware/#\~/$HOME}"
                if [[ ! -f "$firmware" ]]; then
                    ui_error "File not found: $firmware"
                    press_enter
                    return 0
                fi
                ;;
            "Back"*) return 0 ;;
        esac
    else
        ui_info "No bundled stock firmware found."
        ui_info "Download from: https://wobkey.com/pages/support"
        firmware=$(ui_input "Full path to stock firmware .bin file")
        firmware="${firmware/#\~/$HOME}"
        if [[ ! -f "$firmware" ]]; then
            ui_error "File not found: $firmware"
            press_enter
            return 0
        fi
    fi

    local fsize
    fsize="$(wc -c < "$firmware" 2>/dev/null | tr -d ' ')"
    echo ""
    ui_info "Firmware: $(basename "$firmware") (${fsize} bytes)"
    echo ""

    if ! ui_confirm "Proceed with stock firmware restore? (IRREVERSIBLE until you reflash ZMK)"; then
        ui_info "Cancelled."
        press_enter
        return 0
    fi

    ui_step "Restoring stock firmware..."
    echo ""
    bash "$REPO_DIR/restore_stock.sh" -y "$firmware"
    ui_ok "Stock firmware restored."
    press_enter
}

# ═══════════════════════════════════════════════════════════════════════════════
# MENU 5: RECOVERY TOOLS
# ═══════════════════════════════════════════════════════════════════════════════

menu_recovery() {
    local choice
    choice=$(ui_choose "Recovery Tools — pick the right tool for your situation" \
        "Force MCUboot recovery mode (keyboard hangs ~2s after boot)" \
        "Recovery flash (SMP works briefly then dies)" \
        "Resilient upload (upload stalls after ~10-20 KB)" \
        "Unbrick multi-strategy (nothing else worked)" \
        "MCUboot revert to previous image (new firmware is bad)" \
        "Back to main menu") || return 0

    case "$choice" in
        "Force MCUboot"*)
            do_force_recovery
            press_enter
            ;;
        "Recovery flash"*)
            do_recovery_flash
            press_enter
            ;;
        "Resilient upload"*)
            do_resilient_upload
            press_enter
            ;;
        "Unbrick"*)
            do_unbrick_upload
            press_enter
            ;;
        "MCUboot revert"*)
            do_mcuboot_revert
            press_enter
            ;;
        "Back"*) return 0 ;;
    esac
}

do_force_recovery() {
    echo ""
    ui_info "Force MCUboot Recovery Mode"
    ui_dim "Erases the slot 0 image header so MCUboot enters serial recovery."
    ui_dim "Use when: keyboard hangs ~2 seconds after plug-in (irq_lock hang)."
    ui_dim "The script must send the erase command within a <2 second window."
    echo ""

    if ! ui_confirm "Proceed?"; then
        ui_info "Cancelled."
        return 0
    fi

    ui_step "Running force_recovery.py..."
    echo ""
    python3 "$REPO_DIR/scripts/force_recovery.py"
    echo ""
    ui_info "Now UNPLUG the keyboard, wait 2 seconds, then REPLUG."
    ui_info "MCUboot will enter serial recovery mode (no app runs)."
    ui_info "Then use 'Flash / Update Firmware' or 'Resilient upload' to flash good firmware."
}

do_recovery_flash() {
    echo ""
    ui_info "Recovery Flash (Race-Condition Method)"
    ui_dim "Use when: SMP responds briefly after plug-in but then dies."
    ui_dim "You will be prompted to unplug and replug the keyboard."
    echo ""

    if ! ui_confirm "Proceed?"; then
        ui_info "Cancelled."
        return 0
    fi

    ui_step "Running recovery_flash.py..."
    echo ""
    python3 "$REPO_DIR/scripts/recovery_flash.py"
}

do_resilient_upload() {
    echo ""
    ui_info "Resilient Upload (Auto-Retry on Stall)"
    ui_dim "Use when: mcumgr upload stalls after ~10-20 KB."
    ui_dim "Automatically retries without unplugging (device keeps upload state in RAM)."
    ui_dim "Do NOT unplug during upload — each unplug resets progress to 0."
    echo ""

    local firmware
    firmware=$(choose_firmware "Select firmware for resilient upload") || return 0

    if ! ui_confirm "Start resilient upload of $(basename "$firmware")?"; then
        ui_info "Cancelled."
        return 0
    fi

    ui_step "Running resilient upload..."
    echo ""
    bash "$REPO_DIR/scripts/resilient_upload.sh" "$firmware"
}

do_unbrick_upload() {
    echo ""
    ui_info "Unbrick Multi-Strategy Upload"
    ui_dim "Use when: all other methods failed."
    ui_dim "Tries 4 progressively aggressive strategies:"
    ui_dim "  1. mcumgr -w1 mtu=256 (conservative)"
    ui_dim "  2. mcumgr -w1 mtu=128 (ultra-conservative)"
    ui_dim "  3. Python smpclient (per-chunk retry)"
    ui_dim "  4. Raw SMP serial (manual CBOR framing)"
    echo ""

    local firmware
    firmware=$(choose_firmware "Select firmware for unbrick upload") || return 0

    if ! ui_confirm "Start unbrick upload of $(basename "$firmware")?"; then
        ui_info "Cancelled."
        return 0
    fi

    ui_step "Running unbrick upload..."
    echo ""
    bash "$REPO_DIR/scripts/unbrick_upload.sh" "$firmware"
}

do_mcuboot_revert() {
    echo ""
    ui_info "MCUboot Revert to Previous Image"
    ui_dim "Use when: new firmware is bad and you want to swap back to the old image."
    ui_dim "Must run IMMEDIATELY after plugging in (within 5 seconds)."
    ui_dim "The keyboard must be freshly plugged in for SMP to respond."
    echo ""

    local port
    port="$(find_serial_port)"
    if [[ -z "$port" ]]; then
        ui_warn "No serial port detected. Plug in the keyboard first."
        ui_info "You have ~5 seconds after plug-in to run this."
        if ! ui_confirm "Try anyway? (plug in now, then press Y quickly)"; then
            return 0
        fi
        local elapsed=0
        while [[ -z "$port" && $elapsed -lt 10 ]]; do
            sleep 1
            port="$(find_serial_port)"
            ((elapsed++))
        done
        if [[ -z "$port" ]]; then
            ui_error "No serial port found after 10 seconds."
            return 1
        fi
    fi

    ui_info "Using port: $port"
    if ! ui_confirm "Send revert commands now? (must be within 5s of plug-in)"; then
        ui_info "Cancelled."
        return 0
    fi

    ui_step "Running MCUboot revert..."
    echo ""
    bash "$REPO_DIR/scripts/mcuboot_revert.sh" "$port"
}

# ═══════════════════════════════════════════════════════════════════════════════
# MENU 6: DIAGNOSTICS
# ═══════════════════════════════════════════════════════════════════════════════

menu_diagnostics() {
    local choice
    choice=$(ui_choose "Diagnostics" \
        "Find Crush80 on USB" \
        "List firmware on keyboard (MCUboot image slots)" \
        "Show firmware files in repo" \
        "Check installed tools" \
        "Back to main menu") || return 0

    case "$choice" in
        "Find Crush80"*)
            do_find_usb
            press_enter
            ;;
        "List firmware on keyboard"*)
            do_image_list
            press_enter
            ;;
        "Show firmware files"*)
            do_show_firmware_files
            press_enter
            ;;
        "Check installed tools"*)
            do_check_tools
            press_enter
            ;;
        "Back"*) return 0 ;;
    esac
}

do_find_usb() {
    echo ""
    ui_step "Scanning USB devices..."
    echo ""

    local found_any=false

    if check_usb "$ZMK_VID" "$ZMK_PID"; then
        ui_ok "ZMK firmware detected (VID:PID = ${ZMK_VID}:${ZMK_PID})"
        found_any=true
    fi
    if check_usb "$STOCK_VID" "$STOCK_PID"; then
        ui_ok "Stock firmware detected (VID:PID = ${STOCK_VID}:${STOCK_PID})"
        found_any=true
    fi
    if ! $found_any; then
        ui_warn "No Crush80 keyboard found on USB."
    fi

    local port
    port="$(find_serial_port)"
    if [[ -n "$port" ]]; then
        echo ""
        ui_ok "Serial port: $port"
    else
        echo ""
        ui_warn "No serial port found."
    fi

    echo ""
    ui_info "Full USB device listing:"
    echo ""
    if command -v lsusb &>/dev/null; then
        lsusb 2>/dev/null || true
    elif [[ "$(uname)" == "Darwin" ]]; then
        system_profiler SPUSBDataType 2>/dev/null | head -80 || true
    else
        ui_dim "(no USB listing tool available)"
    fi
}

do_image_list() {
    local mcumgr_bin
    mcumgr_bin="$(find_mcumgr)"
    if [[ -z "$mcumgr_bin" ]]; then
        ui_error "mcumgr not installed. Run setup first."
        return 0
    fi

    local port
    port="$(find_serial_port)"
    if [[ -z "$port" ]]; then
        ui_error "No serial port detected. Is the keyboard connected?"
        return 0
    fi

    echo ""
    ui_step "Querying MCUboot image slots on $port..."
    echo ""

    python3 -c "
import serial, time
s = serial.Serial('$port', 115200, timeout=1)
s.dtr = True; time.sleep(0.5); s.close()
" 2>/dev/null || true

    "$mcumgr_bin" --conntype serial --connstring "dev=$port,baud=115200" image list 2>&1 || {
        ui_warn "Could not read image list. Keyboard may not be responding."
        ui_info "Try unplugging and replugging, then run this again quickly."
    }
}

do_show_firmware_files() {
    echo ""
    ui_step "Firmware files in this repository"
    echo ""

    for dir in "releases" "dist"; do
        local full_dir="$REPO_DIR/$dir"
        echo -e "  ${BOLD}${dir}/${NC}"
        if [[ ! -d "$full_dir" ]]; then
            echo -e "    ${DIM}(directory does not exist)${NC}"
        else
            local count=0
            while IFS= read -r -d '' f; do
                local name size mod_date
                name="$(basename "$f")"
                size="$(wc -c < "$f" 2>/dev/null | tr -d ' ')"
                if [[ "$(uname)" == "Darwin" ]]; then
                    mod_date="$(stat -f '%Sm' -t '%Y-%m-%d %H:%M' "$f" 2>/dev/null || echo '?')"
                else
                    mod_date="$(stat -c '%y' "$f" 2>/dev/null | cut -d. -f1 || echo '?')"
                fi
                echo -e "    ${GREEN}•${NC} ${name}"
                echo -e "      ${DIM}${size} bytes | modified ${mod_date}${NC}"
                ((count++))
            done < <(find "$full_dir" -maxdepth 1 -name "*.bin" -type f -print0 2>/dev/null | sort -z)
            if [[ $count -eq 0 ]]; then
                echo -e "    ${DIM}(no .bin files)${NC}"
            fi
        fi
        echo ""
    done
}

do_check_tools() {
    echo ""
    ui_step "Tool Check"
    echo ""

    check_tool() {
        local name="$1" cmd="$2"
        local path version
        if [[ "$name" == "mcumgr" ]]; then
            path="$(find_mcumgr)"
        else
            path="$(command -v "$cmd" 2>/dev/null || true)"
        fi

        if [[ -n "$path" ]]; then
            version=""
            case "$name" in
                python3) version="$($path --version 2>&1 | head -1)" ;;
                west)    version="$($path --version 2>&1 | head -1)" ;;
                go)      version="$($path version 2>&1 | head -1)" ;;
                gum)     version="$($path --version 2>&1 | head -1)" ;;
                cmake)   version="$($path --version 2>&1 | head -1)" ;;
            esac
            echo -e "  ${GREEN}✓${NC} ${BOLD}${name}${NC}"
            echo -e "    ${DIM}Path: ${path}${NC}"
            if [[ -n "$version" ]]; then
                echo -e "    ${DIM}Version: ${version}${NC}"
            fi
        else
            echo -e "  ${RED}✗${NC} ${BOLD}${name}${NC} — not found"
        fi
    }

    check_tool "python3" "python3"
    check_tool "west" "west"
    check_tool "go" "go"
    check_tool "mcumgr" "mcumgr"
    check_tool "cmake" "cmake"
    check_tool "gum" "gum"
    echo ""

    local sdk_path="${ZEPHYR_SDK_INSTALL_DIR:-$HOME/zephyr-sdk-0.17.0}"
    if [[ -d "$sdk_path" ]]; then
        echo -e "  ${GREEN}✓${NC} ${BOLD}Zephyr SDK${NC}"
        echo -e "    ${DIM}Path: ${sdk_path}${NC}"
    else
        echo -e "  ${RED}✗${NC} ${BOLD}Zephyr SDK${NC} — not found at ${sdk_path}"
    fi

    echo ""
    local ws_path=""
    if [[ -f "$REPO_DIR/.workspace_path" ]]; then
        ws_path="$(cat "$REPO_DIR/.workspace_path")"
    fi
    if [[ -n "$ws_path" && -d "$ws_path" ]]; then
        echo -e "  ${GREEN}✓${NC} ${BOLD}West workspace${NC}"
        echo -e "    ${DIM}Path: ${ws_path}${NC}"
    else
        echo -e "  ${RED}✗${NC} ${BOLD}West workspace${NC} — not set up (run setup.sh)"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN MENU LOOP
# ═══════════════════════════════════════════════════════════════════════════════

main() {
    detect_gum

    ui_banner "Crush80 ZMK Firmware Manager"
    show_dashboard

    while true; do
        local choice
        choice=$(ui_choose "What would you like to do?" \
            "First-Time Setup & Install" \
            "Build Firmware" \
            "Flash / Update Firmware" \
            "Revert to Stock Firmware" \
            "Recovery Tools" \
            "Diagnostics" \
            "Exit") || continue

        case "$choice" in
            "First-Time Setup"*)  menu_setup_install ;;
            "Build Firmware"*)    menu_build ;;
            "Flash / Update"*)    menu_flash ;;
            "Revert to Stock"*)   menu_restore_stock ;;
            "Recovery Tools"*)    menu_recovery ;;
            "Diagnostics"*)       menu_diagnostics ;;
            "Exit"*)
                echo ""
                ui_info "Goodbye!"
                echo ""
                exit 0
                ;;
        esac

        echo ""
    done
}

main "$@"
