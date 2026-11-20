# Crush 80 ZMK — Coding & Documentation Etiquette

> **HARD RULE, above everything else: never download, fetch, install or load anything (package, dataset, model, code, firmware blob) that a platform
> has flagged, that cannot be verified, or that is not pinned and hash-checked in a script a person runs.** Agents never run `pip install`, `npm install`,
> `go install`, `brew install`, `git clone`, `west update`, `curl` or any other download. When something is needed, add it to `scripts/owner/install-deps.sh`
> (pinned, dry run by default), tell the owner what it is and why, keep working on what does not need it, and wait until the owner says it was run.
> Exception: the owner tells you in the current session to run a specific command; run exactly that. If a platform's status cannot be read, do not download.
> Every prompt to a subagent that may touch the network must repeat this rule and forbid downloading. Background: `.cursor/rules/no-flagged-downloads.mdc`.

This file is the source of truth for how code and docs are written in this repo, for humans and AI agents alike.
`.cursor/rules/coding-etiquette.mdc` points here.

## What this repo is

Custom ZMK firmware for the Wobkey Crush 80 keyboard (Telink B91 RISC-V) and the tooling that installs it. The failure that shaped the rules below: a firmware
bug hung the board, the safety net did not catch it, and the board was rescued only by hand-written Python scripts racing a two-second window. **The install and upgrade path must make
that impossible, or at least recoverable with the USB cable alone.** Read `docs/guides/install-and-upgrade.md` before touching anything that flashes.

## Start here each session

1. **This file.**
2. **`docs/status.md`**: what works now, what is unverified on hardware, open blockers.
3. **`docs/todo.md`**: next work, in order.
4. **`docs/glossary.md`** if a term is new (slot 0, trial boot, golden image, SWS...).
5. **`docs/decisions/`**: the file for the topic you are about to touch, read to the bottom.
6. If the task flashes, erases or reboots the board: **`docs/guides/install-and-upgrade.md`** and **`docs/guides/recovery.md`**.

## Hardware safety rules (flashing, drivers, boot path)

These exist because each one was paid for. Full reasoning: `docs/incidents/` and `docs/decisions/install-safety.md`.

1. **Never touch the bootloader** (flash 0x0-0xFFFF, MCUboot) in a routine upgrade. Only `install_zmk.sh` (first install) and `./crush80 stock-restore --commit`
   write there, and the second needs a fresh `./crush80 backup`.
2. **New images boot as a trial and are confirmed by the host, never by themselves** (`CONFIG_CRUSH80_MANUAL_CONFIRM=y`, the default). A power cycle before
   confirmation restores the previous image. Do not add self-confirming behaviour to an experimental build.
3. **A known-good image must be on disk and hash-verified** (`releases/MANIFEST.sha256`) before any flash or recovery. Add a line only after the image has run on
   the board and been confirmed.
4. **Flash through `./crush80`** (or `update.sh`, its wrapper). Do not hand-run `mcumgr image test` on an unvalidated file. `./crush80 check IMAGE` validates offline.
5. **No unbounded waits in firmware**: no `while (reg) {}` without a counter, never inside `irq_lock()`. Hold `irq_lock()` for microseconds, not milliseconds.
   Bit-banging that must shut interrupts for longer than that does not belong in this firmware.
6. **Never set `CONFIG_LOG_DEFAULT_LEVEL=4`** (floods the CDC port and stalls SMP). Keep `CONFIG_CONSOLE=y` (the SMP serial transport needs it).
7. **Never enable `&hspi`** in the DTS: PE0/PE1/PE2 are matrix columns.
8. **Do not flash an experimental image unless the user has said the board is connected and they are watching it.** Building is always fine.
9. A step you could not run on hardware is reported as unverified in `docs/status.md`, not as done.

## Documentation structure

Distinct places for distinct purposes. `docs/README.md` has the map.

- **`docs/features/<name>.md`**: one file per feature, describing its design **as it exists in the code today** (`rgb`, `install-mechanism`, `flash-layout`...).
- **`docs/guides/`**: how to do something (build, install and upgrade, recover, hardware test plan).
- **`docs/code/<mirror-of-source-path>.md`**: one file per source file, same relative path (`zmk/src/mcuboot_confirm.c` is documented at
  `docs/code/zmk/src/mcuboot_confirm.c.md`). The file-specific "why". Coverage is partial: files are added when touched.
- **`docs/decisions/<topic>.md`**: append-only dated log of settled calls. Newest at the bottom, never edit an entry. A reversal is a new entry.
- **`docs/incidents/`**: what went wrong, why it was possible, what changed. One dated file each.
- **`docs/history/`**: finished investigations and plans (the RGB bring-up record). Not current design.
- **`docs/reference/`**: third-party or captured material (udev rules, VIA json).
- Top level of `docs/`: `README.md`, `status.md`, `todo.md`, `glossary.md` only.

**Rule for agents:** before answering "why does this code do X", read its `docs/code/` mirror and the relevant feature doc. Do not guess from the code alone if a doc exists.
**Rule for agents:** write the explanation for code that needs more than one line into the `docs/code/` mirror in the **same change**, not as a follow-up.
**Doc drift:** a stale mirror you notice while doing something else is flagged to the user, not silently fixed, unless the fix is trivial and your change needs it.
`scripts/gate/check-doc-links.py` (part of the gate) fails on a `docs/...` path that does not exist.

## Comments in code

- Comments explain **why**, never what. Delete a comment that restates the next line.
- No multi-line comment block for a one-line fix. If it needs more than a line or two, it belongs in the `docs/code/` mirror.
- Comment only: non-obvious invariants, hardware quirks and workarounds (register, pin sharing, timing), and safety assumptions.

## Writing style (docs, comments, commit messages)

No AI-slop: no hedging ("it's worth noting"), no restating the obvious, no filler transitions, no narrating the process. Active voice, concrete nouns,
short sentences. State the fact. Write docs about the board in terms of what was **measured or read from the hardware**, and label anything inferred.

## Function and file size

- When a fix adds another special case to a function that already has several, extract before or alongside the fix. The trigger is "multiple unrelated concerns", not a line count.
- A file that has become a dumping ground is split by responsibility.

## Reuse (DRY, with a YAGNI guardrail)

- Before adding logic, check whether something similar exists; consolidate real duplication (the old recovery scripts each carried their own SMP client: that is why `scripts/crush80/smp.py` exists).
- Do not build abstractions for reuse that does not exist yet.

## Testing and the commit gate

- **Every host-side feature gets automated tests before it is done.** `scripts/tests/` (stdlib `unittest`, no installs).
- **Safety invariants get their own named tests**: "an unconfirmed running image blocks an update", "a corrupt image never reaches the board", "a reverted board is never confirmed".
  A refactor must not be able to break one silently.
- **Every commit is gated on `bash scripts/gate/verify.sh` being green**: tests, shell and Python syntax, doc links, known-good images, stale-reference greps. Run it immediately before the commit.
- **Firmware changes also need a build** (`bash build.sh --skip-bridge`, plus `--rgb` for RGB changes) and, for anything touching boot, USB, flash, watchdog or LEDs, a run through
  `docs/guides/hardware-test-plan.md`. A change that could not be built or run says so in `docs/status.md`.
- **Every command a script runs has a wall-clock timeout** (`subprocess.run(..., timeout=)`, `perl -e 'alarm shift; exec @ARGV' SECONDS cmd`). macOS has no `timeout`. A command that does not return is a failed step: record it,
  stop the flow, say what state the board is in. A new script that runs a command without a timeout is not finished.
- **Never name a source folder `build`, `config`, `secrets` or `.env`**: the machine's managed Claude Code policy denies reading those path segments. Build output directories are fine; they are not source.

## Commits / PRs

Small, atomic, reviewable. One logical change per commit. Stage by explicit path, never `git add -A` or `git add .`. Flash dumps in `backups/` are gitignored on purpose (they hold the board's
calibration and MAC); never commit them. Do not commit `dist/` or the BLE blob. Binaries committed to `releases/` need a `MANIFEST.sha256` line.
Commit only when the user asks.

## Decision log (`docs/decisions/`)

One file per topic. Add a dated entry when a real implementation decision is made (a mechanism, a tradeoff, a rejected option and why). Decisions already in a feature doc need no entry.

## Status snapshot (`docs/status.md`)

Update it whenever a task completes or a blocker changes. It answers "where are things right now"; `docs/todo.md` answers "what next".
