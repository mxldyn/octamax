#!/usr/bin/env python3
"""
scan_hole.py — hypothesis-A test #1 (static): does ANY operand-position pointer literal in the
stock OS land INSIDE the relocation hole [0x46c96000, 0x46cdf640)? If yes, the hole is occupied by
a statically-addressed structure and relocation collides. Prints the full occupancy map of the
DDR neighbourhood [0x46c90000, 0x46cf0000) so we can see exactly what lives where.

    python3 tools/scan_hole.py
"""
import pathlib
from collections import defaultdict

BASE = 0x40000400
IMG = pathlib.Path("out/stock_mainos.bin").read_bytes()

NBR_LO, NBR_HI = 0x46c90000, 0x46cf0000        # neighbourhood to map
HOLE_LO, HOLE_HI = 0x46c96000, 0x46cdf640      # the relocation target (must be empty)


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
    N = len(IMG)
    occ = defaultdict(list)     # value -> list of (va_of_ref, op)
    in_hole = []
    for k in range(2, N - 3):
        if BASE + k >= 0x400e0000:
            break
        v = (IMG[k] << 24) | (IMG[k + 1] << 16) | (IMG[k + 2] << 8) | IMG[k + 3]
        if not (NBR_LO <= v < NBR_HI):
            continue
        op = opname(IMG[k - 2], IMG[k - 1])
        if op is None:
            continue                                  # coincidental value, not a real pointer
        occ[v].append((BASE + k, op))
        if HOLE_LO <= v < HOLE_HI:
            in_hole.append((v, BASE + k, op))

    print(f"OCCUPANCY of [0x{NBR_LO:08x},0x{NBR_HI:08x}) by operand-position pointer literals:")
    for v in sorted(occ):
        refs = occ[v]
        tag = "  <-- INSIDE HOLE" if HOLE_LO <= v < HOLE_HI else ""
        ops = ",".join(sorted({o for _, o in refs}))
        print(f"  0x{v:08x}  x{len(refs):<3} [{ops}]{tag}")

    print(f"\nHOLE [0x{HOLE_LO:08x},0x{HOLE_HI:08x}) operand-literal hits: {len(in_hole)}")
    for v, va, op in in_hole:
        print(f"    0x{v:08x} referenced by {op} @0x{va:08x}")
    print("\n=> " + ("HOLE OCCUPIED (relocation collides)" if in_hole
                      else "no static pointer literal lands in the hole"))


if __name__ == "__main__":
    main()
