#!/bin/bash
# Fetch the firmware built by GitHub Actions for a commit, verify it, and print the flash command.
# Usage: scripts/ci/fetch-build.sh [commit-sha|run-id]     (default: current HEAD)
# Read-only toward the board: this never flashes. Flash only through ./crush80 update.
set -euo pipefail
cd "$(dirname "$0")/../.."

want="${1:-$(git rev-parse HEAD)}"
if [[ "$want" =~ ^[0-9]{6,}$ ]]; then
    run="$want"
else
    run="$(gh run list --workflow build.yml --commit "$want" --status success --limit 1 --json databaseId --jq '.[0].databaseId')"
    [ -n "$run" ] && [ "$run" != "null" ] || { echo "No successful build run for $want. Push it and wait for CI."; exit 1; }
fi
sha="$(gh run view "$run" --json headSha --jq .headSha)"
dir="ci-downloads/$run"
[ ! -e "$dir" ] || { echo "$dir already exists; refusing to mix downloads. Remove it first."; exit 1; }
mkdir -p "$dir"
gh run download "$run" --dir "$dir"
art="$(echo "$dir"/crush80-firmware-*)"
(cd "$art" && shasum -a 256 -c SHA256SUMS)
echo "Built from commit: $sha  (local HEAD: $(git rev-parse HEAD))"
cat "$art/BUILD-INFO.txt"
for f in "$art"/*.bin; do ./crush80 check "$f"; done
echo
echo "Verified. Next, with the board connected:"
echo "  ./crush80 update $art/crush80-zmk-app.signed.bin        # plain"
echo "  ./crush80 update $art/crush80-zmk-app-rgb.signed.bin    # RGB (after T1-T4 pass)"
