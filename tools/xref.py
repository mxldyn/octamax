#!/usr/bin/env python3
"""xref.py -- find references to an address/immediate, function bounds, and idx-table accesses.
Usage:
  python3 tools/xref.py xref 0x40016564          # find jsr/jmp/bsr/lea/immediate refs to VA
  python3 tools/xref.py imm  0x46c90a78          # find 32-bit immediate anywhere
  python3 tools/xref.py bounds 0x4000c8a4        # scan forward to next rts/rte after link, and back to nearest link
  python3 tools/xref.py word 0x46c8657e          # find any 32-bit word equal to value (data ptrs)
"""
import sys, pathlib
BASE = 0x40000400
IMG = (pathlib.Path(__file__).resolve().parent.parent / "out" / "stock_mainos.bin").read_bytes()
N = len(IMG)

def va(o): return BASE + o
def off(a): return a - BASE

def find_imm(val):
    hits = []
    b = val.to_bytes(4, "big")
    start = 0
    while True:
        i = IMG.find(b, start)
        if i < 0: break
        hits.append(i)
        start = i + 1
    return hits

def xref(target):
    # scan for jsr/jmp abs.l (4eb9/4ef9), PC-relative jsr/jmp/bsr/bra, and any 32-bit imm == target
    res = []
    tb = target.to_bytes(4, "big")
    k = 0
    while k < N - 5:
        b0, b1 = IMG[k], IMG[k+1]
        if b0 == 0x4e and b1 in (0xb9, 0xf9):
            t = int.from_bytes(IMG[k+2:k+6], "big")
            if t == target:
                res.append((va(k), "jsr" if b1==0xb9 else "jmp", t)); k += 6; continue
        if b0 == 0x61 and b1 == 0x00:
            disp = int.from_bytes(IMG[k+2:k+4], "big", signed=True)
            if va(k)+2+disp == target:
                res.append((va(k), "bsrw", target)); k += 4; continue
        # PC-RELATIVE forms. These encode the target as a displacement, so the callee address never
        # appears as a 32-bit immediate -- an absolute-only scan reports "no callers" for a function
        # that is in fact called. (Cost us a wrong conclusion on the 0x40027e4c dispatcher.)
        if b0 == 0x4e and b1 in (0xba, 0xfa):          # jsr/jmp %pc@(d16)
            disp = int.from_bytes(IMG[k+2:k+4], "big", signed=True)
            if va(k)+2+disp == target:
                res.append((va(k), "jsr pc@" if b1==0xba else "jmp pc@", target)); k += 4; continue
        if b0 == 0x60 and b1 == 0x00:                  # bra.w
            disp = int.from_bytes(IMG[k+2:k+4], "big", signed=True)
            if va(k)+2+disp == target:
                res.append((va(k), "braw", target)); k += 4; continue
        if b0 in (0x60, 0x61) and b1 not in (0x00, 0xff):   # bra.b / bsr.b (8-bit displacement)
            disp = int.from_bytes(IMG[k+1:k+2], "big", signed=True)
            if va(k)+2+disp == target:
                res.append((va(k), "brab" if b0==0x60 else "bsrb", target)); k += 2; continue
        k += 1
    # also raw immediate occurrences
    for i in find_imm(target):
        res.append((va(i), "imm32@", target))
    res.sort()
    return res

def bounds(addr):
    o = off(addr)
    # back: find nearest 'lea sp@(-n),sp' (4fef ....) or link (4e5x) scanning back up to 0x400
    back = None
    for j in range(o, max(0, o-0x600), -2):
        if IMG[j]==0x4f and IMG[j+1]==0xef:
            back = va(j); break
        if IMG[j]==0x4e and (IMG[j+1] & 0xf8)==0x50:  # link
            back = va(j); break
    # forward: find rts (4e75) / rte (4e73) / jmp
    fwd = None
    for j in range(o, min(N-1, o+0x1200), 2):
        if IMG[j]==0x4e and IMG[j+1] in (0x75, 0x73):
            fwd = va(j); break
    return back, fwd

if __name__ == "__main__":
    cmd = sys.argv[1]; arg = int(sys.argv[2], 16)
    if cmd == "xref":
        for r in xref(arg):
            print(f"  {r[0]:#010x} {r[1]} {r[2]:#x}")
    elif cmd in ("imm","word"):
        for i in find_imm(arg):
            print(f"  {va(i):#010x}")
    elif cmd == "bounds":
        b,f = bounds(arg)
        print(f"  start~{b:#x} end(rts)~{f:#x}" if b and f else f"  {b} {f}")
