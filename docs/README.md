# Docs map

Where each kind of document lives. `AGENTS.md` at the repo root has the rules; this is the map.

**Start here** (each session, in this order): `AGENTS.md`, `status.md`, `todo.md`, `glossary.md` if a term is new, the file in `decisions/` for the topic.

## Top level

| File | What it is |
|---|---|
| `status.md` | What works, what is verified only on the host, blockers. Kept current. |
| `todo.md` | The next work, in order. |
| `glossary.md` | Terms, consistent across all docs. |

## Folders

| Folder | What is in it |
|---|---|
| `features/` | Current design of a whole feature: `install-mechanism`, `flash-layout`, `rgb`, `receiver`. |
| `guides/` | How to do something: `install-and-upgrade`, `keymap`, `recovery`, `build`, `hardware-test-plan`. |
| `code/` | One file per source file at the same relative path: the file-specific "why". Partial coverage. |
| `decisions/` | Append-only log: `install-safety`, `keymap-private`, `rgb`, `tooling`. |
| `incidents/` | What went wrong, why it was possible, what changed. One dated file each. |
| `history/` | Finished investigations and plans (the AW20216S RGB attempts, the Ghidra notes). Not current design. |
| `reference/` | Captured third-party material: udev rules, the stock VIA json and keymap backup. |

Which one holds a given piece of information: features describe the current shape, code docs one file's reasoning, decisions a settled call, status present reality, guides how to do it, history what is finished.

`scripts/gate/check-doc-links.py` (part of `scripts/gate/verify.sh`) fails when a `docs/...` path in a doc or source file does not exist.
