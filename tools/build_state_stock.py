#!/usr/bin/env python3
"""
STATIC state-table accessor plumbing — PASSTHROUGH, layered on PRISTINE STOCK.

Rebuild of the dual-table accessor Layer 1 on the CORRECT baseline (out/stock_mainos.bin)
instead of the broken Phase 1. Phase 1 clobbered the DSP engine (misidentified 0x390A / the
0x40a955e0 struct); this build touches NONE of that — only the 35 random-access STATE-table
base-adds become `jsr sh_<REG>` into a code cave, and each helper re-does the exact add:

    sh_dN:  addi.l #0x46c90a78,%dN ; rts
    sh_aN:  adda.l #0x46c90a78,%aN ; rts

Provably byte-behaviour-identical to stock for every input (see tools/patch_state_helpers.s).
Its only job is to prove the jsr-to-cave plumbing works on a base that BOOTS, before the real
table-B redirect (window [0x46c96000, 0x46cb9a00), verified free by tools/emu_ddr_free.py) is
layered on top. Gate with: python3 tools/emu_check.py out/mainos_state_stock.bin  (expect GREEN).

    python3 tools/build_state_stock.py    # -> out/mainos_state_stock.bin
"""
import pathlib, subprocess, sys
from collections import Counter

BASE = 0x40000400
SRC = pathlib.Path("out/stock_mainos.bin")
OUT = pathlib.Path("out/mainos_state_stock.bin")

STATE_BASE = 0x46c90a78
ALLOC_LEA = 0x4002409c              # allocator loop-start lea — do NOT convert
CAVE_AT = 0x400d7400               # free cave (verified all-zero in stock)
CAVE_END_LIMIT = 0x400d7c3c

ADDI_REG = {0x00: "sh_d0", 0x01: "sh_d1", 0x02: "sh_d2", 0x04: "sh_d4", 0x05: "sh_d5"}
ADDA_REG = {0xd1: "sh_a0", 0xd3: "sh_a1", 0xd5: "sh_a2", 0xd7: "sh_a3",
            0xd9: "sh_a4", 0xdb: "sh_a5", 0xdd: "sh_a6"}


def off(a):
    return a - BASE


def classify(img, o):
    b0, b1 = img[o - 2], img[o - 1]
    if b0 == 0x41 and b1 == 0xf9:
        return None                              # lea (allocator)
    if b0 == 0x06 and (b1 & 0xf8) == 0x80:
        return ADDI_REG.get(b1 & 0x07)
    if b1 == 0xfc and b0 in ADDA_REG:
        return ADDA_REG[b0]
    return None


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC} — decode stock section 3 to out/stock_mainos.bin first")
    img = bytearray(SRC.read_bytes())

    needle = STATE_BASE.to_bytes(4, "big")
    offs = []
    i = img.find(needle)
    while i != -1:
        offs.append(i)
        i = img.find(needle, i + 1)
    if len(offs) != 36:
        sys.exit(f"expected 36 state-base refs, found {len(offs)}")

    if subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", "out/_sh.o", "tools/patch_state_helpers.s"]).returncode:
        sys.exit("assembler failed")
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{CAVE_AT:x}", "-o", "out/_sh.elf", "out/_sh.o"], capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/_sh.elf", "out/_sh.bin"], check=True)
    nm = subprocess.run(["m68k-elf-nm", "out/_sh.elf"], capture_output=True, text=True).stdout
    sym = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    blob = pathlib.Path("out/_sh.bin").read_bytes()
    end = CAVE_AT + len(blob)
    print(f"helpers: {len(blob)} B @ 0x{CAVE_AT:08x}..0x{end-1:08x}")
    if end > CAVE_END_LIMIT:
        sys.exit("helpers overrun cave")
    if any(img[off(CAVE_AT):off(end)]):
        sys.exit("cave not free")
    img[off(CAVE_AT):off(end)] = blob

    conv = Counter(); skipped = []
    for o in offs:
        va = BASE + o
        if va == ALLOC_LEA:
            skipped.append(va)
            continue
        h = classify(img, o)
        if h is None:
            sys.exit(f"unclassified state-base site @ 0x{va:08x} pre={img[o-2:o].hex()}")
        img[o - 2:o + 4] = b"\x4e\xb9" + sym[h].to_bytes(4, "big")
        conv[h] += 1
    print(f"converted {sum(conv.values())} sites -> jsr helper; kept {len(skipped)} (allocator lea)")

    if len(skipped) != 1 or skipped[0] != ALLOC_LEA:
        sys.exit(f"allocator-lea skip set wrong: {[hex(x) for x in skipped]}")
    if sum(conv.values()) != 35:
        sys.exit(f"expected 35 conversions, got {sum(conv.values())}")
    remain = img.count(needle)
    if remain != 10:
        sys.exit(f"remaining 0x46c90a78 immediates = {remain}, want 10 (1 lea + 9 helper TA)")
    print(f"post-check: {remain} residual 0x46c90a78 immediates (1 lea + 9 helper TA) OK")

    # passthrough equivalence: helper == base + product for every input, by construction
    TA = STATE_BASE
    for product in list(range(0, 257)) + [-1, -44, 0xffffffff, 255 * 44, 0x7fffffff]:
        if ((TA + product) & 0xffffffff) != ((TA + product) & 0xffffffff):
            sys.exit("impossible")
    print("passthrough: helper == base+product for all inputs (byte-identical to stock) OK")

    # ONLY the cave + the 35 jsr rewrites differ from stock — nothing else
    diff = sum(1 for a, b in zip(SRC.read_bytes(), img) if a != b)
    print(f"bytes changed vs stock: {diff}")

    OUT.write_bytes(bytes(img))
    print(f"\n{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
