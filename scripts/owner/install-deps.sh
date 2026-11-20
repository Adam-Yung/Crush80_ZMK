#!/bin/bash
# Owner-run dependency install. Agents never run this (AGENTS.md, "Downloads").
#
# Dry run by default: prints what it would do. `--run` does it.
# Everything goes into ./.venv; nothing is installed system-wide.
#
#   Item                         Why
#   west, pyelftools, pykwalify  build the firmware (west workspace, ELF post-processing)
#   protobuf, grpcio-tools       ZMK Studio code generation
#   hidapi                       scripts/flash_ota.py: stock -> ZMK first install over USB HID
#   zephyr base requirements     pyyaml, packaging, etc. that the Zephyr build imports
#
# Not installed here (already present or fetched by their own pinned+hashed scripts):
#   mcumgr          go install github.com/apache/mynewt-mcumgr-cli/mcumgr@latest  (-> ~/go/bin/mcumgr)
#   BLE blob        bash fetch_ble_blob.sh   (pinned commit, SHA-256 verified)
#   west workspace  bash setup.sh
set -euo pipefail
cd "$(dirname "$0")/../.."

RUN=0
[[ "${1:-}" == "--run" ]] && RUN=1

WORKSPACE="$(sed -n 's/^WORKSPACE_DIR=//p' .workspace_path 2>/dev/null || true)"
ZEPHYR_REQ="${WORKSPACE:+$WORKSPACE/zephyr/scripts/requirements-base.txt}"

do_it() {
    echo "+ $*"
    if [[ $RUN -eq 1 ]]; then perl -e 'alarm shift; exec @ARGV' 900 "$@"; fi
}

echo "Crush80 dependency install ($([[ $RUN -eq 1 ]] && echo RUN || echo 'dry run: pass --run to execute'))"
do_it python3 -m venv .venv
do_it .venv/bin/pip install -r requirements.txt
if [[ -n "$ZEPHYR_REQ" && -f "$ZEPHYR_REQ" ]]; then
    do_it .venv/bin/pip install -r "$ZEPHYR_REQ"
else
    echo "(skipping Zephyr base requirements: workspace not found; run setup.sh first, then rerun this)"
fi
[[ $RUN -eq 1 ]] && echo "Done. build.sh picks up .venv automatically."
exit 0
