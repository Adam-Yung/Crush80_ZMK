# Keymap Reference

Crush80 ZMK firmware keymap — Home Row Mods with layers.

---

## Layer Triggers

| Key | Action |
|-----|--------|
| W (hold) | Nav layer |
| CapsLock (tap) | Escape |
| CapsLock (hold) | Sym layer |
| Apostrophe (hold) | Sym layer |
| Left of spacebar | Shift |
| Right of spacebar | Tab |
| Fn (right bottom) | Fn layer (hold) |
| ScrLk position | Toggle Native layer |
| Shift keys | Normal shift (unchanged) |

---

## Base Layer

Full Home Row Mods (CAGS order):

```
Left hand:   A=Ctrl  S=Alt  D=Gui  F=Shift
Right hand:  J=Shift K=Gui  L=Alt  ;=Ctrl
```

F-row sends media keys by default. Hold Fn for F1-F12 + BT/RGB controls.

Bottom row modifiers:
- Left of spacebar = Shift
- Right of spacebar = Tab
- CapsLock = Escape (tap) / Sym layer (hold)
- Apostrophe = Sym layer (hold) / plain apostrophe (tap)
- W = Nav layer (hold) / plain w (tap)

---

## Nav Layer (hold W)

Right-hand IJKL arrow cluster; left-hand editing shortcuts.

### Right hand (arrows + navigation)

```
┌───────┬───────┬───────┬───────┬───────┐
│       │ Bksp  │  ↑    │  Del  │       │
│   y   │   u   │   i   │   o   │   p   │
├───────┼───────┼───────┼───────┼───────┤
│       │  ←    │  ↓    │  →    │S-Enter│
│   h   │   j   │   k   │   l   │   ;   │
├───────┼───────┼───────┼───────┼───────┤
│       │       │SelLn  │SelWrd │       │
│   n   │   m   │   ,   │   .   │   /   │
└───────┴───────┴───────┴───────┴───────┘
```

### Left hand (editing + modifiers)

```
┌───────┬───────┬───────┬───────┬───────┬───────┐
│  Tab  │  Esc  │       │ Home  │  End  │ Shift │
│  tab  │   q   │   w   │   e   │   r   │   t   │
├───────┼───────┼───────┼───────┼───────┼───────┤
│       │ Shift │ Shift │       │       │CapsWd │
│ caps  │   a   │   s   │   d   │   f   │   g   │
├───────┼───────┼───────┼───────┼───────┼───────┤
│ Shift │ Undo  │  Cut  │ Copy  │ Paste │       │
│ lsft  │   z   │   x   │   c   │   v   │   b   │
└───────┴───────┴───────┴───────┴───────┴───────┘
```

### Key summary

| Key | Action |
|-----|--------|
| i | Up |
| j | Left |
| k | Down |
| l | Right |
| u | Backspace |
| o | Delete (forward) |
| , | Select Line |
| . | Select Word |
| ; | Shift+Enter |
| q | Escape |
| e | Home |
| r | End |
| t | Shift |
| a | Shift |
| s | Shift |
| g | Caps Word (auto-deactivates on space/punctuation) |
| z | Undo (Ctrl+Z) |
| x | Cut (Ctrl+X) |
| c | Copy (Ctrl+C) |
| v | Paste (Ctrl+V) |
| Space | Activate ExtNav sub-layer |

---

## ExtNav Layer (hold Space while in Nav)

Word-level movement and page navigation on the same positions.

| Key | Action |
|-----|--------|
| i | Page Up |
| j | Word Left (Ctrl+Left) |
| k | Page Down |
| l | Word Right (Ctrl+Right) |
| u | Word Backspace (Ctrl+Bspc) |
| o | Word Delete (Ctrl+Del) |
| , | Select Line |
| . | Select Word |
| ; | Enter (plain) |
| q | Escape |
| e | Home |
| r | End |
| t | Shift |
| a | Shift |
| s | Shift |
| z | Redo (Ctrl+Shift+Z) |
| x | Cut |
| c | Copy |
| v | Paste |

---

## Sym Layer (hold CapsLock or Apostrophe)

Numbers on the left hand, English punctuation and brackets on the right.

### Left hand: Numbers and Macros

```
┌───────┬───────┬───────┬───────┬───────┬───────┐
│ Space │   4   │   5   │   6   │  ->   │=> {}← │
│  tab  │   q   │   w   │   e   │   r   │   t   │
├───────┼───────┼───────┼───────┼───────┼───────┤
│       │   7   │   8   │   9   │   -   │   +   │
│ caps  │   a   │   s   │   d   │   f   │   g   │
├───────┼───────┼───────┼───────┼───────┼───────┤
│ Shift │ Undo  │   0   │   .   │   \   │   |   │
│ lsft  │   z   │   x   │   c   │   v   │   b   │
└───────┴───────┴───────┴───────┴───────┴───────┘
```

Number row: `1 2 3` remain as-is, followed by `$ % ^ & * ( )` shifted symbols.

### Right hand: Punctuation and Brackets

```
┌───────┬───────┬───────┬───────┬───────┐
│() =>  │   (   │   )   │   [   │   ]   │
│   y   │   u   │   i   │   o   │   p   │
├───────┼───────┼───────┼───────┼───────┤
│   =   │   ,   │   .   │   ?   │   '   │
│   h   │   j   │   k   │   l   │   ;   │
├───────┼───────┼───────┼───────┼───────┤
│   /   │       │       │       │       │
│   n   │   m   │       │       │       │
└───────┴───────┴───────┴───────┴───────┘
```

### Macros

| Key | Output | Use |
|-----|--------|-----|
| r | `->` | C-style pointer/return arrow |
| t | `=> {}` + cursor left | Lambda body (cursor inside braces) |
| y | `() =>` | Arrow function start |

### Special keys in Sym layer

- **Space** sends Shift (allows capitals without releasing the layer key)
- **;** sends Apostrophe (quick access without reaching)
- **'** sends Backspace (right pinky delete)

---

## Fn Layer (hold Fn)

F-row becomes actual F1-F12. Additional controls:

| Key | Action |
|-----|--------|
| F1-F3 (number row 1-3) | BT Profile 1/2/3 |
| 4 (number row) | USB output |
| 5 (number row) | BT/USB toggle |
| Backspace | RGB toggle |
| Ins | BT clear |
| \ | RGB effect cycle |
| Enter | RGB effect cycle |
| Up arrow | RGB brightness up |
| Down arrow | RGB brightness down |

---

## Native Layer (toggle ScrLk)

Full passthrough with no remapping. All keys send their standard keycodes. Press ScrLk position again to return to Base layer.

---

## Wireless Controls

| Combo | Action |
|-------|--------|
| Fn + 1 | BT Profile 1 |
| Fn + 2 | BT Profile 2 |
| Fn + 3 | BT Profile 3 |
| Fn + 4 | Force USB output |
| Fn + 5 | Toggle BT/USB |
| Fn + Ins | Clear current BT profile |
| Fn + Bspc | RGB on/off |

---

## Home Row Mod Parameters

| Parameter | Value |
|-----------|-------|
| Flavor | Balanced |
| Tapping term | 280ms |
| Quick-tap | 175ms |
| Require prior idle | 150ms |
| Bilateral filtering | Yes (hold-trigger-key-positions) |
