# 2026-11-20: the host tool dropped every reply from the board

**What happened:** the first hardware run of `./crush80 backup` failed with `no response to group 64 cmd 2 within 5.0s`, on two different firmware images. Even a plain `echo` through the Python SMP client got no reply, while Go `mcumgr` talking to the same port worked.
**Cause:** Zephyr's SMP encoder answers with an indefinite-length CBOR map (`bf ... ff`). `scripts/crush80/cbor.py` supported only definite lengths, raised, and `FrameParser` swallowed the error and dropped the frame. So every reply was silently ignored. Found by capturing the raw bytes the board sent.
**Why it was possible:** the 29 unit tests used fake boards whose replies were encoded by our own encoder, so they never saw the real format. Nothing had talked to hardware.
**What changed:** the decoder handles indefinite arrays and maps (`c5b7d06`), with a test that uses a reply captured from the board (`scripts/tests/test_cbor_indefinite.py`). `./crush80 backup` then worked (1,040,384 bytes). `recover` and `stock-restore` use the same client and were affected the same way; they are still unproven end to end (hardware test plan T3, T7).
**Rule going forward:** protocol tests must include bytes captured from the real device, not only our own encoder's output.
