#!/usr/bin/env python3
"""Prove a firmware image cannot write the SH68F90's flash.

Every flash erase/program needs IB_CON1 (0xF2, the operation: 0xE6 erase / 0x6E
program) plus the unlock sequence IB_CON2..IB_CON5 = 05 0A 09 06 (smk flash.c, stock
0x6060/0x5EDB). 8051 SFRs can only be written by direct-address instructions, so if no
encoding that writes IB_CON1, IB_CON2 or IB_CON3 (0xF2-0xF4) appears at ANY byte offset
of the image, no code path (reachable, indirect, or a wild jump) can program or erase
flash. (IB_CON4/5 = 0xF5/0xF6 are not usable for the proof: 0xF5 is also the MOV dir,A
opcode, so it shows up at misaligned offsets everywhere.)

usage: check_no_flash_write.py image.hex
"""
import sys

FLASH_SFRS = {0xF2, 0xF3, 0xF4}  # IB_CON1 (operation), IB_CON2/3 (unlock)
# opcodes whose 2nd byte is a direct destination address
DIRECT_DST = {0x05, 0x15, 0x42, 0x43, 0x52, 0x53, 0x62, 0x63, 0x75, 0x86, 0x87,
              0xC5, 0xD0, 0xD5, 0xF5} | set(range(0x88, 0x90))


def load_hex(path):
    mem = {}
    for line in open(path):
        if line.startswith(":") and line[7:9] == "00":
            n, a = int(line[1:3], 16), int(line[3:7], 16)
            for i in range(n):
                mem[a + i] = int(line[9 + 2 * i:11 + 2 * i], 16)
    return mem


def main():
    mem = load_hex(sys.argv[1])
    hits = []
    for a, op in mem.items():
        b1, b2 = mem.get(a + 1), mem.get(a + 2)
        if op in DIRECT_DST and b1 in FLASH_SFRS:
            hits.append((a, op, b1))
        if op == 0x85 and b2 in FLASH_SFRS:  # MOV dir,dir: destination is the 3rd byte
            hits.append((a, op, b2))
    if hits:
        for a, op, sfr in hits:
            print(f"0x{a:04X}: opcode 0x{op:02X} writes SFR 0x{sfr:02X}")
        print(f"FAIL: {len(hits)} possible flash-register write(s)")
        return 1
    print(f"ok: no flash-register write encoding in {len(mem)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
