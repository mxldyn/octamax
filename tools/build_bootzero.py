#!/usr/bin/env python3
"""
2afix base (pool move + settings->DDR, END pointers kept) + BOOT-ZERO of the DDR settings
home. Properly tests the uninitialized-DDR hypothesis at a point BEFORE the crash (the
earlier reload-orch zero-init ran too late). See tools/patch_bootzero.s.

    python3 tools/build.py           # -> out/mainos.bin (R11)
    python3 tools/build_bootzero.py  # -> out/mainos_bootzero.bin
"""
import pathlib, subprocess, sys
from collections import Counter

BASE = 0x40000400
R11 = pathlib.Path("out/mainos.bin")
OUT = pathlib.Path("out/mainos_bootzero.bin")

OLD_POOL, NEW_POOL = 0x40a955e0, 0x40af55e0
COUNT_AT, OLD_COUNT, NEW_COUNT = 0x40096f82, 0x390A, 0x38CA
TAB_LO, TAB_HI = 0x100d5b30, 0x100f7f31
TAB_END = 0x100f7f30
TAB_DELTA = 0x40a955e0 - 0x100d5b30
CODE_END = 0x400e0000
BASE_LOADS = {"lea", "pea", "movea#", "move.l#", "move.l#abs", "jsr/jmp"}

CAVE_AT = 0x400d72a0
DETOUR_AT = 0x4001fa64
DETOUR_EXPECT = "41f910000000"     # lea 0x10000000,a0 (6 bytes)
RESUME_AT = 0x4001fa6a


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

    # step 2a-fixed
    reloc = Counter(); skipped = 0
    N = len(img)
    for i in range(2, N - 3):
        v = (img[i] << 24) | (img[i + 1] << 16) | (img[i + 2] << 8) | img[i + 3]
        if not (TAB_LO <= v < TAB_HI and (BASE + i) < CODE_END):
            continue
        op = opname(img[i - 2], img[i - 1])
        if not op:
            continue
        if v == TAB_END and op in BASE_LOADS:
            skipped += 1
            continue
        img[i:i + 4] = (v + TAB_DELTA).to_bytes(4, "big")
        reloc[v] += 1
    total = sum(reloc.values())
    print(f"step 2a-fixed: {total} relocated, {skipped} END-pointers skipped")
    if total != 54 or skipped != 2:
        sys.exit(f"unexpected reloc set ({total}/{skipped})")

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
    print(f"boot-zero cave {len(blob)} B @ 0x{CAVE_AT:08x}..0x{end-1:08x} (cave ends 0x400d7c3b)")
    if end > 0x400d7c3c:
        sys.exit("blob overruns cave")
    if any(img[off(CAVE_AT):off(end)]):
        sys.exit("cave not free")
    img[off(CAVE_AT):off(end)] = blob

    o = off(DETOUR_AT)
    if bytes(img[o:o + 6]).hex() != DETOUR_EXPECT:
        sys.exit(f"detour 0x{DETOUR_AT:08x}: {bytes(img[o:o+6]).hex()} want {DETOUR_EXPECT}")
    img[o:o + 6] = b"\x4e\xf9" + sym["bootzero_stub"].to_bytes(4, "big")
    print(f"  detour 0x{DETOUR_AT:08x} -> bootzero_stub 0x{sym['bootzero_stub']:08x}, resume 0x{RESUME_AT:08x}")

    OUT.write_bytes(bytes(img))
    print(f"\n{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
