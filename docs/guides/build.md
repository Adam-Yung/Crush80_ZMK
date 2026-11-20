# Build

The firmware builds in a west workspace outside this repo (path in `.workspace_path`, currently `~/Projects/crush80-workspace`). `build.sh` copies the board, drivers and bindings into it and builds.

```bash
bash build.sh --skip-bridge            # stock-keymap app -> dist/crush80-zmk-app.signed.bin
bash build.sh --skip-bridge --rgb      # Reboot Pro RGB app -> dist/crush80-zmk-app-rgb.signed.bin
bash build.sh --build-mcuboot          # MCUboot -> dist/crush80-mcuboot.bin (only for a first install or SWS recovery)
```

Then `./crush80 check dist/<file>.signed.bin` before it goes anywhere.

## Build in CI (the normal route)

GitHub Actions builds the plain and RGB images on a clean runner (`.github/workflows/build.yml`), validates them offline and uploads them with a `SHA256SUMS`. Nothing is published as a release.
This repo's own run builds the generic `keymaps/stock.keymap`. The personal keymap is built by the private `keybindings` repo, which calls this workflow; see `keymap.md`.
Fetch and verify a run with `scripts/ci/fetch-build.sh <run-id> [owner/repo]`; it never flashes.

## Tools

An agent does not install any of these. The owner runs `bash scripts/owner/install-deps.sh --run` (a dry run without `--run` lists everything). It creates `./.venv` with `west`, `pyelftools`, `pykwalify`, `protobuf`,
`grpcio-tools`, `hidapi` and the Zephyr base requirements; `build.sh` uses `.venv/bin` when it exists. `mcumgr` (`~/go/bin/mcumgr`), the Zephyr SDK (`~/zephyr-sdk-0.17.0`) and the BLE blob (`bash fetch_ble_blob.sh`, pinned and SHA-256 checked)
are installed by the owner separately. `bash setup.sh` bootstraps a new machine and is owner-run.

## Patches

`patches/apply-patches.sh` applies `patches/{zephyr,hal_telink,mcuboot,zmk-src}/` to the workspace repos after `west update`. It is idempotent. Patches in a directory are a stack: later ones are written against earlier ones.

## What the gate does not cover

`scripts/gate/verify.sh` is offline and does not compile firmware. A firmware change is not finished until `build.sh` succeeds for both the plain and `--rgb` variants.
