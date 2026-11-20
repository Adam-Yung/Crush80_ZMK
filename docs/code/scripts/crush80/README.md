# scripts/crush80

Host tool behind `./crush80`. Standard library only. Design: `docs/features/install-mechanism.md`. Tests: `scripts/tests/`.

| Module | Why it is its own file |
|---|---|
| `cbor.py` | the SMP payload subset, so no `cbor2` install; bool handled before the length decode because `0xf4`-`0xf6` look like short ints |
| `smp.py` | serial framing and the `flash_mgmt` client; `FrameParser` tolerates console log text in the stream and frames split across reads, because the firmware's UART console shares the port |
| `mcuimg.py` | offline image validation; refuses anything without the MCUboot magic, a matching SHA-256 TLV and room for the swap trailer |
| `mcumgr.py` | wrapper over the CLI with a wall-clock limit on every call; parses both `flags:` and `confirmed:` list formats |
| `device.py` | port discovery; `wait_for_port(gone_first=True)` requires the port to vanish first so a stale port from before the unplug is never taken for the reboot |
| `serialport.py` | termios serial; raises DTR because the firmware ignores a port nobody has opened |
| `flows.py` | the procedures. Every failure message names the board's state and the next action |
| `cli.py` | argument parsing and exit codes only |

Invariants with named tests (`scripts/tests/test_flows.py`): an unconfirmed running image blocks an update; a corrupt image never reaches the board; a reverted board is never confirmed;
a missing or altered golden image blocks every flash; confirmation happens only after the user says yes; stock commit needs a backup.

**`cbor.py`:** minimal CBOR for SMP. Decodes indefinite-length arrays and maps (Zephyr's SMP encoder emits them); before 2026-11-20 it did not and dropped every board reply (`incidents/2026-11-20-smp-cbor-indefinite.md`).
