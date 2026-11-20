#!/bin/bash
# Upgrade ZMK firmware on a running Crush 80. Thin wrapper over ./crush80 update (the logic and its tests live there).
#
#   bash update.sh [--build] [--rgb] [IMAGE.signed.bin]
#
# The procedure: validate the image offline, check the known-good release image, upload, mark for ONE trial boot,
# you unplug/replug, the tool checks the new image is the one running, you test the keys, and only then it confirms.
# Anything wrong: unplug and replug and the previous image is back. See docs/guides/install-and-upgrade.md.
set -euo pipefail
cd "$(dirname "$0")"

BUILD=0; RGB=0; IMAGE=""
for arg in "$@"; do
    case "$arg" in
        --build) BUILD=1 ;;
        --rgb) RGB=1 ;;
        -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
        *) IMAGE="$arg" ;;
    esac
done

if [[ $BUILD -eq 1 ]]; then
    bash build.sh --skip-bridge $([[ $RGB -eq 1 ]] && echo --rgb)
fi

if [[ -z "$IMAGE" ]]; then
    IMAGE="${CRUSH80_FIRMWARE:-dist/crush80-zmk-app$([[ $RGB -eq 1 ]] && echo -rgb).signed.bin}"
fi
exec ./crush80 update "$IMAGE"
