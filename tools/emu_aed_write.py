#!/usr/bin/env python3
"""emu_aed_write.py -- function-level EMULATOR proof that the migrated AED "load sample to slot" WRITE
resolvers target SET-B/STATE-B for idx>=128 (so loading a sample into a high slot populates SET-B, and a
later SAVE persists real data instead of an empty project.256).

  FUNC A 0x40024510 (idx in d3): resolves SETTINGS[idx] (d2) + STATE[idx] (d0). Run clamp..past both adds.
  FUNC B 0x40024854 (idx in d2): resolves STATE[idx] (d0).                       Run clamp..past the add.

    python3 tools/emu_aed_write.py
"""
import pathlib, sys
from unicorn import *
from unicorn.m68k_const import *
sys.path.insert(0, "tools")
import build_dual256 as bd

BASE = 0x40000400
IMG = bytes(pathlib.Path("out/mainos_persist256.bin").read_bytes())
SET_A, SET_B = 0x100d5b30, bd.SET_B          # 0x40a955e0
ST_A, ST_B = 0x46c90a78, bd.SETB_HI          # 0x40ab79e0
SSTRIDE, TSTRIDE = 0x448, 44


def run(start, stop, idxreg, idx):
    mu = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    for a, s in [(0x40000000, 0x2000000), (0x10000000, 0x400000),
                 (0x46000000, 0x1000000), (0x00008000, 0x8000)]:
        mu.mem_map(a, s)
    mu.mem_write(BASE, IMG)
    mu.reg_write(idxreg, idx)
    mu.reg_write(UC_M68K_REG_A7, 0x0000c000)
    try:
        mu.emu_start(start, stop, count=3000)
    except UcError:
        pass
    return mu.reg_read(UC_M68K_REG_D0), mu.reg_read(UC_M68K_REG_D2)


def tset(a):
    if SET_A <= a < SET_A + 256 * SSTRIDE: return f"SET-A[{(a-SET_A)//SSTRIDE}]"
    if SET_B <= a < SET_B + 128 * SSTRIDE: return f"SET-B[{(a-SET_B)//SSTRIDE}]"
    return f"0x{a:08x}"


def tst(a):
    if ST_A <= a < ST_A + 256 * TSTRIDE: return f"STATE-A[{(a-ST_A)//TSTRIDE}]"
    if ST_B <= a < ST_B + 128 * TSTRIDE: return f"STATE-B[{(a-ST_B)//TSTRIDE}]"
    return f"0x{a:08x}"


def main():
    print(f"SET-B=0x{SET_B:08x}  STATE-B=0x{ST_B:08x}\n")
    allok = True
    # FUNC A: clamp 0x4002455e, idx=d3, stop 0x40024584 (past STATE add). d2=SET ptr, d0=STATE ptr.
    print("FUNC A 0x40024510 (SETTINGS d2 + STATE d0):")
    for idx in (57, 128, 255):
        d0, d2 = run(0x4002455e, 0x40024584, UC_M68K_REG_D3, idx)
        eset = (SET_B if idx >= 128 else SET_A) + (idx - (128 if idx >= 128 else 0)) * SSTRIDE
        est = (ST_B if idx >= 128 else ST_A) + (idx - (128 if idx >= 128 else 0)) * TSTRIDE
        ok = (d2 == eset) and (d0 == est)
        allok &= ok
        print(f"  [{'OK ' if ok else 'FAIL'}] idx={idx:<3} SET={tset(d2):12} STATE={tst(d0)}")
    # FUNC B: clamp 0x40024922, idx=d2, stop 0x40024936 (past STATE add). d0=STATE ptr.
    print("FUNC B 0x40024854 (STATE d0):")
    for idx in (57, 128, 255):
        d0, _ = run(0x40024922, 0x40024936, UC_M68K_REG_D2, idx)
        est = (ST_B if idx >= 128 else ST_A) + (idx - (128 if idx >= 128 else 0)) * TSTRIDE
        ok = (d0 == est)
        allok &= ok
        print(f"  [{'OK ' if ok else 'FAIL'}] idx={idx:<3} STATE={tst(d0)}")
    print("\n" + ("ALL GREEN -- AED load-sample write path targets SET-B/STATE-B for idx=128..255. Loading a "
                  "sample into a high slot now writes B; a subsequent SAVE persists real data."
                  if allok else "FAILURES -- re-examine"))


if __name__ == "__main__":
    main()
