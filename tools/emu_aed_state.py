#!/usr/bin/env python3
"""emu_aed_state.py -- function-level EMULATOR proof that the migrated AED STATE resolvers land in
STATE-B for idx>=128. Each AED tab-body / waveform-stream fn resolves the slot STATE inline as
`cmpi #255,d1 ; bhi null ; moveq #44,dP ; muls d1,dP ; jsr h_st_dP`. We start at the clamp with d1=idx
pre-set (bypassing the descriptor read), run to just past the jsr, and read the resolved STATE ptr (dP).

Contract: idx 0..127 -> STATE-A[idx]; idx 128..255 -> STATE-B[idx-128]; idx 256 -> clamp bails (null).

    python3 tools/emu_aed_state.py
"""
import pathlib, sys
from unicorn import *
from unicorn.m68k_const import *
sys.path.insert(0, "tools")
import build_dual256 as bd

BASE = 0x40000400
IMG = bytes(pathlib.Path("out/mainos_persist256.bin").read_bytes())
ST_A, ST_B, STRIDE = 0x46c90a78, bd.SETB_HI, 44   # STATE-B base = 0x40ab79e0
DREG = {"d0": UC_M68K_REG_D0, "d2": UC_M68K_REG_D2}

# (label, clamp_va, site_instr_va, product_reg, bail_va)
FUNCS = [
    ("AED TRIM  0x4006f0a4", 0x4006f1b6, 0x4006f1c4, "d0", None),
    ("AED SLICE 0x40070db8", 0x40070ec8, 0x40070ed6, "d0", None),
    ("AED EDIT  0x40073b30", 0x40073bb8, 0x40073bc6, "d0", None),
    ("AED ATTR  0x4006e450", 0x4006e4c4, 0x4006e4d4, "d0", None),
    ("WAVESTRM1 0x400985ac", 0x400985c4, 0x400985d2, "d2", None),
    ("WAVESTRM2 0x4009871c", 0x40098734, 0x40098742, "d2", None),
]


def resolve(clamp_va, site_va, reg, idx):
    mu = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    for a, s in [(0x40000000, 0x2000000), (0x10000000, 0x400000),
                 (0x46000000, 0x1000000), (0x00008000, 0x8000)]:
        mu.mem_map(a, s)
    mu.mem_write(BASE, IMG)
    mu.reg_write(UC_M68K_REG_D1, idx)
    sp = 0x0000c000
    mu.reg_write(UC_M68K_REG_A7, sp)
    stop = site_va + 6           # just past the 6-byte jsr h_st_dP
    st = {"site": False}
    def hk(mu, addr, size, ud):
        if addr == site_va:      # the resolver add/jsr actually executed (not bailed by the clamp)
            st["site"] = True
        if addr == stop:
            mu.emu_stop()
    mu.hook_add(UC_HOOK_CODE, hk)
    try:
        mu.emu_start(clamp_va, stop, count=3000)
    except UcError:
        pass
    return mu.reg_read(DREG[reg]), st["site"]


def tag(a):
    if ST_A <= a < ST_A + 256 * STRIDE: return f"STATE-A[{(a-ST_A)//STRIDE}]"
    if ST_B <= a < ST_B + 128 * STRIDE: return f"STATE-B[{(a-ST_B)//STRIDE}]"
    return f"0x{a:08x}"


def main():
    print(f"STATE-A=0x{ST_A:08x}  STATE-B=0x{ST_B:08x}\n")
    allok = True
    for label, clamp, site, reg, _ in FUNCS:
        row = []
        for idx, exp in [(57, ST_A + 57 * STRIDE), (128, ST_B), (255, ST_B + 127 * STRIDE)]:
            val, sited = resolve(clamp, site, reg, idx)
            ok = sited and (val == exp)
            allok &= ok
            row.append(f"idx={idx}->{tag(val)}{'' if ok else ' !!'}")
        # idx=256 must bail (clamp), i.e. the resolver add/jsr must NOT execute
        _, sited256 = resolve(clamp, site, reg, 256)
        bail_ok = not sited256
        allok &= bail_ok
        row.append(f"idx=256 {'bails(OK)' if bail_ok else 'REACHED-SITE !!'}")
        print(f"  [{'OK ' if all('!!' not in r for r in row) else 'FAIL'}] {label} ({reg}):  " + " | ".join(row))
    print("\n" + ("ALL GREEN -- every AED STATE resolver maps idx=128->STATE-B[0], 255->STATE-B[127], "
                  "57->STATE-A[57], 256->bail. The AED tab canvases read STATE-B for high slots."
                  if allok else "FAILURES -- re-examine"))


if __name__ == "__main__":
    main()
