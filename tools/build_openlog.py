#!/usr/bin/env python3
"""
blockmove base + OPEN-PATH logger. Logs every open() path to a DDR ring buffer during the
(now non-crashing) project load, dumped to /OPENLOG.TXT on a CHANGE. See patch_openlog.s.

    python3 tools/build.py          # -> out/mainos.bin
    python3 tools/build_openlog.py  # -> out/mainos_openlog.bin
"""
import pathlib, subprocess, sys
from collections import Counter

BASE = 0x40000400
R11 = pathlib.Path("out/mainos.bin")
OUT = pathlib.Path("out/mainos_openlog.bin")

OLD_POOL, NEW_POOL = 0x40a955e0, 0x40af55e0
COUNT_AT, OLD_COUNT, NEW_COUNT = 0x40096f82, 0x390A, 0x38CA
BLK_LO, BLK_HI = 0x100b14f0, 0x100f7f30
BLK_DELTA = 0x40a955e0 - 0x100b14f0
CODE_END = 0x400e0000
BASE_LOADS = {"lea", "pea", "movea#", "move.l#", "move.l#abs", "jsr/jmp"}

BZ_CAVE = 0x400d72a0
BZ_DETOUR = 0x4001fa64
BZ_EXPECT = "41f910000000"

OL_CAVE = 0x400d7300
OL_DETOURS = [(0x4001b570, "open_hook", "4feffeb848d7041c"),   # universal FS open
              (0x40063e28, "dump_hook", "4aaf00046618")]


def off(a):
    return a - BASE


def opname(b0, b1):
    if b1 == 0xf9 and b0 in (0x41, 0x43, 0x45, 0x47, 0x49, 0x4b, 0x4d): return "lea"
    if (b0 << 8 | b1) == 0x4879: return "pea"
    if (b0 << 8 | b1) in (0x4eb9, 0x4ef9): return "jsr/jmp"
    if b1 == 0x7c and b0 in range(0x20, 0x2d, 2): return "movea#"
    if b1 == 0x3c and b0 in range(0x20, 0x2f, 2): return "move.l#"
    if (b0 << 8 | b1) == 0x23fc: return "move.l#abs"
    if b1 == 0xfc and b0 in (0xd1, 0xd3, 0xd5, 0xd7, 0xd9, 0xdb, 0xdd, 0xdf): return "adda#"
    if b1 == 0xfc and b0 in (0x91, 0x93, 0x95, 0x97, 0x99, 0x9b, 0x9d, 0x9f): return "suba#"
    if b1 == 0xfc and b0 in (0xb1, 0xb3, 0xb5, 0xb7, 0xb9, 0xbb, 0xbd, 0xbf): return "cmpa#"
    if b0 in (0x00, 0x02, 0x04, 0x06, 0x0a, 0x0c) and 0x80 <= b1 <= 0x87: return "immarith"
    return None


def inject(img, src, cave, detours):
    r = subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", "out/_p.o", src])
    if r.returncode:
        sys.exit("assembler failed")
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{cave:x}", "-o", "out/_p.elf", "out/_p.o"], capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/_p.elf", "out/_p.bin"], check=True)
    nm = subprocess.run(["m68k-elf-nm", "out/_p.elf"], capture_output=True, text=True).stdout
    sym = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    blob = pathlib.Path("out/_p.bin").read_bytes()
    end = cave + len(blob)
    print(f"  {src}: {len(blob)} B @ 0x{cave:08x}..0x{end-1:08x}")
    if end > 0x400d7c3c:
        sys.exit("blob overruns cave")
    if any(img[off(cave):off(end)]):
        sys.exit("cave not free")
    img[off(cave):off(end)] = blob
    for site, s, exp in detours:
        o = off(site)
        if bytes(img[o:o + len(exp) // 2]).hex() != exp:
            sys.exit(f"detour 0x{site:08x}: {bytes(img[o:o+len(exp)//2]).hex()} want {exp}")
        img[o:o + 6] = b"\x4e\xf9" + sym[s].to_bytes(4, "big")
        if len(exp) // 2 == 8:
            img[o + 6:o + 8] = b"\x4e\x71"
        print(f"    detour 0x{site:08x} -> {s} 0x{sym[s]:08x}")


def main():
    img = bytearray(R11.read_bytes())
    # step1 pool
    n = img.count(OLD_POOL.to_bytes(4, "big"))
    img = bytearray(img.replace(OLD_POOL.to_bytes(4, "big"), NEW_POOL.to_bytes(4, "big")))
    img[off(COUNT_AT):off(COUNT_AT) + 4] = NEW_COUNT.to_bytes(4, "big")
    # step2 block relocation (same as blockmove)
    N = len(img); reloc = Counter()
    for i in range(2, N - 3):
        v = (img[i] << 24) | (img[i + 1] << 16) | (img[i + 2] << 8) | img[i + 3]
        if BLK_LO <= v < BLK_HI and (BASE + i) < CODE_END and opname(img[i - 2], img[i - 1]):
            img[i:i + 4] = (v + BLK_DELTA).to_bytes(4, "big"); reloc[v] += 1
    for i in range(2, N - 3):
        v = (img[i] << 24) | (img[i + 1] << 16) | (img[i + 2] << 8) | img[i + 3]
        if v == BLK_HI and (BASE + i) < CODE_END:
            op = opname(img[i - 2], img[i - 1])
            if op and op not in BASE_LOADS:
                img[i:i + 4] = (v + BLK_DELTA).to_bytes(4, "big"); reloc[v] += 1
    print(f"block relocated: {sum(reloc.values())} refs")
    # boot-zero
    print("boot-zero:")
    inject(img, "tools/patch_bootzero.s", BZ_CAVE, [(BZ_DETOUR, "bootzero_stub", BZ_EXPECT)])
    # open logger
    print("open-logger:")
    inject(img, "tools/patch_openlog.s", OL_CAVE, OL_DETOURS)
    OUT.write_bytes(bytes(img))
    print(f"\n{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
