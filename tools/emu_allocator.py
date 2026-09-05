#!/usr/bin/env python3
"""emu_allocator.py -- EMULATOR of the STATIC free-slot allocator FUN_40024098.

Walks STATE[i].status@8 for a FREE slot (status==1) and returns the index. Stock walks only
STATE-A[0..127] (bound #128 at 0x400240b2) -> can never allocate a high slot even if STATE-B has free
entries. This emulates it (stopping at FOUND 0x400240bc / NOTFOUND 0x400240d2, reading d1) for:
  (A) all STATE-A used              -> NOTFOUND
  (B) STATE-A[50] free              -> 50
  (C) STATE-A full, STATE-B[10] free -> STOCK: NOTFOUND (B unreachable) ; EXTENDED: 138

Run with --img to point at a patched build.  python3 tools/emu_allocator.py [--img out/mainos_persist256.bin]
"""
import pathlib, sys
from unicorn import *
from unicorn.m68k_const import *

BASE = 0x40000400
ST_A, ST_B, STRIDE = 0x46c90a78, 0x40ab79e0, 44
ENTRY = 0x40024098
FOUND, NOTFOUND = 0x400240bc, 0x400240d2

IMGPATH = "out/stock_mainos.bin"
if "--img" in sys.argv:
    IMGPATH = sys.argv[sys.argv.index("--img") + 1]
IMG = bytes(pathlib.Path(IMGPATH).read_bytes())


def run(free_a=(), free_b=()):
    mu = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    for a, s in [(0x40000000, 0x2000000), (0x10000000, 0x400000),
                 (0x46000000, 0x1000000), (0x80000000, 0x10000), (0x00008000, 0x8000)]:
        mu.mem_map(a, s)
    mu.mem_write(BASE, IMG)
    # default: every slot status@8 = 0 (USED). set the chosen ones FREE (=1).
    for i in free_a:
        mu.mem_write(ST_A + i * STRIDE + 8, (1).to_bytes(4, "big"))
    for i in free_b:
        mu.mem_write(ST_B + i * STRIDE + 8, (1).to_bytes(4, "big"))
    res = {"idx": None, "found": None}
    def hk(mu, addr, size, ud):
        if addr == FOUND:
            res["idx"] = mu.reg_read(UC_M68K_REG_D1); res["found"] = True; mu.emu_stop()
        elif addr == NOTFOUND:
            res["idx"] = mu.reg_read(UC_M68K_REG_D1); res["found"] = False; mu.emu_stop()
    mu.hook_add(UC_HOOK_CODE, hk)
    mu.reg_write(UC_M68K_REG_A7, 0x0000c000)
    try:
        mu.emu_start(ENTRY, 0, count=100000)
    except UcError:
        pass
    return res


def main():
    print(f"img={IMGPATH}  STATE-A=0x{ST_A:08x} STATE-B=0x{ST_B:08x}\n")
    cases = [
        ("all STATE-A used", (), ()),
        ("STATE-A[50] free", (50,), ()),
        ("STATE-A full, STATE-B[10] free", (), (10,)),
    ]
    for label, fa, fb in cases:
        r = run(fa, fb)
        verdict = f"FOUND slot {r['idx']}" if r["found"] else "NOTFOUND (no free slot)"
        print(f"  {label:34} -> {verdict}")
    print("\n(Stock: case 3 = NOTFOUND -- B unreachable. Extended allocator should return 138.)")


if __name__ == "__main__":
    main()
