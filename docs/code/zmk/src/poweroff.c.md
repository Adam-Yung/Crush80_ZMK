# zmk/src/poweroff.c

Deep sleep with key wake-up. Cuts LED power (PC2), detaches USB, sets 100 K pull-downs on the matrix **columns** and 1 M pull-ups on the **rows** through the analog registers (they survive deep sleep), arms the rows as wake sources, and enters DEEPSLEEP. Wake is a cold boot through MCUboot (so on an unconfirmed trial it ends the trial).

**2026-11-20 fix.** The pin lists were the Rainy 75's (rows PE0, PD2-6; columns PA0-4, PB1-6, PC1, PE4-7). This board's matrix (`crush80.dts`, `kscan0`) has rows PD7, PD2-6 and columns PE0-2, PE4-6, PB0-6, PC0, PC1, PC4. As written, row PD7 (the F-row, Esc and others) was never a wake source and several columns were never pulled low, so some keys could not wake the board. The lists now match the DTS, and the two analog-register waits are bounded (they were unbounded spins under `irq_lock`).
**Not tested on the board.** Test after confirming an image: let it deep-sleep on battery (5 min idle) and wake it with a key from every column and row group (Esc, F-row, number row, letters, right-hand keys, arrows). If a key does not wake it, unplug and replug.
