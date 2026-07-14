#!/usr/bin/env python3
"""
Extract AW20216S SPI GPIO pins from Crush 80 firmware binary.

Uses raw RV32I instruction pattern matching — no Capstone, no Ghidra,
no Andes V5 support needed. Only scans 4-byte standard RV32I instructions
which decode identically regardless of Andes extensions.

Method:
1. Find all LUI instructions loading 0x80140 (GPIO base) in LED init region
2. Decode the SB (store byte) instructions that follow them
3. Map SB offset → GPIO register → port + pin
4. Pattern-match: CS pin = driven HIGH and LOW around each SPI transaction
"""

import struct
import sys
import os

FW_PATH = os.path.join(os.path.dirname(__file__), "../firmware/v2_patched.bin")

with open(FW_PATH, "rb") as f:
    fw = bytearray(f.read())

print(f"Firmware: {len(fw)} bytes")

# ── RV32I instruction decoders ──────────────────────────────────────────────

ABI_NAMES = {
    0: "x0/zero", 1: "ra", 2: "sp", 3: "gp", 4: "tp",
    5: "t0", 6: "t1", 7: "t2", 8: "s0/fp", 9: "s1",
    10: "a0", 11: "a1", 12: "a2", 13: "a3", 14: "a4", 15: "a5",
    16: "a6", 17: "a7", 18: "s2", 19: "s3", 20: "s4", 21: "s5",
    22: "s6", 23: "s7", 24: "s8", 25: "s9", 26: "s10", 27: "s11",
    28: "t3", 29: "t4", 30: "t5", 31: "t6",
}
PORT_NAMES = {0: "PA", 1: "PB", 2: "PC", 3: "PD", 4: "PE"}

GPIO_BASE  = 0x80140000
GPIO_REGS  = {
    0x000: "GPIO_IE",   # input enable
    0x100: "GPIO_OUT",  # output value
    0x120: "GPIO_OE",   # output enable (0=output)
    0x140: "GPIO_IN",   # input read
    0x160: "GPIO_PU",   # pull-up/down
    0x300: "GPIO_FEN",  # function enable
}

def gpio_reg_name(addr):
    offset = addr - GPIO_BASE
    base_reg = offset & ~0x0F      # round down to nearest 0x10
    port_idx = offset & 0x0F
    port = PORT_NAMES.get(port_idx, f"P?({port_idx})")
    reg_name = GPIO_REGS.get(base_reg, f"GPIO?+0x{base_reg:03X}")
    return f"{reg_name}[{port}]", port, port_idx

def decode_lui(word):
    """Decode LUI: [31:12]=imm, [11:7]=rd, [6:0]=0x37"""
    if (word & 0x7F) != 0x37:
        return None
    rd  = (word >> 7) & 0x1F
    imm = (word >> 12) & 0xFFFFF
    return rd, imm << 12

def decode_addi(word):
    """Decode ADDI: [31:20]=imm12, [19:15]=rs1, [14:12]=000, [11:7]=rd, [6:0]=0x13"""
    if (word & 0x7F) != 0x13:
        return None
    if ((word >> 12) & 0x7) != 0:
        return None
    rd  = (word >> 7) & 0x1F
    rs1 = (word >> 15) & 0x1F
    imm = word >> 20
    if imm >= 2048:
        imm -= 4096      # sign-extend 12-bit
    return rd, rs1, imm

def decode_sb(word):
    """Decode SB: func7|rs2|rs1|000|imm_lo|0x23"""
    if (word & 0x7F) != 0x23:
        return None
    if ((word >> 12) & 0x7) != 0:  # func3 must be 0 for SB
        return None
    rs2     = (word >> 20) & 0x1F
    rs1     = (word >> 15) & 0x1F
    imm_lo  = (word >> 7) & 0x1F
    imm_hi  = (word >> 25) & 0x7F
    offset  = (imm_hi << 5) | imm_lo
    if offset >= 2048:
        offset -= 4096
    return rs1, rs2, offset

def decode_lbu(word):
    """Decode LBU: [31:20]=imm, [19:15]=rs1, [14:12]=100, [11:7]=rd, [6:0]=0x03"""
    if (word & 0x7F) != 0x03:
        return None
    if ((word >> 12) & 0x7) != 4:  # func3=4 for LBU
        return None
    rd  = (word >> 7) & 0x1F
    rs1 = (word >> 15) & 0x1F
    imm = word >> 20
    if imm >= 2048:
        imm -= 4096
    return rd, rs1, imm

def decode_ori(word):
    """Decode ORI: [31:20]=imm12, [19:15]=rs1, [14:12]=110, [11:7]=rd, [6:0]=0x13"""
    if (word & 0x7F) != 0x13:
        return None
    if ((word >> 12) & 0x7) != 6:
        return None
    rd  = (word >> 7) & 0x1F
    rs1 = (word >> 15) & 0x1F
    imm = word >> 20
    if imm >= 2048:
        imm -= 4096
    return rd, rs1, imm

def decode_andi(word):
    """Decode ANDI: [31:20]=imm12, [19:15]=rs1, [14:12]=111, [11:7]=rd, [6:0]=0x13"""
    if (word & 0x7F) != 0x13:
        return None
    if ((word >> 12) & 0x7) != 7:
        return None
    rd  = (word >> 7) & 0x1F
    rs1 = (word >> 15) & 0x1F
    imm = word >> 20
    if imm >= 2048:
        imm -= 4096
    return rd, rs1, imm

# ── Scan for LED init GPIO accesses ─────────────────────────────────────────

def scan_region(start, end, label):
    print(f"\n{'='*72}")
    print(f"Region: {label}  (0x{start:05X} – 0x{end:05X})")
    print(f"{'='*72}")

    # Simulate registers: maps reg_number → current known value (None if unknown)
    regs = {}
    gpio_accesses = []

    for off in range(start, end - 3, 2):
        if off + 3 >= len(fw):
            break
        word = struct.unpack_from("<I", fw, off)[0]

        # Only process 4-byte (non-compressed) instructions
        if (word & 0x3) != 3:
            continue    # compressed instruction, skip

        addr = off  # load address (firmware runs from ILM at 0x00000000)

        # Track LUI
        r = decode_lui(word)
        if r:
            rd, val = r
            regs[rd] = val
            if 0x80140000 <= val <= 0x80150000:
                print(f"  0x{addr:05x}  LUI {ABI_NAMES[rd]}, 0x{val>>12:05X}   "
                      f"← GPIO base")
            continue

        # Track ADDI (often used to compute exact GPIO address)
        r = decode_addi(word)
        if r:
            rd, rs1, imm = r
            if rs1 in regs and regs[rs1] is not None:
                regs[rd] = regs[rs1] + imm
                computed = regs[rd]
                if 0x80140000 <= computed <= 0x80150000:
                    reg_nm, port, _ = gpio_reg_name(computed)
                    print(f"  0x{addr:05x}  ADDI {ABI_NAMES[rd]}, {ABI_NAMES[rs1]}, {imm}"
                          f"  → 0x{computed:08X}  {reg_nm}")
            continue

        # Detect SB (store byte to GPIO)
        r = decode_sb(word)
        if r:
            rs1, rs2, offset = r
            if rs1 in regs and regs[rs1] is not None:
                target = regs[rs1] + offset
                if 0x80140000 <= target <= 0x80150000:
                    reg_nm, port, port_idx = gpio_reg_name(target)
                    src_name = ABI_NAMES.get(rs2, f"x{rs2}")
                    gpio_accesses.append((addr, "W", target, reg_nm, port, port_idx, src_name))
                    print(f"  0x{addr:05x}  SB {src_name}, {offset}({ABI_NAMES[rs1]})"
                          f"  → WRITE {reg_nm}")
            continue

        # Detect LBU (read byte from GPIO)
        r = decode_lbu(word)
        if r:
            rd, rs1, imm = r
            if rs1 in regs and regs[rs1] is not None:
                target = regs[rs1] + imm
                if 0x80140000 <= target <= 0x80150000:
                    reg_nm, port, port_idx = gpio_reg_name(target)
                    gpio_accesses.append((addr, "R", target, reg_nm, port, port_idx, ABI_NAMES[rd]))
                    print(f"  0x{addr:05x}  LBU {ABI_NAMES[rd]}, {imm}({ABI_NAMES[rs1]})"
                          f"  → READ  {reg_nm}")
            continue

        # Track ORI (bitmask operations on GPIO values — tell us which pins)
        r = decode_ori(word)
        if r:
            rd, rs1, imm = r
            if rs1 in regs and regs[rs1] is not None:
                regs[rd] = regs[rs1] | imm
            elif imm != 0:
                # Standalone OR with known immediate — pin mask candidate
                pass
            continue

        # Track ANDI
        r = decode_andi(word)
        if r:
            rd, rs1, imm = r
            if rs1 in regs and regs[rs1] is not None:
                regs[rd] = regs[rs1] & imm
            continue

    return gpio_accesses

# ── Find the LED init function ───────────────────────────────────────────────

print("\n=== Step 1: Finding LUI 0x80140 clusters (LED init candidates) ===")

# Search entire firmware for LUI x?, 0x80140
# Any register target (not just a5/x15)
lui_hits = []
for off in range(0, len(fw) - 3, 4):
    word = struct.unpack_from("<I", fw, off)[0]
    r = decode_lui(word)
    if r:
        _, val = r
        if val == 0x80140000:
            lui_hits.append(off)

print(f"Total LUI 0x80140 hits: {len(lui_hits)}")

# Find dense clusters (potential LED init / matrix init)
if lui_hits:
    clusters = []
    i = 0
    while i < len(lui_hits):
        cluster_start = lui_hits[i]
        cluster_hits = [lui_hits[i]]
        j = i + 1
        while j < len(lui_hits) and lui_hits[j] - cluster_hits[-1] <= 64:
            cluster_hits.append(lui_hits[j])
            j += 1
        if len(cluster_hits) >= 3:
            clusters.append((cluster_start, lui_hits[j-1] if j > i+1 else cluster_start + 4,
                             len(cluster_hits)))
        i = j if j > i + 1 else i + 1

    clusters.sort(key=lambda x: -x[2])
    print(f"\nTop 10 GPIO-dense clusters (potential init functions):")
    for s, e, cnt in clusters[:10]:
        print(f"  0x{s:05X}–0x{e:05X}  ({cnt} GPIO base loads, {e-s} bytes span)")

# ── Detailed analysis of top clusters ───────────────────────────────────────

print("\n=== Step 2: Detailed GPIO access analysis of top clusters ===")

all_accesses = []
if clusters:
    for s, e, cnt in clusters[:5]:
        region_start = max(0, s - 32)
        region_end   = min(len(fw), e + 256)
        accesses = scan_region(region_start, region_end,
                               f"cluster at 0x{s:05X} ({cnt} GPIO loads)")
        all_accesses.extend(accesses)

# ── Summary: identify SPI pins ───────────────────────────────────────────────

print("\n" + "="*72)
print("SUMMARY: GPIO_OE writes (pins configured as OUTPUT = likely SPI/CS pins)")
print("="*72)

oe_writes = [(addr, tgt, rnm, port, pidx, src)
             for (addr, rw, tgt, rnm, port, pidx, src) in all_accesses
             if rw == "W" and "GPIO_OE" in rnm]

if oe_writes:
    for addr, tgt, rnm, port, pidx, src in oe_writes:
        print(f"  0x{addr:05x}  {rnm}  val_reg={src}")
else:
    print("  (none found — try wider region or check firmware offset)")

print()
print("GPIO_OUT writes (pins driven HIGH/LOW = likely CS or data pins):")
out_writes = [(addr, tgt, rnm, port, pidx, src)
              for (addr, rw, tgt, rnm, port, pidx, src) in all_accesses
              if rw == "W" and "GPIO_OUT" in rnm]
for addr, tgt, rnm, port, pidx, src in out_writes:
    print(f"  0x{addr:05x}  {rnm}  val_reg={src}")

print()
print("GPIO_FEN writes (pin function mode = GPIO vs peripheral SPI):")
fen_writes = [(addr, tgt, rnm, port, pidx, src)
              for (addr, rw, tgt, rnm, port, pidx, src) in all_accesses
              if rw == "W" and "GPIO_FEN" in rnm]
for addr, tgt, rnm, port, pidx, src in fen_writes:
    print(f"  0x{addr:05x}  {rnm}  val_reg={src}")
