# Tooling

## 2026-11-19: one host tool, standard library only

`./crush80` (`scripts/crush80/`) replaces five scripts that each carried their own SMP client and their own port detection. It uses no pip package so it works on a fresh machine and in recovery
(pyserial and cbor2 are not installed here, and agents do not install). `mcumgr` stays for image upload, test and confirm, where it is proven; the Python SMP client covers only the custom `flash_mgmt` group.

## 2026-11-19: adopt the prisma-encryptor repo conventions, minus what does not apply

Adopted: `AGENTS.md` as source of truth with a hard no-download rule, docs split into features, guides, code mirrors, decisions, incidents and history, a status snapshot and a todo, a pre-commit gate,
timeouts on every command, explicit-path staging. Not adopted: Rust and Swift lint, VM test requirements, the Git LFS rules, `safe_fetch.py` and `approved-sources.json` (this repo downloads only through owner-run scripts: `setup.sh`,
`fetch_ble_blob.sh`, `scripts/owner/install-deps.sh`; there is nothing for an agent to fetch).
