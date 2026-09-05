#!/usr/bin/env python3
"""
enum_fn.py — for each candidate function, map its exact byte range and every per-slot access it
makes, so the dual-256 migration can open its clamp AND redirect EVERY per-slot add (a missed one
= OOB write into the OS working region at runtime -> project corruption). Prints, per function:
  - the function extent (entry .. first top-level rts),
  - each static clamp `cmpi.l #128,dN` (candidate to open),
  - each per-slot base-add: SETTINGS 0x100d5b30(+fld) / STATE 0x46c90a78 / STRIDE4 0x46c920a4 /
    0x46c93a24, with its register + helper name, so it can be pasted into build_dual256.CORE.

    python3 tools/enum_fn.py 0x4006da78 0x4009367c ...
"""
import sys, subprocess, re, pathlib

BASE = 0x40000400
IMG = pathlib.Path("out/stock_mainos.bin").read_bytes()

TABLES = {  # base -> (helper-prefix, exact-immediate-set incl folded, stride)
    0x100d5b30: ("h_set", "SETTINGS"),
    0x100d5c3e: ("h_setf", "SETTINGS+0x10e"),
    0x100d5c59: ("h_set?", "SETTINGS+0x129(lea)"),
    0x46c90a78: ("h_st", "STATE"),
    0x46c920a4: ("h_s41", "STRIDE4#1"),
    0x46c93a24: ("h_s42", "STRIDE4#2"),
}
REG_OF = {0x00:"d0",0x02:"d1",0x04:"d2",0x06:"d3",0x08:"d4",0x0a:"d5",0x0c:"d6",0x0e:"d7"}
AREG = {0xd1:"a0",0xd3:"a1",0xd5:"a2",0xd7:"a3",0xd9:"a4",0xdb:"a5",0xdd:"a6",0xdf:"a7"}


def dis(a, b):
    out = subprocess.run(["m68k-elf-objdump","-D","-b","binary","-m","m68k:68040",
        "--adjust-vma=0x40000400",f"--start-address=0x{a:x}",f"--stop-address=0x{b:x}",
        "out/stock_mainos.bin"], capture_output=True, text=True).stdout.splitlines()
    return [l for l in out if re.match(r"^4[0-9a-f]{7}:", l)]


def fn_end(entry):
    """first top-level rts (4e75) at/after entry — good enough for these leaf-ish accessors."""
    a = entry
    while a < entry + 0x1200:
        for l in dis(a, a + 0x200):
            va = int(l.split(":")[0], 16)
            txt = l.split("\t")[-1].strip()
            if txt == "rts":
                return va + 2
        a += 0x200
    return entry + 0x1200


def enum(entry):
    end = fn_end(entry)
    print(f"\n=== fn 0x{entry:08x} .. 0x{end:08x} ({end-entry} B) ===")
    o0, o1 = entry - BASE, end - BASE
    # clamps: cmpi.l #128,dN  (0c 8N 00000080)
    clamps = []
    for k in range(o0, o1 - 5):
        if IMG[k] == 0x0c and 0x80 <= IMG[k+1] <= 0x87 and int.from_bytes(IMG[k+2:k+6],"big") == 128:
            clamps.append(BASE + k)
    for c in clamps:
        print(f"  clamp  0x{c:08x}  cmpi.l #128,d{IMG[c-BASE+1]&7}")
    # per-slot base-adds (muls-scaled add of a table immediate)
    sites = []
    for k in range(o0 + 2, o1 - 3):
        v = int.from_bytes(IMG[k:k+4], "big")
        if v not in TABLES:
            continue
        b0, b1 = IMG[k-2], IMG[k-1]
        reg = op = None
        if b0 == 0x06 and 0x80 <= b1 <= 0x87:      # addi.l #v,dN
            reg = REG_OF[(b1 & 7) << 1]; op = "addi"
        elif b1 == 0xfc and b0 in AREG:            # adda.l #v,aN
            reg = AREG[b0]; op = "adda"
        else:
            continue                                # cmpa/lea/move = bound/walk, skip
        pfx, name = TABLES[v]
        helper = f"{pfx}_{reg}"
        sites.append((BASE + k, v, reg, helper, name))
        print(f"  SITE   0x{BASE+k:08x}  {op} #{name} ,{reg}   -> {helper}")
    if not sites:
        print("  (no per-slot base-adds)")
    return entry, end, clamps, sites


def main():
    for arg in sys.argv[1:]:
        enum(int(arg, 16))


if __name__ == "__main__":
    main()
