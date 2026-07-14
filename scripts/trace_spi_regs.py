#!/usr/bin/env python3
"""Decode compressed instructions after LUI s3 to find what s3 becomes."""
import struct

with open("../firmware/v2_patched.bin", "rb") as f:
    fw = bytearray(f.read())

ABI = {0:"zero",1:"ra",2:"sp",3:"gp",4:"tp",5:"t0",6:"t1",7:"t2",
       8:"s0",9:"s1",10:"a0",11:"a1",12:"a2",13:"a3",14:"a4",15:"a5",
       16:"a6",17:"a7",18:"s2",19:"s3",20:"s4",21:"s5",22:"s6",23:"s7",
       24:"s8",25:"s9",26:"s10",27:"s11",28:"t3",29:"t4",30:"t5",31:"t6"}

def decode_c(w):
    op = w & 3
    funct3 = (w >> 13) & 7
    rd_rs1 = (w >> 7) & 0x1F
    rs2_field = (w >> 2) & 0x1F

    if op == 1:
        if funct3 == 0:
            if rd_rs1 == 0:
                return "C.NOP", None, None, None
            imm5 = (w >> 12) & 1
            imm40 = (w >> 2) & 0x1F
            imm = (imm5 << 5) | imm40
            if imm >= 32:
                imm -= 64
            return "C.ADDI", rd_rs1, rd_rs1, imm
        elif funct3 == 2:
            imm5 = (w >> 12) & 1
            imm40 = (w >> 2) & 0x1F
            imm = (imm5 << 5) | imm40
            if imm >= 32:
                imm -= 64
            return "C.LI", rd_rs1, None, imm
        elif funct3 == 3:
            if rd_rs1 == 2:
                return "C.ADDI16SP", 2, 2, None
            imm17 = (w >> 12) & 1
            imm1612 = (w >> 2) & 0x1F
            imm = ((imm17 << 5) | imm1612) << 12
            return "C.LUI", rd_rs1, None, imm
        elif funct3 == 5:
            return "C.J", None, None, None
        elif funct3 == 6:
            return "C.BEQZ", None, None, None
        elif funct3 == 7:
            return "C.BNEZ", None, None, None
        else:
            rdc = 8 + ((w >> 7) & 7)
            return "C.ALU", rdc, rdc, None
    elif op == 2:
        if funct3 == 2:
            return "C.LWSP", rd_rs1, None, None
        elif funct3 == 4:
            f12 = (w >> 12) & 1
            if f12 == 0:
                if rs2_field == 0:
                    return "C.JR", None, None, None
                return "C.MV", rd_rs1, rs2_field, None
            else:
                if rs2_field == 0 and rd_rs1 == 0:
                    return "C.EBREAK", None, None, None
                if rs2_field == 0:
                    return "C.JALR", None, None, None
                return "C.ADD", rd_rs1, None, None
        elif funct3 == 6:
            return "C.SWSP", None, None, None
        else:
            return "C.C2", None, None, None
    elif op == 0:
        return "C.C0", None, None, None
    return "C.??", None, None, None


# Track all registers from LUI s3 at 0x0F66C through the SB instructions
regs = {}
regs[19] = 0x80140000  # s3=x19 from LUI s3, 0x80140 at 0x0F66C

print("=== Tracking registers 0x0F66C - 0x0F690 ===")
print(f"  0F66C: LUI s3, 0x80140  -> s3=0x80140000")

i = 0x0F670  # skip the LUI at 0x0F66C (4 bytes)
while i < 0x0F6A0:
    w2 = struct.unpack_from("<H", fw, i)[0]
    is4 = (w2 & 3) == 3
    if is4:
        word = struct.unpack_from("<I", fw, i)[0]
        op = word & 0x7F
        rd = (word >> 7) & 0x1F
        rs1 = (word >> 15) & 0x1F
        f3 = (word >> 12) & 7
        if op == 0x37:  # LUI
            imm = word >> 12
            regs[rd] = imm << 12
            print(f"  {i:05X}: LUI {ABI[rd]}, 0x{imm:X}  -> {ABI[rd]}=0x{imm<<12:08X}")
        elif op == 0x13 and f3 == 0:  # ADDI
            imm = word >> 20
            if imm >= 2048:
                imm -= 4096
            if rs1 in regs and regs[rs1] is not None:
                regs[rd] = regs[rs1] + imm
                print(f"  {i:05X}: ADDI {ABI[rd]}, {ABI[rs1]}, {imm}  -> {ABI[rd]}=0x{regs[rd]:08X}")
            else:
                print(f"  {i:05X}: ADDI {ABI[rd]}, {ABI[rs1]}, {imm}  (rs1 unknown)")
        elif op == 0x23 and f3 == 0:  # SB
            imm_lo = (word >> 7) & 0x1F
            imm_hi = (word >> 25) & 0x7F
            imm = (imm_hi << 5) | imm_lo
            if imm >= 2048:
                imm -= 4096
            base_val = regs.get(rs1)
            rs2 = (word >> 20) & 0x1F
            src_val = regs.get(rs2, "?")
            if base_val is not None:
                target = base_val + imm
                from_b = target - 0x80140000
                reg_id = "?"
                port = from_b & 0xF
                if 0x000 <= from_b < 0x010:
                    reg_id = f"GPIO_IE[P{chr(65+port)}]"
                elif 0x100 <= from_b < 0x110:
                    reg_id = f"GPIO_OUT[P{chr(65+port)}]"
                elif 0x120 <= from_b < 0x130:
                    reg_id = f"GPIO_OE[P{chr(65+port)}]"
                elif 0x300 <= from_b < 0x310:
                    reg_id = f"GPIO_FEN[P{chr(65+port)}]"
                print(f"  {i:05X}: SB {ABI[rs2]}={hex(src_val) if isinstance(src_val,int) else '?'}, {imm}({ABI[rs1]})  -> {reg_id}  (0x{target:08X})")
            else:
                print(f"  {i:05X}: SB {ABI[rs2]}, {imm}({ABI[rs1]})  (base unknown)")
        else:
            print(f"  {i:05X}: [4] 0x{word:08X}")
        i += 4
    else:
        mne, rd_op, rs1_op, imm_op = decode_c(w2)
        note = ""
        if mne == "C.ADDI" and rd_op is not None and rs1_op is not None and imm_op is not None:
            old = regs.get(rd_op)
            if old is not None:
                regs[rd_op] = old + imm_op
                note = f"  -> {ABI[rd_op]}=0x{regs[rd_op]:08X}"
        elif mne == "C.LI" and rd_op is not None and imm_op is not None:
            regs[rd_op] = imm_op
            note = f"  -> {ABI[rd_op]}={imm_op}"
        elif mne == "C.MV" and rd_op is not None and rs1_op is not None:
            regs[rd_op] = regs.get(rs1_op)
            note = f"  -> {ABI[rd_op]}={hex(regs[rd_op]) if regs[rd_op] is not None else '?'}"
        rd_name = ABI[rd_op] if rd_op is not None else ""
        print(f"  {i:05X}: {mne} {rd_name} (0x{w2:04X}){note}")
        i += 2

print()
print("=== Final register state ===")
for reg_n, val in sorted(regs.items()):
    if val is not None and 0x80140000 <= val <= 0x80150000:
        print(f"  x{reg_n:2d} ({ABI[reg_n]:5s}) = 0x{val:08X}  (GPIO+0x{val-0x80140000:03X})")
    elif val is not None:
        print(f"  x{reg_n:2d} ({ABI[reg_n]:5s}) = {hex(val) if isinstance(val,int) else val}")

print()
# Now decode the SB targets properly
s0_val = regs.get(8, 0x80140000)
s3_val = regs.get(19, 0x80140000)
print(f"s0 = 0x{s0_val:08X}")
print(f"s3 = 0x{s3_val:08X}")
print()
print("=== SB GPIO_FEN targets (AW20216S SPI peripheral pins) ===")
for off, base_n, base_val in [(778, 's3', s3_val), (779, 's0', s0_val)]:
    target = base_val + off
    from_b = target - 0x80140000
    port = from_b & 0xF
    reg_base = from_b & ~0xF
    if reg_base == 0x300:
        print(f"  SB {off}({base_n}): 0x{target:08X} = GPIO_FEN[P{chr(65+port)}] = port {chr(65+port)}")
    else:
        print(f"  SB {off}({base_n}): 0x{target:08X} = GPIO+0x{from_b:03X} (need Ghidra for exact)")
