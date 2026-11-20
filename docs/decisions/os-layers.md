# Decision: macOS and Windows from one keymap

## 2026-11-20
**Decision:** the keymap carries both OSes as duplicated layers, like the Cornix keyboard, switched by Fn+W (Windows) and Fn+M (macOS). A marker layer (Win) plus ZMK conditional layers swap Nav, ExtNav, Desk and DeskMove for full 86-binding Windows copies; Base, Sym, Fn and Native are shared. The choice is saved to flash (`crush80_os.c`); Cornix does not persist it.
**Why full copies:** ExtNav sits above Nav, so a sparse Windows Nav could not stop macOS ExtNav bindings showing through. Cost: 13 layers x 86 bindings.
**Windows content** follows `kanata-windows.kbd` exactly (Ctrl shortcuts, Home/End, Ctrl word jumps; Desk without Mission Control; the Win key adds Shift for DeskMove). The text snippet on ExtNav+1 is on both OSes (Kanata has it on macOS only).
**Rejected:** Cornix-style duplicated Base with `&to` (more layers, no persistence); a custom per-key "OS-aware" behaviour (not visible in ZMK Studio, and the backlight classifier would need to understand it).
**Owner's decisions (same day):** full copies; two set-keys, not a toggle; Windows Desk matches Kanata; RGB off on Bluetooth but toggleable with Fn+Backspace; held home-row mod lights its key on Base; colour groups plus sparse overrides; effects dropped; no key-press highlight; deep sleep stays at 5 min until measured; the one-colour module is deleted once the engine is proven.
**Known limit:** with Kanata running on Windows, the board's own remapping doubles it (Kanata cannot exclude the Crush 80 there): stop Kanata or use Native.
