# Keymap and firmware: where things live and how to change them

**The personal keymap is not in this repo.** This repository is public. Your keymap (and the text macros in it) lives in the **private** repository `Adam-Yung/keybindings`
(checked 2026-11-20: visibility PRIVATE; it is also a submodule of the private `Adam-Yung/DOTFILES`, `~/.config/DOTFILES/keybindings`).
This repo carries only generic keymaps: `keymaps/stock.keymap` (the default) and `keymaps/example.keymap`. `scripts/gate/verify.sh` fails if any other `.keymap` is tracked.
Reasoning: `decisions/keymap-private.md`.

| What | Where | Visible to |
|---|---|---|
| Firmware source, drivers, patches, tools, CI recipe | `Adam-Yung/Crush80_ZMK` (this repo) | public |
| Personal keymap `crush80-zmk/crush80.keymap`, `crush80-zmk/app.conf`, the kanata configs | `Adam-Yung/keybindings` | private |
| The build workflow that combines the two, and its artifacts | `keybindings/.github/workflows/crush80-zmk.yml` | private |

## Change the keymap

1. The keymap is **generated**: edit `~/.config/DOTFILES/keybindings/crush80-zmk/tools/gen_keymap.py` (layers, colours, overrides), run `python3 crush80-zmk/tools/gen_keymap.py`, then `python3 crush80-zmk/tools/gen_docs.py` (redraws `Keymap.md` and stops if the firmware layout drifts from the Kanata configs). Editing `crush80.keymap` by hand also works, but the next generator run overwrites it.
   - Every layer needs exactly 86 bindings (the matrix, 16 + 17 + 17 + 13 + 13 + 10 per row group). The generator asserts it.
   - There are 13 layers (macOS and Windows copies); the highest active layer wins, so each Windows layer must sit directly above its macOS layer (`decisions/os-layers.md`).
   - Backlight colours are in the `rgb_scheme` node the generator writes at the bottom (`features/rgb.md`). A keymap with that node builds the per-key engine; without it the RGB build falls back to ZMK underglow.
   - Text macros (such as the one on ExtNav + 1) are typed text; they stay in this private file only; the generator keeps the existing one.
2. Commit and push **in the keybindings repo** (`git -C ~/.config/DOTFILES/keybindings commit ...; git push`). The push starts the build in GitHub Actions.
3. When the run is green, fetch it (below) and flash it with `./crush80 update`.

No local toolchain is needed for this. A local build (`bash build.sh --rgb`) still works if the west workspace exists: `build.sh` prefers `~/.config/DOTFILES/keybindings/crush80-zmk/` over `keymaps/stock.keymap`.

## Load a new firmware or keymap onto the board

```bash
# 1. find the run (private repo) and wait for it to be green
gh run list -R Adam-Yung/keybindings --workflow crush80-zmk.yml -L 3
# 2. download, verify hashes, validate the images offline (never flashes)
scripts/ci/fetch-build.sh <run-id> Adam-Yung/keybindings
# 3. flash as a trial: it prints the exact command
./crush80 update ci-downloads/<run-id>/crush80-firmware-*/crush80-zmk-app-rgb.signed.bin
```

`update` uploads to slot 1, marks one trial boot, and asks you to unplug, wait 3 s and replug. Test the keyboard (typing, every layer, colours), then answer `y` to confirm.
Anything else, or a power cycle before confirming, restores the previous image. Details and the failure cases: `install-and-upgrade.md`.

If `./crush80 update` stalls during the upload (seen 2026-11-20 on the running ZMK image, cause unknown), Ctrl-C is safe, nothing is marked until the upload verifies. The manual route that worked:

```bash
P=$(ls /dev/cu.usbmodem*)
~/go/bin/mcumgr --conntype serial --connstring "dev=$P,baud=115200" -t 5 -r 2 image upload IMAGE.signed.bin
~/go/bin/mcumgr --conntype serial --connstring "dev=$P,baud=115200" -t 10 image list     # slot 1 hash must equal the image's sha256
~/go/bin/mcumgr --conntype serial --connstring "dev=$P,baud=115200" -t 10 image test <that full hash>
# unplug, wait 3 s, replug, wait 15 s, then:
./crush80 status        # new hash active? test it, then: ./crush80 confirm
```

## Update the firmware itself (drivers, patches, tools)

Work in this repo on a branch; `scripts/gate/verify.sh` must be green; push. This repo's own CI builds the generic keymap (plain and RGB) as a compile check.
The private workflow pins the firmware commit it builds (`firmware_ref`). To take new firmware, change that SHA in `keybindings/.github/workflows/crush80-zmk.yml`, push, and fetch the new run. Pinning means a push to this public repo can never change what your keyboard gets.

## The reusable workflow

`.github/workflows/build.yml` here also runs as a reusable workflow (`workflow_call`) with inputs `firmware_repo`, `firmware_ref`, `keymap_path`, `app_conf_path`.
It checks out the firmware at `firmware_ref`, checks out the *calling* repo under `_caller/`, builds with the caller's keymap, and uploads the artifact to the **caller's** run, so the compiled keymap never appears in a public place.
