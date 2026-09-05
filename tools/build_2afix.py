#!/usr/bin/env python3
"""
Step 1 (pool relocation) + Step 2a-FIXED (relocate STATIC settings table to DDR 0x40a955e0,
but DO NOT relocate the two base-load pointers to the exclusive-end address 0x100f7f30).

  Root cause of the step-2a crash (found by opcode-classifying all 56 refs):
  0x100f7f30 is the byte just past the last settings slot (table = [0x100d5b30, 0x100f7f30),
  exactly 128 x 0x448). It doubles as: (a) the loop-bound END for iterating the table, and
  (b) the BASE of a separate ~260-byte structure sitting immediately after the table in SRAM.
  Nine refs use 0x100f7f30: seven are cmpa/cmpi loop BOUNDS (relocate correctly, in lockstep
  with the base) and two are `pea 0x100f7f30` POINTER loads feeding strcpy(0x40013f40) /
  memcpy(0x40013f5c) that read/write that adjacent structure during project load. Blanket 2a
  relocated the two pea to 0x40af7f30 (inside the flex pool) -> the copies scribble on the pool
  -> "corrupt noises + hang at load". This is why zero-init and writethrough did nothing (it's
  a wrong pointer, not a memory-behavior issue) and why an empty boot is fine (the copies only
  run on a real project load).

  Fix: skip base-load ops (pea/lea/movea#/move.l#/jsr) whose value == 0x100f7f30; that adjacent
  structure stays in SRAM. Bounds (cmpa/cmpi/immarith/adda) to 0x100f7f30 still relocate.

    python3 tools/build.py         # -> out/mainos.bin (R11)
    python3 tools/build_2afix.py   # -> out/mainos_2afix.bin
"""
import pathlib, sys
from collections import Counter

BASE = 0x40000400
R11 = pathlib.Path("out/mainos.bin")
OUT = pathlib.Path("out/mainos_2afix.bin")

OLD_POOL, NEW_POOL = 0x40a955e0, 0x40af55e0
COUNT_AT, OLD_COUNT, NEW_COUNT = 0x40096f82, 0x390A, 0x38CA

TAB_LO, TAB_HI = 0x100d5b30, 0x100f7f31
TAB_END = 0x100f7f30                        # exclusive end == adjacent struct base
TAB_DELTA = 0x40a955e0 - 0x100d5b30
CODE_END = 0x400e0000

BASE_LOADS = {"lea", "pea", "movea#", "move.l#", "move.l#abs", "jsr/jmp"}


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

    # === step 1: pool relocation ===
    n = img.count(OLD_POOL.to_bytes(4, "big"))
    if not (18 <= n <= 30):
        sys.exit(f"pool-base count {n} unexpected — aborting")
    img = bytearray(img.replace(OLD_POOL.to_bytes(4, "big"), NEW_POOL.to_bytes(4, "big")))
    o = off(COUNT_AT)
    if int.from_bytes(img[o:o + 4], "big") != OLD_COUNT:
        sys.exit(f"count @0x{COUNT_AT:08x} != 0x{OLD_COUNT:x}")
    img[o:o + 4] = NEW_COUNT.to_bytes(4, "big")
    print(f"step 1: pool 0x{OLD_POOL:08x}->0x{NEW_POOL:08x} ({n} refs), count 0x{OLD_COUNT:x}->0x{NEW_COUNT:x}")

    # === step 2a-fixed: relocate settings refs, skip END base-load pointers ===
    reloc = Counter()
    skipped = []
    N = len(img)
    for i in range(2, N - 3):
        v = (img[i] << 24) | (img[i + 1] << 16) | (img[i + 2] << 8) | img[i + 3]
        if not (TAB_LO <= v < TAB_HI and (BASE + i) < CODE_END):
            continue
        op = opname(img[i - 2], img[i - 1])
        if not op:
            continue
        if v == TAB_END and op in BASE_LOADS:
            skipped.append((BASE + i, op))
            continue
        img[i:i + 4] = (v + TAB_DELTA).to_bytes(4, "big")
        reloc[v] += 1
    total = sum(reloc.values())
    print(f"step 2a-fixed: settings 0x{TAB_LO:08x} -> 0x{TAB_LO+TAB_DELTA:08x}  ({total} refs relocated)")
    for v, c in sorted(reloc.items()):
        print(f"    0x{v:08x} x{c} -> 0x{v+TAB_DELTA:08x}")
    print(f"  SKIPPED (adjacent-struct pointers, left in SRAM): {len(skipped)}")
    for a, op in skipped:
        print(f"    0x{a:08x} {op} -> 0x{TAB_END:08x} (unchanged)")
    if len(skipped) != 2 or total != 54:
        sys.exit(f"unexpected: {total} relocated, {len(skipped)} skipped (want 54 / 2) — aborting")

    OUT.write_bytes(bytes(img))
    print(f"\n{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
