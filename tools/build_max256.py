#!/usr/bin/env python3
"""
MAX256 — WHOLE-BLOCK relocation of the flex+static settings block (the correct, leak-free
approach), on pristine stock (DSP never touched).

Static-only settings relocation LEAKS: the firmware treats flex+static as ONE contiguous 264-slot
array (static_base = flex_base + 136*0x448 = 0x100d5b30), so many accesses reach static via
flex-relative / combined addressing that never appears as the literal static base 0x100d5b30.
Hardware proof: rebasing only the static refs left the static slot table empty / samples silent.

Fix: move the WHOLE block [0x100b14f0, 0x100f7f30) (flex 136 + static 128 = 264 slots) by ONE
DELTA to DDR, so EVERY relative address inside it stays valid -- no per-loop trampolines needed.
This is Phase 1's mechanism done right: BLK_HI = 0x100f7f30 exactly (the 2 pea base-loads of the
non-moving global above stay; the block-END bound refs move), and the DSP is never touched.

Layout in the verified-free hole:
    STATE-256   [0x46c96000, 0x46c98c00)   state base 0x46c90a78 -> 0x46c96000 (36 refs, clean)
    FLEX+STATIC [0x46c98c00, 0x46cdf640)   264 slots (flex_new=0x46c98c00, static_new=0x46cbd240)
    boot-zero [0x46c96000, 0x46cdf640) to replicate the SRAM pre-zero the block had.

MODE: neutral (static stays 128). The 256-static feature needs flex+static256 = 430 KB which does
NOT fit this 350 KB hole -- a bigger window / record-array move is a separate step. This gets a
WORKING relocated base first.

    python3 tools/build_max256.py     # -> out/mainos_max256.bin
"""
import pathlib, sys

BASE = 0x40000400
SRC = pathlib.Path("out/stock_mainos.bin")
OUT = pathlib.Path("out/mainos_max256.bin")

STATE_A, STATE_B = 0x46c90a78, 0x46c96000
BLK_LO, BLK_HI = 0x100b14f0, 0x100f7f30       # flex base .. static end (exclusive) == global base
BLK_B = 0x46c98c00                            # relocated block base (flex_new)
DELTA = BLK_B - BLK_LO
CAVE = 0x400d7400

# A value in range is relocated ONLY when it is a real OPERAND (preceded by a load/arith/cmp
# opcode) -- NOT every coincidental 4-byte window (moving those corrupts unrelated code/data;
# that regression hung the splash). Same opcode set as build_phase1.py.
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

BASE_LOADS = {"lea", "pea", "movea#", "move.l#", "move.l#abs", "jsr/jmp"}


def off(a):
    return a - BASE


def main():
    img = bytearray(SRC.read_bytes())

    # STATE: blanket rebase (36 refs, all static-access; template has 0 refs)
    nb = STATE_A.to_bytes(4, "big"); n = 0; i = img.find(nb)
    while i != -1:
        if BASE + i < 0x400e0000:
            img[i:i + 4] = STATE_B.to_bytes(4, "big"); n += 1
        i = img.find(nb, i + 1)
    assert n == 36, f"state refs {n}"
    print(f"STATE : {n} refs 0x{STATE_A:08x} -> 0x{STATE_B:08x}")

    # SETTINGS WHOLE-BLOCK: rebase every ref whose value is inside [BLK_LO, BLK_HI) by DELTA;
    # for the boundary value BLK_HI, keep base-loads (global above) and move bound refs.
    moved = 0; kept = 0; N = len(img)
    for k in range(2, N - 3):
        if BASE + k >= 0x400e0000:
            break
        v = (img[k] << 24) | (img[k + 1] << 16) | (img[k + 2] << 8) | img[k + 3]
        op = opname(img[k - 2], img[k - 1])
        if op is None:
            continue                                        # not an operand -> leave (coincidence)
        if BLK_LO <= v < BLK_HI:
            img[k:k + 4] = (v + DELTA).to_bytes(4, "big"); moved += 1
        elif v == BLK_HI:
            if op in BASE_LOADS:
                kept += 1                                   # global-above base-load -> keep
            else:
                img[k:k + 4] = (v + DELTA).to_bytes(4, "big"); moved += 1   # block-END bound
    print(f"BLOCK : moved {moved} operand refs +0x{DELTA:08x}; kept {kept} global base-loads")
    assert kept == 2, f"expected 2 global base-loads kept, got {kept}"

    # residual: no OPERAND ref left in the old block range (coincidental non-operand values stay)
    left = 0
    for k in range(2, N - 3):
        if BASE + k >= 0x400e0000:
            break
        v = (img[k] << 24) | (img[k + 1] << 16) | (img[k + 2] << 8) | img[k + 3]
        if BLK_LO <= v < BLK_HI and opname(img[k - 2], img[k - 1]):
            left += 1
    assert left == 0, f"{left} old-block operand refs remain"
    print("residual: 0 old-block operand refs OK")

    # BOOT-ZERO the relocated region [STATE_B, block end). Hook 0x4001fa64 (lea 0x10000000,a0).
    ZLO, ZHI = STATE_B, BLK_B + (BLK_HI - BLK_LO)          # [0x46c96000, 0x46cdf640)
    assert ZHI < 0x46ceb400, "region overruns hole"
    nlongs = (ZHI - ZLO) // 4
    STUB_AT = CAVE
    stub = bytes.fromhex(
        "4fefffc4" + "48d77fff" + "207c" + ZLO.to_bytes(4, "big").hex()
        + "203c" + nlongs.to_bytes(4, "big").hex() + "7200" + "20c1" + "5380" + "66fa"
        + "4cd77fff" + "4fef003c" + "41f910000000" + "4ef94001fa6a")
    assert not any(img[off(STUB_AT):off(STUB_AT) + len(stub)]), "cave overlap"
    img[off(STUB_AT):off(STUB_AT) + len(stub)] = stub
    o = off(0x4001fa64)
    assert bytes(img[o:o + 6]) == bytes.fromhex("41f910000000"), img[o:o + 6].hex()
    img[o:o + 6] = bytes.fromhex("4ef9") + STUB_AT.to_bytes(4, "big")
    print(f"BOOTZERO: [0x{ZLO:08x},0x{ZHI:08x}) ({nlongs} longs) @0x{STUB_AT:08x}; detour 0x4001fa64")

    OUT.write_bytes(bytes(img))
    print(f"\n{OUT}: {len(img):,} bytes  [whole-block relocation, static still 128]")


if __name__ == "__main__":
    main()
