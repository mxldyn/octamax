#!/usr/bin/env python3
"""
Move the ENTIRE contiguous flex+static settings block [0x100b14f0, 0x100f7f30) to DDR
(0x40a955e0) as one unit + boot-zero. 264 slots x 0x448 = 0x46A40 (283 KB), fits the 384 KB
reserved window.

  Why the whole block: flex settings (0x100b14f0, 136 slots) and static settings
  (0x100d5b30, 128 slots) are physically contiguous and some loops iterate them AS ONE
  array (e.g. a4=0x100b14f0 walked +0x448 until cmpa #0x100f7f30). Relocating static alone
  breaks every such combined loop (start in SRAM flex, bound in DDR -> runaway hang right
  after LOADING). Moving the whole block by one delta preserves every internal offset, so
  flex-only, static-only AND combined loops all stay consistent.

  Relocate every operand ref whose value is in [0x100b14f0, 0x100f7f30), EXCEPT base-load
  pointers (pea/lea/movea/move.l#) to exactly 0x100f7f30 -- that address doubles as the
  base of a global struct ABOVE the block, which does NOT move. (cmpa/cmpi #0x100f7f30 are
  loop END bounds and DO relocate.) The bottom (0x100b14f0) has no bound-refs, so no lower
  neighbour to preserve.

    python3 tools/build.py           # -> out/mainos.bin (R11)
    python3 tools/build_blockmove.py # -> out/mainos_blockmove.bin
"""
import pathlib, subprocess, sys
from collections import Counter

BASE = 0x40000400
R11 = pathlib.Path("out/mainos.bin")
OUT = pathlib.Path("out/mainos_blockmove.bin")

OLD_POOL, NEW_POOL = 0x40a955e0, 0x40af55e0
COUNT_AT, OLD_COUNT, NEW_COUNT = 0x40096f82, 0x390A, 0x38CA

BLK_LO = 0x100b14f0                 # flex base = block bottom
BLK_HI = 0x100f7f30                 # static end = block top (exclusive) == global base above
BLK_DELTA = 0x40a955e0 - 0x100b14f0 # 0x309c40f0
CODE_END = 0x400e0000
BASE_LOADS = {"lea", "pea", "movea#", "move.l#", "move.l#abs", "jsr/jmp"}

CAVE_AT = 0x400d72a0
DETOUR_AT = 0x4001fa64
DETOUR_EXPECT = "41f910000000"


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


def main():
    if not R11.exists():
        sys.exit(f"missing {R11} — run tools/build.py first")
    img = bytearray(R11.read_bytes())
    print(f"block [0x{BLK_LO:08x}, 0x{BLK_HI:08x}) size 0x{BLK_HI-BLK_LO:x} -> DDR 0x{BLK_LO+BLK_DELTA:08x}..0x{BLK_HI+BLK_DELTA-1:08x}")
    if BLK_HI + BLK_DELTA > NEW_POOL:
        sys.exit("block overruns the reserved window")

    # step 1: pool
    n = img.count(OLD_POOL.to_bytes(4, "big"))
    if not (18 <= n <= 30):
        sys.exit(f"pool-base count {n} unexpected")
    img = bytearray(img.replace(OLD_POOL.to_bytes(4, "big"), NEW_POOL.to_bytes(4, "big")))
    o = off(COUNT_AT)
    if int.from_bytes(img[o:o + 4], "big") != OLD_COUNT:
        sys.exit("count mismatch")
    img[o:o + 4] = NEW_COUNT.to_bytes(4, "big")
    print(f"step 1: pool moved ({n} refs)")

    # step 2: relocate the whole block; keep only base-loads to the top global (0x100f7f30)
    reloc = Counter(); skip = []
    N = len(img)
    for i in range(2, N - 3):
        v = (img[i] << 24) | (img[i + 1] << 16) | (img[i + 2] << 8) | img[i + 3]
        if not (BLK_LO <= v < BLK_HI and (BASE + i) < CODE_END):
            continue
        op = opname(img[i - 2], img[i - 1])
        if not op:
            continue
        img[i:i + 4] = (v + BLK_DELTA).to_bytes(4, "big")
        reloc[v] += 1
    # 0x100f7f30 == BLK_HI is exclusive above, so its refs are handled separately below.

    # handle the top boundary 0x100f7f30 explicitly: relocate cmpa/cmpi bounds, keep base-loads
    TOP = BLK_HI
    for i in range(2, N - 3):
        v = (img[i] << 24) | (img[i + 1] << 16) | (img[i + 2] << 8) | img[i + 3]
        if v != TOP or (BASE + i) >= CODE_END:
            continue
        op = opname(img[i - 2], img[i - 1])
        if not op:
            continue
        if op in BASE_LOADS:
            skip.append((BASE + i, op))            # global above the block -> keep
        else:
            img[i:i + 4] = (v + BLK_DELTA).to_bytes(4, "big")   # loop END bound -> relocate
            reloc[v] += 1

    total = sum(reloc.values())
    print(f"step 2: {total} refs relocated across the block; {len(skip)} top-global base-loads kept")
    for a, op in skip:
        print(f"    keep 0x{a:08x} {op} #0x{TOP:08x} (global above block)")

    # post-check: no operand ref left pointing into the OLD block span, except the kept globals
    left = 0
    for i in range(2, N - 3):
        v = (img[i] << 24) | (img[i + 1] << 16) | (img[i + 2] << 8) | img[i + 3]
        if BLK_LO <= v <= BLK_HI and (BASE + i) < CODE_END and opname(img[i - 2], img[i - 1]):
            if v == TOP and any(a == BASE + i for a, _ in skip):
                continue
            left += 1
    print(f"    remaining old-block operand refs in code: {left} (want 0)")
    if left:
        sys.exit("relocation incomplete")

    # boot-zero hook
    r = subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", "out/bootzero.o", "tools/patch_bootzero.s"])
    if r.returncode:
        sys.exit("assembler failed")
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{CAVE_AT:x}", "-o", "out/bootzero.elf", "out/bootzero.o"],
                   capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/bootzero.elf", "out/bootzero.bin"], check=True)
    nm = subprocess.run(["m68k-elf-nm", "out/bootzero.elf"], capture_output=True, text=True).stdout
    sym = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    blob = pathlib.Path("out/bootzero.bin").read_bytes()
    end = CAVE_AT + len(blob)
    if end > 0x400d7c3c:
        sys.exit("blob overruns cave")
    if any(img[off(CAVE_AT):off(end)]):
        sys.exit("cave not free")
    img[off(CAVE_AT):off(end)] = blob
    o = off(DETOUR_AT)
    if bytes(img[o:o + 6]).hex() != DETOUR_EXPECT:
        sys.exit(f"detour 0x{DETOUR_AT:08x}: {bytes(img[o:o+6]).hex()} want {DETOUR_EXPECT}")
    img[o:o + 6] = b"\x4e\xf9" + sym["bootzero_stub"].to_bytes(4, "big")
    print(f"boot-zero: detour 0x{DETOUR_AT:08x} -> 0x{sym['bootzero_stub']:08x}")

    OUT.write_bytes(bytes(img))
    print(f"\n{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
