# zmk/src/crush80_os.c

macOS / Windows selection. The keymap has one marker layer (Win). ZMK conditional layers turn Nav, ExtNav, Desk and DeskMove into their Windows copies while it is on. This file switches the marker layer from `&os_mac`, `&os_win`, `&os_tog` (behaviours in `zmk/src/rgb/c80_beh_os.c`, nodes in `crush80.dts`) and remembers the choice in settings (`c80os/win`, saved 3 s after a change, re-applied 2 s after boot).

Which layer is the marker comes from the keymap: `&c80os_cfg { win-layer = <WIN>; };` (255 = no OS switching, the default, so stock keymaps are unaffected).
It cannot be tested on a trial image beyond the switch itself: persistence needs a reboot, and a reboot reverts an unconfirmed trial (`features/install-mechanism.md`).
