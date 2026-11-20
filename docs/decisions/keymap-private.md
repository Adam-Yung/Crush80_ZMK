# Decision: the personal keymap lives in a private repository

## 2026-11-20
**Decision:** `keymaps/personal.keymap` and the tracked `zmk/boards/crush80/crush80.keymap` were removed from this public repo. The keymap, its `app.conf` and the build workflow that uses them live in the private repo `Adam-Yung/keybindings`.
This repo builds only the generic `keymaps/stock.keymap`. The gate fails if another `.keymap` is tracked.

**Why:** a keymap carries text macros (a password-like string was committed to this public repo in 08b88d1 and stays in history), and the compiled firmware contains them too, so a public CI artifact would leak it as well.
Building in the private repo keeps both the source and the artifact private. The firmware is pinned by commit SHA in the private workflow, so a public push cannot change what gets flashed.

**Consequences:** the earlier password string is still readable in this repo's git history (not rewritten); change the password if it was real. The Telink BLE blob is linked into the images, which is also why artifacts are never published as releases.
**Rejected:** a GitHub secret holding the keymap (the build would still upload a public artifact); making this repo private (the firmware is meant to be shared).
