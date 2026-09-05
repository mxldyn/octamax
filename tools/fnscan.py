#!/usr/bin/env python3
"""fnscan.py -- for a function [start,end), list per-slot base-adds, call targets, and slot-count
   compares. Used to build the transitive closure of idx-dependent code for the 256-slot migration.
     python3 tools/fnscan.py 0x40099680 0x40099900
"""
import sys, pathlib
BASE = 0x40000400
# Default to the BUILT image, not stock. Reading stock while reasoning about the build produced three
# confident wrong conclusions in one session (a guard reads #128 in stock that the build already raised
# to #256, and an `addi` in stock is a `jsr <helper>` in the build). Same fix as tools/otdis.py.
import os
_root = pathlib.Path(__file__).resolve().parent.parent
img = pathlib.Path(os.environ.get("OTDIS_IMG", _root / "out" / "mainos_persist256.bin"))
if not img.exists():
    img = _root / "out" / "stock_mainos.bin"
IMG = pathlib.Path(img).read_bytes()
print(f"[fnscan] scanning {img}")

# known per-slot table bases (STATIC) + FLEX + slice + waveform
KNOWN = {0x100d5b30: "SET-A", 0x100b14f0: "FLEX-set", 0x46c90a78: "STATE-A",
         0x46c920a4: "S41", 0x46c93a24: "S42", 0x46aaa980: "WAVEBUF(0x3000)",
         0x46c922c4: "FLEX-STATE", 0x100d5c3e: "SETf", 0x100d5c59: "SETf2"}


def off(a): return a - BASE


def scan(lo, hi):
    o0, o1 = off(lo), off(hi)
    adds, calls, cmps = [], [], []
    k = o0
    while k < o1 - 1:
        va = BASE + k
        b0, b1 = IMG[k], IMG[k + 1]
        # addi.l #imm,dN : 06 8N
        if b0 == 0x06 and 0x80 <= b1 <= 0x87 and k + 6 <= o1:
            imm = int.from_bytes(IMG[k + 2:k + 6], "big")
            if 0x100b0000 <= imm <= 0x101fffff or 0x46000000 <= imm <= 0x46ffffff or 0x40a00000 <= imm <= 0x40afffff:
                adds.append((va, "addi", imm, "d%d" % (b1 & 7)))
            k += 6; continue
        # adda.l #imm,aN : dX FC  (X: 1,3,5,7,9,b,d,f -> a0..a7)
        if b1 == 0xFC and b0 in (0xd1, 0xd3, 0xd5, 0xd7, 0xd9, 0xdb, 0xdd, 0xdf) and k + 6 <= o1:
            imm = int.from_bytes(IMG[k + 2:k + 6], "big")
            an = {0xd1:1,0xd3:3,0xd5:5,0xd7:7,0xd9:9,0xdb:11,0xdd:13,0xdf:15}[b0]//2
            if 0x100b0000 <= imm <= 0x101fffff or 0x46000000 <= imm <= 0x46ffffff or 0x40a00000 <= imm <= 0x40afffff:
                adds.append((va, "adda", imm, "a%d" % an))
            k += 6; continue
        # jsr abs.l : 4e b9 ; jmp abs.l : 4e f9
        if b0 == 0x4e and b1 in (0xb9, 0xf9) and k + 6 <= o1:
            tgt = int.from_bytes(IMG[k + 2:k + 6], "big")
            calls.append((va, "jsr" if b1 == 0xb9 else "jmp", tgt))
            k += 6; continue
        # bsr.w : 61 00 dd dd
        if b0 == 0x61 and b1 == 0x00 and k + 4 <= o1:
            disp = int.from_bytes(IMG[k + 2:k + 4], "big", signed=True)
            calls.append((va, "bsrw", va + 2 + disp)); k += 4; continue
        # cmpi.l #imm,dN : 0c 8N .... (slot-count compares)
        if b0 == 0x0c and 0x80 <= b1 <= 0x87 and k + 6 <= o1:
            imm = int.from_bytes(IMG[k + 2:k + 6], "big")
            if imm in (0x80, 0x87, 0x100, 0xff):
                cmps.append((va, imm, "d%d" % (b1 & 7)))
            k += 6; continue
        k += 2
    return adds, calls, cmps


if __name__ == "__main__":
    lo = int(sys.argv[1], 16); hi = int(sys.argv[2], 16)
    a, c, m = scan(lo, hi)
    print(f"== [{lo:#x},{hi:#x}) ==")
    print("-- per-slot base-adds --")
    for va, kind, imm, reg in a:
        tag = KNOWN.get(imm, "??")
        print(f"  {va:#010x} {kind} #{imm:#010x},{reg}   [{tag}]")
    if not a: print("  (none)")
    print("-- slot-count compares --")
    for va, imm, reg in m:
        print(f"  {va:#010x} cmpi #{imm},{reg}")
    if not m: print("  (none)")
    print("-- calls --")
    for row in c:
        print("  " + " ".join(f"{x:#x}" if isinstance(x, int) else str(x) for x in row))
