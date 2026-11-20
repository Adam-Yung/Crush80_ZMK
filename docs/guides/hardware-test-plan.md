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

## T8. Per-key backlight and OS layers (the 2026-11-20 build)

Image: the private build from the keybindings repo (`guides/keymap.md`). Keep your hands off the keyboard during the upload, and test **in order**; stop at the first failure (a failure means unplug and replug: an unconfirmed trial reverts).

1. Boot as a trial. Base: **no light at all**. Type normally for a minute. `./crush80 status` answers.
2. Hold **Caps** (Nav): side bar and logo blue, `i j k l` green, `e` orange, `r` amber, `u o` red, `z x c v` yellow, `g , .` magenta, only those and the modifiers lit. Release: all dark. If a colour appears on the **wrong key**, the LED map is off for that key: write down which, and stop (`code/zmk/src/rgb/engine.c.md`).
3. Hold **Space on top of Nav** (ExtNav): `i k` violet, `j l` azure, others as listed in `Keymap.md`. Hold **Tab** (Desk), the left **Shift** key or `'` (Sym), **Fn**: colours as in `Keymap.md`.
4. Hold **A** (Ctrl, home-row mod) for half a second: **only the A key** lights, red. Tap A: nothing lights. Same for S, D, F, J, K, L, `;`.
5. F5 / F6 change brightness while a layer is held; Pause and Fn+Backspace switch the backlight off and on (on Base, with Nav held, the side bar must follow).
6. **Fn+W**: Windows. Hold Caps: the side bar is a **paler** blue; `e` types Home, `z` Ctrl+Z. **Fn+M**: back to macOS. Do **not** reboot yet (a reboot reverts a trial).
7. Stop typing for ~60 s: the backlight goes off by itself; the next key brings it back.
8. Bad-day checks: tap Caps ten times quickly; hold Caps for 15 s; press F5 with Caps held (the trigger of the 2026-11-20 trial reset: `incidents/2026-11-20-trial-reverted-on-capslock-f5.md`). If USB drops, write down exactly what you did.
9. Only after all of that: confirm (`./crush80 confirm`). **Then** test what a trial cannot show: choose Windows, wait 5 s, unplug and replug: still Windows? Brightness remembered? Backlight on/off remembered on USB?
10. On battery (confirmed image): Bluetooth output has the backlight **off**; Fn+Backspace turns it on; deep sleep (5 min idle) and a wake by a key from every part of the board (the wake pins changed, `code/zmk/src/poweroff.c.md`).
Record each result in `status.md`.
