#!/usr/bin/env python3
"""
Step 1 (pool relocation) + Step 2a (relocate STATIC settings table to DDR 0x40a955e0)
+ ACR0 copyback->writethrough, on R11. Tests whether the step-2a crash is COPYBACK
cache staleness (a 2nd bus master reading stale settings from physical memory).

  ACR0 runtime = 0x4007e020 (E=1, CM=01 COPYBACK) over DDR 0x40000000-0x47ffffff,
  which includes the relocated settings at 0x40a955e0. The old SRAM (0x100d5b30) falls
  to the CACR default DDCM = writethrough (memory always current). Under copyback the
  CPU's settings writes linger in cache; a 2nd master (audio DMA) reading settings from
  memory during a live CHANGE sees stale data -> "corrupt noises + hang". This also
  explains why zero-init failed: the zeros stayed in cache, physical memory kept garbage.

  Fix/test: ACR0 0x4007e020 -> 0x4007e000 (CM=01 -> CM=00 WRITETHROUGH), matching the
  old SRAM behavior. Writethrough is still cached (fast reads) and Elektron itself uses
  0x4007e000 in another init path, so this is low-risk. Whole pool stays cacheable.

    python3 tools/build.py        # -> out/mainos.bin (R11)
    python3 tools/build_wthru.py  # -> out/mainos_wthru.bin
"""
import pathlib, sys

BASE = 0x40000400
R11 = pathlib.Path("out/mainos.bin")
OUT = pathlib.Path("out/mainos_wthru.bin")

# --- step 1: pool relocation ---
OLD_POOL, NEW_POOL = 0x40a955e0, 0x40af55e0
COUNT_AT, OLD_COUNT, NEW_COUNT = 0x40096f82, 0x390A, 0x38CA

# --- step 2a: static settings table relocation ---
TAB_LO, TAB_HI = 0x100d5b30, 0x100f7f31
TAB_DELTA = 0x40a955e0 - 0x100d5b30
CODE_END = 0x400e0000

# --- ACR0 copyback -> writethrough ---
ACR0_CB, ACR0_WT = 0x4007e020, 0x4007e000   # CM=01 (copyback) -> CM=00 (writethrough)


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
            img[i:i + 4] = (v + TAB_DELTA).to_bytes(4, "big")
            byval[v] += 1
    total = sum(byval.values())
    print(f"step 2a: settings 0x{TAB_LO:08x} -> 0x{TAB_LO+TAB_DELTA:08x}  ({total} operand refs, {len(byval)} distinct)")
    if not (50 <= total <= 62 and len(byval) == 4):
        sys.exit(f"unexpected settings-ref set (total {total}, distinct {len(byval)}) — aborting")

    # === ACR0 copyback -> writethrough (all init sites) ===
    nacr = img.count(ACR0_CB.to_bytes(4, "big"))
    if not (1 <= nacr <= 5):
        sys.exit(f"ACR0 copyback-immediate count {nacr} unexpected — aborting")
    img = bytearray(img.replace(ACR0_CB.to_bytes(4, "big"), ACR0_WT.to_bytes(4, "big")))
    print(f"ACR0: 0x{ACR0_CB:08x} -> 0x{ACR0_WT:08x} (copyback -> writethrough, {nacr} sites)")

    OUT.write_bytes(bytes(img))
    print(f"\n{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
