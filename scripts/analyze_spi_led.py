#!/usr/bin/env python3
"""
Analyze Crush 80 firmware to determine LED driver type (WS2812 vs AW20216S)
and extract GPIO matrix pin assignments.
"""
import struct
from capstone import *

FW_PATH = "../firmware/v2_patched.bin"

with open(FW_PATH, 'rb') as f:
    fw = bytearray(f.read())

print("=== Firmware header ===")
print(f"  Size: {len(fw)} bytes")
print(f"  First 32 bytes: {fw[:32].hex()}")
print(f"  Marker at 0x20: {fw[0x20:0x24]}")
fw_size = struct.unpack_from('<I', fw, 0x18)[0]
print(f"  Firmware size field at 0x18: {fw_size}")

# Telink B91 loads firmware to ILM at 0x00000000
LOAD_ADDR = 0x00000000
md = Cs(CS_ARCH_RISCV, CS_MODE_RISCV32)
md.detail = True

# ---------------------------------------------------------------
# Identify SPI peripheral accesses
# ---------------------------------------------------------------
print()
print("=== SPI/LED peripheral register scan ===")

# Key peripheral addresses on Telink B91
PERIPH = {
    # PSPI (secondary SPI — shared with JTAG pins) — used for WS2812 on Rainy 75
    0x80140040: "PSPI_DATA0",
    0x80140044: "PSPI_DATA1",
    0x80140048: "PSPI_FIFO (WS2812 DMA write target)",
    0x8014004C: "PSPI_CTRL0",
    0x80140050: "PSPI_CTRL1",
    0x80140054: "PSPI_STATUS",
    # GSPI (general SPI) — could be used for AW20216S
    0x801401C0: "GSPI_DATA",
    0x801401C4: "GSPI_CTRL",
    0x801401CC: "GSPI_STATUS",
    # DMA channel 4 (used for PSPI on Rainy 75)
    0x80100200: "DMA_CH4_CTRL",
    0x80100204: "DMA_CH4_DST",
    0x80100208: "DMA_CH4_SRC",
    # I2C
    0x80140280: "I2C_CTRL",
    0x80140284: "I2C_DATA",
}

hits = {}
for off in range(0, len(fw)-4, 2):
    word = struct.unpack_from('<I', fw, off)[0]
    if (word & 0x7F) == 0x37:  # LUI opcode
        imm = ((word >> 12) & 0xFFFFF) << 12
        if imm == 0x80140000 or imm == 0x80100000:
            window_end = min(off + 128, len(fw))
            regs = {}
            for ins in md.disasm(bytes(fw[off:window_end]), LOAD_ADDR + off):
                mn, op = ins.mnemonic, ins.op_str
                if mn == 'lui':
                    p = [x.strip() for x in op.split(',')]
                    if len(p) == 2:
                        try:
                            regs[p[0]] = int(p[1], 0) << 12
                        except Exception:
                            pass
                if mn == 'addi':
                    p = [x.strip() for x in op.split(',')]
                    if len(p) == 3:
                        try:
                            v = int(p[2], 0)
                            if p[1] in regs:
                                regs[p[0]] = regs[p[1]] + v
                        except Exception:
                            pass
                if mn in ('sb', 'sh', 'sw', 'lb', 'lbu', 'lh', 'lhu', 'lw'):
                    clean = op.replace('(', ',').replace(')', '')
                    parts = [x.strip() for x in clean.split(',')]
                    if len(parts) >= 3:
                        try:
                            addr = regs.get(parts[2], 0) + int(parts[1], 0)
                            if addr in PERIPH:
                                key = addr
                                if key not in hits:
                                    hits[key] = []
                                hits[key].append(f"0x{off:05X}")
                        except Exception:
                            pass

if hits:
    for addr in sorted(hits.keys()):
        print(f"  0x{addr:08X}  {PERIPH[addr]:40s}  {len(hits[addr])} refs at: {hits[addr][:6]}")
else:
    print("  No SPI/DMA peripheral refs found via LUI pattern — trying broader scan")
    # Try scanning for SPI addresses stored as immediate li/mv patterns
    for off in range(0, len(fw) - 4, 4):
        word = struct.unpack_from('<I', fw, off)[0]
        for target in [0x80140048, 0x801401C0, 0x80100204]:
            if word == target or (word & 0xFFFFF000) == (target & 0xFFFFF000):
                print(f"  Raw word match 0x{word:08X} at offset 0x{off:05X}")

# ---------------------------------------------------------------
# Disassemble the LED init region — v1 was at 0xEF88 (768 bytes)
# v2 has +864 bytes total; LED init may have shifted.
# Scan for the function by looking at dense GPIO writes around 0xEF00-0xF500
# ---------------------------------------------------------------
print()
print("=== Disassembling GPIO-dense region around LED init (0xEF00-0xF500) ===")

region_start = 0xEF00
region_end   = 0xF600
code = bytes(fw[region_start:region_end])
regs = {}
gpio_ops = []

for ins in md.disasm(code, LOAD_ADDR + region_start):
    mn, op = ins.mnemonic, ins.op_str
    if mn == 'lui':
        p = [x.strip() for x in op.split(',')]
        if len(p) == 2:
            try:
                regs[p[0]] = int(p[1], 0) << 12
            except Exception:
                pass
    if mn == 'addi':
        p = [x.strip() for x in op.split(',')]
        if len(p) == 3:
            try:
                v = int(p[2], 0)
                if p[1] in regs:
                    regs[p[0]] = regs[p[1]] + v
            except Exception:
                pass
    if mn in ('sb', 'sh', 'sw', 'lb', 'lbu', 'lh', 'lhu', 'lw'):
        clean = op.replace('(', ',').replace(')', '')
        parts = [x.strip() for x in clean.split(',')]
        if len(parts) >= 3:
            try:
                addr = regs.get(parts[2], 0) + int(parts[1], 0)
                if 0x80140000 <= addr <= 0x80150000:
                    port = (addr & 0xFF)
                    if   0x80140100 <= addr < 0x80140110: reg_name = f"GPIO_OUT[{port-0x100}] port {chr(65+port-0x100)}"
                    elif 0x80140120 <= addr < 0x80140130: reg_name = f"GPIO_OE[{port-0x120}]  port {chr(65+port-0x120)}"
                    elif 0x80140140 <= addr < 0x80140150: reg_name = f"GPIO_IN[{port-0x140}]  port {chr(65+port-0x140)}"
                    elif 0x80140000 <= addr < 0x80140010: reg_name = f"GPIO_IE[{port}]  port {chr(65+port)}"
                    elif 0x80140160 <= addr < 0x80140170: reg_name = f"GPIO_PU[{port-0x160}]  port {chr(65+port-0x160)}"
                    elif 0x80140300 <= addr < 0x80140310: reg_name = f"GPIO_FEN[{port-0x300}] port {chr(65+port-0x300)}"
                    else: reg_name = f"GPIO?  0x{addr:08X}"
                    gpio_ops.append((ins.address, mn, op, reg_name))
                    print(f"  0x{ins.address:08x}: {mn:8s} {op:30s}  <- {reg_name}")
            except Exception:
                pass

if not gpio_ops:
    print("  (no GPIO ops in this region)")

# ---------------------------------------------------------------
# Matrix scan: disassemble 0x01300-0x01700 with full GPIO annotation
# ---------------------------------------------------------------
print()
print("=== Matrix scan region (0x01300-0x01700) with GPIO annotation ===")
regs = {}
for ins in md.disasm(bytes(fw[0x01300:0x01700]), LOAD_ADDR + 0x01300):
    mn, op = ins.mnemonic, ins.op_str
    if mn == 'lui':
        p = [x.strip() for x in op.split(',')]
        if len(p) == 2:
            try:
                regs[p[0]] = int(p[1], 0) << 12
            except Exception:
                pass
    if mn == 'addi':
        p = [x.strip() for x in op.split(',')]
        if len(p) == 3:
            try:
                v = int(p[2], 0)
                if p[1] in regs:
                    regs[p[0]] = regs[p[1]] + v
            except Exception:
                pass
    anno = ""
    if mn in ('sb', 'sh', 'sw', 'lb', 'lbu', 'lh', 'lhu', 'lw'):
        clean = op.replace('(', ',').replace(')', '')
        parts = [x.strip() for x in clean.split(',')]
        if len(parts) >= 3:
            try:
                addr = regs.get(parts[2], 0) + int(parts[1], 0)
                if 0x80140000 <= addr <= 0x80150000:
                    if   0x80140100 <= addr < 0x80140110: anno = f"GPIO_OUT port {chr(65+addr-0x80140100)}"
                    elif 0x80140120 <= addr < 0x80140130: anno = f"GPIO_OE  port {chr(65+addr-0x80140120)}"
                    elif 0x80140140 <= addr < 0x80140150: anno = f"GPIO_IN  port {chr(65+addr-0x80140140)}"
                    elif 0x80140200 <= addr < 0x80140210: anno = f"GPIO_IN2 port {chr(65+addr-0x80140200)}"
                    elif 0x80140000 <= addr < 0x80140010: anno = f"GPIO_IE  port {chr(65+addr-0x80140000)}"
                    elif 0x80140160 <= addr < 0x80140170: anno = f"GPIO_PU  port {chr(65+addr-0x80140160)}"
                    elif 0x80140300 <= addr < 0x80140310: anno = f"GPIO_FEN port {chr(65+addr-0x80140300)}"
                    else: anno = f"GPIO?  0x{addr:08X}"
            except Exception:
                pass
    suffix = f"  <- {anno}" if anno else ""
    print(f"  0x{ins.address:08x}: {mn:8s} {op}{suffix}")
