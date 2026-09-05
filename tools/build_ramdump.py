#!/usr/bin/env python3
"""
Step 1 (pool relocation / reserve) + Step 2a (relocate the STATIC settings table into the
reserved region), on R11.

  STATUS: Step 1 is HARDWARE-CONFIRMED (pool moves cleanly, audio intact, 384 KB reserved,
  canary-verified). Step 2a **crashes on hardware** ("corrupt" noises + hang at project load):
  the 0x448/slot settings table is DSP-read, so relocating only the CPU operand refs leaves the
  DSP reading the old SRAM address. See NOTES.md "Reclaiming fixed RAM from the flex pool". The
  step-2a block below is kept for reference; the DSP-side address source must be handled first.

  Step 1  flex pool +64 pages:  base 0x40a955e0->0x40af55e0 (23 refs), count 0x390A->0x38CA.
          -> [0x40a955e0, 0x40af55e0) (384 KB) reserved below the pool.
  Step 2a static settings table 0x100d5b30 -> 0x40a955e0 (delta +0x309bfab0). Relocated at
          every OPERAND-position ref in the CODE region whose value lands in the table span
          [0x100d5b30, 0x100f7f30] (BASE + END + slot-0 field refs); data-region coincidences
          are excluded. Table stays 128 slots (0x22400) for now — this only proves relocation.

    python3 tools/build.py          # -> out/mainos.bin (R11)
    python3 tools/build_ramdump.py  # -> out/mainos_ramdump.bin
"""
import pathlib, sys

BASE = 0x40000400
R11 = pathlib.Path("out/mainos.bin")
OUT = pathlib.Path("out/mainos_ramdump.bin")

# --- step 1: pool relocation ---
OLD_POOL, NEW_POOL = 0x40a955e0, 0x40af55e0
COUNT_AT, OLD_COUNT, NEW_COUNT = 0x40096f82, 0x390A, 0x38CA

# --- step 2a: static settings table relocation ---
TAB_LO, TAB_HI = 0x100d5b30, 0x100f7f31     # [base, end] inclusive
TAB_DELTA = 0x40a955e0 - 0x100d5b30         # 0x309bfab0
CODE_END = 0x400e0000                       # relocate only operand refs in executable code


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

    # === step 2a: relocate the static settings table (operand refs in code) ===
    from collections import Counter
    byval = Counter()
    N = len(img)
    for i in range(2, N - 3):
        v = (img[i] << 24) | (img[i + 1] << 16) | (img[i + 2] << 8) | img[i + 3]
        if TAB_LO <= v < TAB_HI and (BASE + i) < CODE_END and opname(img[i - 2], img[i - 1]):
            nv = v + TAB_DELTA
            img[i:i + 4] = nv.to_bytes(4, "big")
            byval[v] += 1
    total = sum(byval.values())
    print(f"step 2a: static settings table 0x{TAB_LO:08x} -> 0x{TAB_LO+TAB_DELTA:08x}  ({total} operand refs, {len(byval)} distinct)")
    for v, c in sorted(byval.items()):
        print(f"    0x{v:08x} x{c} -> 0x{v+TAB_DELTA:08x}")
    if not (50 <= total <= 62 and len(byval) == 4):
        sys.exit(f"unexpected settings-ref set (total {total}, distinct {len(byval)}) — aborting")

    # post-check: no operand ref into the OLD table span left in code
    left = 0
    for i in range(2, N - 3):
        v = (img[i] << 24) | (img[i + 1] << 16) | (img[i + 2] << 8) | img[i + 3]
        if TAB_LO <= v < TAB_HI and (BASE + i) < CODE_END and opname(img[i - 2], img[i - 1]):
            left += 1
    print(f"    remaining old-table operand refs in code: {left} (want 0)")
    if left:
        sys.exit("relocation incomplete")

    OUT.write_bytes(bytes(img))
    print(f"\n{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
