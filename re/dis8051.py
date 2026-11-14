#!/usr/bin/env python3
"""Recursive-descent 8051 disassembler with SH68F90 SFR names.

usage: dis8051.py <firmware.bin|.hex> [--sfr-header sh68f90.h] [--entry 0xADDR ...] > out.asm

Code is only decoded where control flow reaches it (from the reset and interrupt
vectors plus any --entry), so data tables are not mistaken for code. Indirect jumps
(JMP @A+DPTR) cannot be followed; add their targets with --entry.
"""
import argparse
import re
import sys
from pathlib import Path

# (mnemonic, length, operand format). Operand codes:
#  A acc, Rn reg n, @Ri, d direct, b bit, #8 imm8, #16 imm16, r rel8, a11 addr11, a16 addr16,
#  /b inverted bit, DPTR, C, @A+DPTR, @A+PC, @DPTR, AB
OPS = {}


def op(code, mnem, *args):
    size = 1
    for a in args:
        size += {"d": 1, "b": 1, "/b": 1, "#8": 1, "r": 1, "a11": 1, "#16": 2, "a16": 2}.get(a, 0)
    OPS[code] = (mnem, size, args)


# ajmp / acall: aaa00001 / aaa10001
for hi in range(8):
    op((hi << 5) | 0x01, "AJMP", "a11")
    op((hi << 5) | 0x11, "ACALL", "a11")

simple = {
    0x00: ("NOP",), 0x02: ("LJMP", "a16"), 0x03: ("RR", "A"), 0x04: ("INC", "A"), 0x05: ("INC", "d"),
    0x10: ("JBC", "b", "r"), 0x12: ("LCALL", "a16"), 0x13: ("RRC", "A"), 0x14: ("DEC", "A"),
    0x15: ("DEC", "d"), 0x20: ("JB", "b", "r"), 0x22: ("RET",), 0x23: ("RL", "A"),
    0x24: ("ADD", "A", "#8"), 0x25: ("ADD", "A", "d"), 0x30: ("JNB", "b", "r"), 0x32: ("RETI",),
    0x33: ("RLC", "A"), 0x34: ("ADDC", "A", "#8"), 0x35: ("ADDC", "A", "d"), 0x40: ("JC", "r"),
    0x42: ("ORL", "d", "A"), 0x43: ("ORL", "d", "#8"), 0x44: ("ORL", "A", "#8"), 0x45: ("ORL", "A", "d"),
    0x50: ("JNC", "r"), 0x52: ("ANL", "d", "A"), 0x53: ("ANL", "d", "#8"), 0x54: ("ANL", "A", "#8"),
    0x55: ("ANL", "A", "d"), 0x60: ("JZ", "r"), 0x62: ("XRL", "d", "A"), 0x63: ("XRL", "d", "#8"),
    0x64: ("XRL", "A", "#8"), 0x65: ("XRL", "A", "d"), 0x70: ("JNZ", "r"), 0x72: ("ORL", "C", "b"),
    0x73: ("JMP", "@A+DPTR"), 0x74: ("MOV", "A", "#8"), 0x75: ("MOV", "d", "#8"), 0x80: ("SJMP", "r"),
    0x82: ("ANL", "C", "b"), 0x83: ("MOVC", "A", "@A+PC"), 0x84: ("DIV", "AB"), 0x85: ("MOV", "d", "d"),
    0x90: ("MOV", "DPTR", "#16"), 0x92: ("MOV", "b", "C"), 0x93: ("MOVC", "A", "@A+DPTR"),
    0x94: ("SUBB", "A", "#8"), 0x95: ("SUBB", "A", "d"), 0xA0: ("ORL", "C", "/b"), 0xA2: ("MOV", "C", "b"),
    0xA3: ("INC", "DPTR"), 0xA4: ("MUL", "AB"), 0xA5: ("DB 0xA5",), 0xB0: ("ANL", "C", "/b"),
    0xB2: ("CPL", "b"), 0xB3: ("CPL", "C"), 0xB4: ("CJNE", "A", "#8", "r"), 0xB5: ("CJNE", "A", "d", "r"),
    0xC0: ("PUSH", "d"), 0xC2: ("CLR", "b"), 0xC3: ("CLR", "C"), 0xC4: ("SWAP", "A"), 0xC5: ("XCH", "A", "d"),
    0xD0: ("POP", "d"), 0xD2: ("SETB", "b"), 0xD3: ("SETB", "C"), 0xD4: ("DA", "A"),
    0xD5: ("DJNZ", "d", "r"), 0xE0: ("MOVX", "A", "@DPTR"), 0xE4: ("CLR", "A"), 0xE5: ("MOV", "A", "d"),
    0xF0: ("MOVX", "@DPTR", "A"), 0xF4: ("CPL", "A"), 0xF5: ("MOV", "d", "A"),
}
for k, v in simple.items():
    op(k, v[0], *v[1:])

# register-indexed families: (base for @R0, base+1 @R1, base+2.. R0..R7)
fam = {
    0x06: ("INC", ()), 0x16: ("DEC", ()), 0x26: ("ADD", ("A",)), 0x36: ("ADDC", ("A",)),
    0x46: ("ORL", ("A",)), 0x56: ("ANL", ("A",)), 0x66: ("XRL", ("A",)), 0x76: ("MOV", None),
    0x86: ("MOV", "d<-"), 0x96: ("SUBB", ("A",)), 0xA6: ("MOV", "<-d"), 0xB6: ("CJNE", "cj"),
    0xC6: ("XCH", ("A",)), 0xD6: ("XCHD", ("A",)), 0xE6: ("MOV", ("A",)), 0xF6: ("MOV", "->"),
}
for base, (mn, pre) in fam.items():
    for j in range(10):
        code = base + j
        if base == 0xD6 and j >= 2:
            # 0xD8-0xDF is DJNZ Rn, rel
            op(code, "DJNZ", f"R{j-2}", "r")
            continue
        reg = f"@R{j}" if j < 2 else f"R{j-2}"
        if pre is None:          # 0x76..: MOV reg,#imm
            op(code, "MOV", reg, "#8")
        elif pre == "d<-":       # 0x86..: MOV direct, reg
            op(code, "MOV", "d", reg)
        elif pre == "<-d":       # 0xA6..: MOV reg, direct
            op(code, "MOV", reg, "d")
        elif pre == "cj":        # 0xB6..: CJNE reg,#imm,rel
            op(code, "CJNE", reg, "#8", "r")
        elif pre == "->":        # 0xF6..: MOV reg, A
            op(code, "MOV", reg, "A")
        else:
            op(code, mn, *pre, reg)
# MOVX @Ri
op(0xE2, "MOVX", "A", "@R0"); op(0xE3, "MOVX", "A", "@R1")
op(0xF2, "MOVX", "@R0", "A"); op(0xF3, "MOVX", "@R1", "A")
# XCH/XCHD fixups: 0xC6..0xCF XCH A,reg ; 0xD6/0xD7 XCHD A,@Ri
op(0xD6, "XCHD", "A", "@R0"); op(0xD7, "XCHD", "A", "@R1")

STD_IRAM_BITS = {}


def load_image(path):
    data = bytearray(b"\xff" * 0x10000)
    if path.endswith(".hex") or path.endswith(".ihx"):
        for line in open(path):
            line = line.strip()
            if not line.startswith(":"):
                continue
            n, addr, t = int(line[1:3], 16), int(line[3:7], 16), int(line[7:9], 16)
            if t == 0:
                data[addr:addr + n] = bytes.fromhex(line[9:9 + 2 * n])
    else:
        raw = open(path, "rb").read()
        data[:len(raw)] = raw
    return data


def load_sfrs(header):
    sfr, sbit = {}, {}
    if header and Path(header).exists():
        for m in re.finditer(r"SFR\((\w+),\s*(0x[0-9a-fA-F]+)\)", Path(header).read_text()):
            sfr.setdefault(int(m.group(2), 16), m.group(1))
        for m in re.finditer(r"SBIT\((\w+),\s*(0x[0-9a-fA-F]+),\s*(\d+)\)", Path(header).read_text()):
            sbit.setdefault(int(m.group(2), 16) + int(m.group(3)), m.group(1))
    return sfr, sbit


class Dis:
    def __init__(self, mem, sfr, sbit):
        self.mem, self.sfr, self.sbit = mem, sfr, sbit
        self.insn = {}          # addr -> (text, size, mnem, targets)
        self.labels = set()
        self.calls = set()
        self.indirect = []

    def direct(self, d):
        if d >= 0x80:
            return self.sfr.get(d, f"SFR_{d:02X}")
        return f"0x{d:02X}"

    def bit(self, b):
        if b in self.sbit:
            return self.sbit[b]
        if b >= 0x80:
            return f"{self.direct(b & 0xF8)}.{b & 7}"
        return f"0x{0x20 + (b >> 3):02X}.{b & 7}"

    def decode(self, pc):
        m = self.mem
        code = m[pc]
        mnem, size, args = OPS.get(code, (f"DB 0x{code:02X}", 1, ()))
        ops, targets = [], []
        p = pc + 1
        for a in args:
            if a == "d":
                ops.append(self.direct(m[p])); p += 1
            elif a == "b":
                ops.append(self.bit(m[p])); p += 1
            elif a == "/b":
                ops.append("/" + self.bit(m[p])); p += 1
            elif a == "#8":
                ops.append(f"#0x{m[p]:02X}"); p += 1
            elif a == "#16":
                ops.append(f"#0x{(m[p] << 8) | m[p+1]:04X}"); p += 2
            elif a == "r":
                rel = m[p] - 256 if m[p] > 127 else m[p]; p += 1
                t = (pc + size + rel) & 0xFFFF
                ops.append(f"L_{t:04X}"); targets.append(t)
            elif a == "a11":
                t = ((pc + size) & 0xF800) | ((code >> 5) << 8) | m[p]; p += 1
                ops.append(f"L_{t:04X}"); targets.append(t)
            elif a == "a16":
                t = (m[p] << 8) | m[p+1]; p += 2
                ops.append(f"L_{t:04X}"); targets.append(t)
            else:
                ops.append(a)
        # MOV d,d encodes src first
        if code == 0x85:
            ops = [ops[1], ops[0]]
        return mnem, size, ops, targets

    def run(self, entries):
        work = list(entries)
        while work:
            pc = work.pop()
            while pc not in self.insn and pc < 0x10000:
                mnem, size, ops, targets = self.decode(pc)
                text = f"{mnem:<6} {', '.join(ops)}".rstrip()
                self.insn[pc] = (text, size, mnem, targets)
                for t in targets:
                    self.labels.add(t)
                    work.append(t)
                if mnem in ("LCALL", "ACALL"):
                    self.calls.update(targets)
                if mnem in ("LJMP", "AJMP", "SJMP", "RET", "RETI") or mnem.startswith("DB"):
                    break
                if mnem == "JMP":
                    self.indirect.append(pc)
                    work.extend(self.jump_table(pc))
                    break
                pc += size

    def jump_table(self, pc):
        """SDCC/Keil switch: MOV DPTR,#T; MOV R0,A; ADD A,R0; ADD A,R0; JMP @A+DPTR
        with T a run of LJMPs. Bound it by the CJNE A,#n just before, if present."""
        m = self.mem
        if m[pc-6] != 0x90 or bytes(m[pc-3:pc]) != b"\xF8\x28\x28":
            return []
        base = (m[pc-5] << 8) | m[pc-4]
        limit = 64
        for back in range(pc - 6, max(pc - 24, 0), -1):     # look for CJNE A,#n,rel
            if m[back] == 0xB4:
                limit = m[back+1]
                break
        out = []
        for k in range(limit):
            a = base + 3 * k
            if m[a] != 0x02:
                break
            self.insn.setdefault(a, (f"LJMP   L_{(m[a+1] << 8) | m[a+2]:04X}   ; case {k}", 3, "LJMP", []))
            t = (m[a+1] << 8) | m[a+2]
            self.labels.add(t)
            out.append(t)
        return out

    def dump(self, out):
        prev_end = None
        for pc in sorted(self.insn):
            text, size, mnem, _ = self.insn[pc]
            if prev_end is not None and pc != prev_end:
                out.write(f"\n; ---- gap 0x{prev_end:04X}-0x{pc-1:04X} (data or unreached) ----\n")
            if pc in self.labels:
                kind = "FUNC" if pc in self.calls else "L"
                out.write(f"\n{kind}_{pc:04X}:\n" if kind == "FUNC" else f"L_{pc:04X}:\n")
            raw = " ".join(f"{b:02X}" for b in self.mem[pc:pc+size])
            out.write(f"  {pc:04X}: {raw:<9} {text}\n")
            prev_end = pc + size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--sfr-header")
    ap.add_argument("--entry", action="append", default=[])
    ap.add_argument("--vectors", type=int, default=16, help="number of interrupt vectors at 0x03+8n")
    args = ap.parse_args()
    mem = load_image(args.image)
    sfr, sbit = load_sfrs(args.sfr_header)
    d = Dis(mem, sfr, sbit)
    # only follow vector slots that hold a jump; on this firmware some slots contain code
    vecs = [v for v in (3 + 8 * i for i in range(args.vectors)) if mem[v] in (0x02, 0x01, 0x21, 0x41, 0x61, 0x81, 0xA1, 0xC1, 0xE1)]
    entries = [0] + vecs + [int(e, 0) for e in args.entry]
    d.run(entries)
    d.dump(sys.stdout)
    sys.stderr.write(f"decoded {len(d.insn)} instructions, {len(d.calls)} functions, "
                     f"indirect jumps at: {', '.join(f'0x{p:04X}' for p in d.indirect) or 'none'}\n")


if __name__ == "__main__":
    main()
