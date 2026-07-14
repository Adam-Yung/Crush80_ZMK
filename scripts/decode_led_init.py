#!/usr/bin/env python3
"""Decode raw instructions around LED init GPIO_FEN writes to find SPI pins."""
import struct

with open("../firmware/v2_patched.bin", "rb") as f:
    fw = bytearray(f.read())

ABI = {0:"zero",1:"ra",2:"sp",3:"gp",4:"tp",5:"t0",6:"t1",7:"t2",
       8:"s0",9:"s1",10:"a0",11:"a1",12:"a2",13:"a3",14:"a4",15:"a5",
       16:"a6",17:"a7",18:"s2",19:"s3",20:"s4",21:"s5",22:"s6",23:"s7",
       24:"s8",25:"s9",26:"s10",27:"s11",28:"t3",29:"t4",30:"t5",31:"t6"}

GPIO_BASE = 0x80140000
GPIO_MAP = {
    0x000:"IE", 0x100:"OUT", 0x120:"OE", 0x140:"IN",
    0x160:"PU", 0x300:"FEN"
}
PORTS = {0:"PA",1:"PB",2:"PC",3:"PD",4:"PE"}

def gpio_desc(abs_addr):
    off = abs_addr - GPIO_BASE
    base = off & ~0xF
    port = off & 0xF
    reg = GPIO_MAP.get(base, f"REG+0x{base:03X}")
    pname = PORTS.get(port, f"P{port}")
    return f"GPIO_{reg}[{pname}]"

def decode(start, end):
    regs = {}
    for i in range(start, end, 2):
        if i + 3 >= len(fw):
            break
        w2 = struct.unpack_from("<H", fw, i)[0]
        is4 = (w2 & 3) == 3
        if is4:
            if i + 3 >= len(fw):
                break
            word = struct.unpack_from("<I", fw, i)[0]
            op = word & 0x7F
            rd  = (word >> 7) & 0x1F
            rs1 = (word >> 15) & 0x1F
            rs2 = (word >> 20) & 0x1F
            f3  = (word >> 12) & 7

            if op == 0x37:  # LUI
                imm = word >> 12
                regs[rd] = imm << 12
                note = f"   <- GPIO base" if (imm << 12) == GPIO_BASE else ""
                print(f"  {i:05X}: LUI {ABI[rd]}, 0x{imm:X}{note}")

            elif op == 0x13 and f3 == 0:  # ADDI
                imm = word >> 20
                if imm >= 2048: imm -= 4096
                val = (regs.get(rs1) or 0) + imm if rs1 in regs else None
                regs[rd] = val
                note = ""
                if val and 0x80140000 <= val <= 0x80150000:
                    note = f"   <- {gpio_desc(val)}"
                print(f"  {i:05X}: ADDI {ABI[rd]}, {ABI[rs1]}, {imm}{note}")

            elif op == 0x23 and f3 == 0:  # SB
                imm_lo = (word >> 7) & 0x1F
                imm_hi = (word >> 25) & 0x7F
                imm = (imm_hi << 5) | imm_lo
                if imm >= 2048: imm -= 4096
                base_val = regs.get(rs1)
                note = ""
                if base_val is not None:
                    target = base_val + imm
                    if 0x80140000 <= target <= 0x80150000:
                        note = f"   <- WRITE {gpio_desc(target)}"
                src_val = regs.get(rs2, "?")
                print(f"  {i:05X}: SB {ABI[rs2]}(={hex(src_val) if isinstance(src_val,int) else '?'}), {imm}({ABI[rs1]}){note}")

            elif op == 0x03 and f3 == 4:  # LBU
                imm = word >> 20
                if imm >= 2048: imm -= 4096
                base_val = regs.get(rs1)
                note = ""
                if base_val is not None:
                    target = base_val + imm
                    if 0x80140000 <= target <= 0x80150000:
                        note = f"   <- READ {gpio_desc(target)}"
                print(f"  {i:05X}: LBU {ABI[rd]}, {imm}({ABI[rs1]}){note}")

            elif op == 0x13 and f3 == 6:  # ORI
                imm = word >> 20
                if imm >= 2048: imm -= 4096
                old = regs.get(rs1)
                regs[rd] = (old | imm) if old is not None else None
                print(f"  {i:05X}: ORI {ABI[rd]}, {ABI[rs1]}, 0x{imm & 0xFFF:X}   (pin mask=0b{imm & 0xFF:08b})")

            elif op == 0x13 and f3 == 7:  # ANDI
                imm = word >> 20
                if imm >= 2048: imm -= 4096
                old = regs.get(rs1)
                regs[rd] = (old & imm) if old is not None else None
                print(f"  {i:05X}: ANDI {ABI[rd]}, {ABI[rs1]}, 0x{imm & 0xFFF:X}   (mask=0b{imm & 0xFF:08b})")

            elif op == 0x6F:  # JAL
                print(f"  {i:05X}: JAL/J")
            elif op == 0x67:  # JALR
                print(f"  {i:05X}: JALR/RET")
            else:
                print(f"  {i:05X}: [op=0x{op:02X}]  0x{word:08X}")
            i += 2  # will add 2 more below for total of 4
        else:
            print(f"  {i:05X}: [C] 0x{w2:04X}")

        i += 2


print("="*70)
print("LED init cluster 0x0F4D8 - 0x0F780 (top GPIO cluster)")
print("="*70)
decode(0x0F4D8, 0x0F780)
