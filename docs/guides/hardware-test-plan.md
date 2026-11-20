# Hardware test plan

The first run on the real board of everything built without it. Each test lists what proves it and when to stop. Record results in `status.md`. Do the tests in order: each one relies on the earlier ones.

Stop rule: any surprise (an unexpected hash, a prompt that does not match, a port that does not return) ends the session. Do not improvise a flash.

**Setup (owner):** `scripts/owner/install-deps.sh --run` done, `bash build.sh --skip-bridge` succeeds, `./crush80 golden` passes, board on a direct USB port, nothing else with a serial port attached.

## T1. Read-only: the board is what we think

1. `./crush80 status`: slot 0 `confirmed active`, hash matches `./crush80 check releases/Crush80-No-RGB.bin` (note: `check` prints the image digest, `status` prints the same digest).
2. `./crush80 backup`. Expect ~3 minutes, a `flash.json` with a sha256. Run it twice; the two sha256 values should match (nothing changed).

Pass: both. Fail: a `status` timeout means fix connectivity first (cable, port, `mcumgr echo`), not the tool.

## T2. Trial boot and revert, with a harmless image

Proves the safety net on this hardware, before any experimental code is involved.

1. Build the current tree without RGB. It differs from the golden image (trial-boot behaviour), so the hash differs.
2. `./crush80 update dist/crush80-zmk-app.signed.bin`, replug when told.
3. Tool reports the new hash running. **Answer `n`** to the confirm question.
4. `./crush80 status`: slot 0 `active` and not `confirmed`.
5. Unplug 5 s, replug. `./crush80 status`: the **old golden hash is back** and confirmed.

Pass: step 5 shows the old hash. This is the property every later test depends on. Fail: stop and read `docs/features/install-mechanism.md`, "What is assumed".

## T3. Confirm persists

Repeat T2 but answer `y`. Unplug and replug. `status` still shows the new hash, confirmed. Slot 1 now holds the old image.

## T4. Recovery rehearsal

On a healthy board, with the golden image: `./crush80 recover`, following its prompts. It should end with the keyboard typing on the golden image. This proves the drill before it is ever needed, and
promotes `recover` over `scripts/legacy/` (then the legacy scripts can be deleted).

## T5. WDT behaviour (informational)

Not a pass/fail gate; it decides whether the watchdog counts as a safety layer or only the power-cycle revert does.
Build with `CONFIG_CRUSH80_MANUAL_CONFIRM=y` and a deliberate hang (e.g. `for(;;);` in a work handler behind a temporary Kconfig, never committed), trial-boot it, and **do not touch the board**: within about 11 s the watchdog should reset it.
Record whether the board came back on the old image by itself (WDT reset reaches MCUboot) or stayed dead until unplugged (it does not). Either result is fine; write it in `features/install-mechanism.md`.

## T6. RGB

Prerequisite: T2 and T3 pass. First read `features/rgb.md`, "Which board is this".

1. `bash build.sh --skip-bridge --rgb`, `./crush80 check dist/crush80-zmk-app-rgb.signed.bin`.
2. `./crush80 update dist/crush80-zmk-app-rgb.signed.bin`. It stays a trial until you say `y`.
3. While in trial, check in order (stop at the first failure; a failure means unplug/replug, not confirm):
   - keys still type on USB, with and without RGB on;
   - `./crush80 status` still answers while an effect is running (SMP alive);
   - Fn+Backspace toggles RGB; Fn+Backslash cycles effects; Fn+Up/Down changes brightness; keys, side bar and logo all light;
   - 5 minutes of typing with an effect running, no stalls, no stuck keys;
   - Bluetooth: pair a host, type, let it idle into sleep, wake it.
4. Only then confirm. If LEDs stay dark but everything else is healthy, do not confirm blindly: decide with the notes in `features/rgb.md`.

## T7. Stock switch (optional, last)

Only with an SWS probe on hand. `./crush80 stock-restore firmware.bin` (dry run, expect "Staged image verified byte for byte"), then `./crush80 backup`, then `--commit`, then `bash install_zmk.sh` to return.
Record the elapsed time between the commit and stock enumerating.
