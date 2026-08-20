#!/bin/bash
# Apply local patches to west-managed repositories after west update.
#
# Applies patches for: zephyr, hal_telink, mcuboot, zmk-src
# Idempotent: safe to run multiple times (skips already-applied patches).
#
# Usage: ./patches/apply-patches.sh [WORKSPACE_DIR]
#   WORKSPACE_DIR defaults to the parent directory of this script's location.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_DIR="${1:-$REPO_DIR}"

if [ ! -d "$WORKSPACE_DIR/.west" ] && [ "$WORKSPACE_DIR" = "$REPO_DIR" ]; then
    echo "ERROR: No .west directory found. Pass the workspace path as argument."
    echo "Usage: $0 /path/to/west/workspace"
    exit 1
fi

PATCH_DIR="$REPO_DIR/patches"
FAILED=0

apply_patches_for_repo() {
    local repo_name="$1"
    local repo_path="$2"
    local patch_subdir="$PATCH_DIR/$repo_name"

    if [ ! -d "$patch_subdir" ]; then
        return 0
    fi

    local patches=("$patch_subdir"/*.patch)
    if [ ${#patches[@]} -eq 0 ] || [ ! -f "${patches[0]}" ]; then
        return 0
    fi

    echo "=== $repo_name (${#patches[@]} patches) ==="

    if [ ! -d "$repo_path" ]; then
        echo "  WARNING: $repo_path does not exist — skipping"
        FAILED=1
        return 0
    fi

    for patch in "${patches[@]}"; do
        local patch_name
        patch_name="$(basename "$patch")"

        # Check if already applied by trying to reverse-apply
        if git -C "$repo_path" apply --reverse --check "$patch" 2>/dev/null; then
            echo "  [skip] $patch_name (already applied)"
            continue
        fi

        # Check if it applies cleanly
        if git -C "$repo_path" apply --check "$patch" 2>/dev/null; then
            git -C "$repo_path" apply "$patch"
            echo "  [ ok ] $patch_name"
        else
            echo "  [FAIL] $patch_name — does not apply cleanly"
            FAILED=1
        fi
    done
}

echo "Applying patches from: $PATCH_DIR"
echo "Workspace: $WORKSPACE_DIR"
echo ""

apply_patches_for_repo "zmk-src"    "$WORKSPACE_DIR/zmk-src"
apply_patches_for_repo "zephyr"     "$WORKSPACE_DIR/zephyr"
apply_patches_for_repo "hal_telink" "$WORKSPACE_DIR/modules/hal/hal_telink"
apply_patches_for_repo "mcuboot"    "$WORKSPACE_DIR/bootloader/mcuboot"

echo ""
if [ $FAILED -ne 0 ]; then
    echo "WARNING: Some patches failed to apply. Check output above."
    exit 1
else
    echo "All patches applied successfully."
fi
