#!/usr/bin/env python3
"""emu_seq_slot.py -- EMULATOR proof that the sequencer's effective-slot resolution (FUN_40005030, the
trackparam/voice-command path shared by the track DEFAULT slot AND a per-step SAMPLE-LOCK) maps a high
slot to SET-B and delivers it zero-extended.

At 0x40005080 the effective slot d3 = p-lock (arg3) if != -1 else the track default byte -- from there the
code is identical for lock vs default. We inject d3 = slot (as if from a p-lock), type d4=0 (STATIC), run
the STATIC branch (mvzb d3,d1 ; cmpi #255,d1 ; muls #1096 ; jsr h_set_d0) and read the resolved SETTINGS
pointer (d0) + the zero-extended slot (d1).

    python3 tools/emu_seq_slot.py
"""
import pathlib, sys
from unicorn import *
from unicorn.m68k_const import *
sys.path.insert(0, "tools")
import build_dual256 as bd

BASE = 0x40000400
IMG = bytes(pathlib.Path("out/mainos_persist256.bin").read_bytes())
SET_A, SET_B, STRIDE = 0x100d5b30, bd.SET_B, 0x448
START = 0x400050b8            # mvzb d3,d1 (effective slot -> d1)
SITE = 0x400050ce            # jsr h_set_d0
STOP = 0x400050d4            # after the jsr


def resolve(slot):
    mu = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    for a, s in [(0x40000000, 0x2000000), (0x10000000, 0x400000),
                 (0x46000000, 0x1000000), (0x00008000, 0x8000)]:
        mu.mem_map(a, s)
    mu.mem_write(BASE, IMG)
    mu.reg_write(UC_M68K_REG_D3, slot)    # effective slot (from p-lock)
    mu.reg_write(UC_M68K_REG_D4, 0)       # machine type = 0 (STATIC)
    mu.reg_write(UC_M68K_REG_A7, 0x0000c000)
    st = {"site": False}
    def hk(mu, addr, size, ud):
        if addr == SITE: st["site"] = True
        if addr == STOP: mu.emu_stop()
    mu.hook_add(UC_HOOK_CODE, hk)
    try:
        mu.emu_start(START, STOP, count=2000)
    except UcError:
        pass
    return mu.reg_read(UC_M68K_REG_D0), mu.reg_read(UC_M68K_REG_D1), st["site"]


def tag(a):
    if SET_A <= a < SET_A + 256 * STRIDE: return f"SET-A[{(a-SET_A)//STRIDE}]"
    if SET_B <= a < SET_B + 128 * STRIDE: return f"SET-B[{(a-SET_B)//STRIDE}]"
    return f"0x{a:08x}"


def main():
    print(f"SET-B=0x{SET_B:08x}  (p-lock slot -> FUN_40005030 STATIC resolve)\n")
    allok = True
    # the effective slot is a BYTE (mvzb d3,d1): valid range 0..255, all resolve; 256 can't occur.
    for slot in (0, 57, 127, 128, 200, 255):
        d0, d1, sited = resolve(slot)
        exp = (SET_B if slot >= 128 else SET_A) + (slot - (128 if slot >= 128 else 0)) * STRIDE
        ok = sited and d0 == exp and d1 == slot        # d1 = mvzb(slot) must equal slot (no sign trunc)
        allok &= ok
        print(f"  [{'OK ' if ok else 'FAIL'}] p-lock slot={slot:<3} -> SETTINGS={tag(d0):12} d1(zero-ext slot)={d1}")
    print("\n" + ("ALL GREEN -- a SAMPLE-LOCK to any byte slot 0..255 resolves correctly (128..255 -> SET-B, "
                  "e.g. idx=128->SET-B[0]) and the slot is delivered ZERO-extended (no sign truncation). "
                  "Identical code to the track default, which HW (P29) already plays."
                  if allok else "FAILURES -- re-examine"))


if __name__ == "__main__":
    main()
