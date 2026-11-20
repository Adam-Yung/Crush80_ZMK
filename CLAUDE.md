# Crush 80 ZMK: instructions for Claude Code

Read `AGENTS.md` first. Its first block is a hard rule that overrides everything else: **agents never download or install anything**; dependencies go into
`scripts/owner/install-deps.sh` for the owner to audit and run. Its "Hardware safety rules" section governs every flash, erase and reboot of the board:
new images boot as a trial and are confirmed by the host, a hash-verified known-good image must be on disk, and flashing goes through `./crush80`.

Session start: `AGENTS.md`, `docs/status.md`, `docs/todo.md`. Before any commit: `bash scripts/gate/verify.sh` must be green.
