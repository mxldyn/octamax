#!/usr/bin/env python3
"""emu_seq_plock.py -- EMULATOR proof of the SAMPLE-LOCK (p-lock) READ path for high slots.

The p-lock slot is loaded from pattern data (table 0x46c7dff9, stride 32) with mvsb (SIGNED byte) at
0x40043d66 / 0x4004fb22 and passed as the effective-slot arg (d3) to FUN_40005030. The resolver checks
d3 == -1 (= "no lock", use default) then does mvzb d3,d1 to index SETTINGS. Feeding d3 = mvsb(byte) we
prove: byte 128..254 -> the low byte is recovered (mvzb) -> SET-B[idx-128]; byte 0xff -> -1 -> "no lock"
-> falls to the track DEFAULT (the inherent limit: slot 255 can't be sample-locked, only used as default).

    python3 tools/emu_seq_plock.py
"""
import pathlib, sys
from unicorn import *
from unicorn.m68k_const import *
sys.path.insert(0, "tools")
import build_dual256 as bd

BASE = 0x40000400
IMG = bytes(pathlib.Path("out/mainos_persist256.bin").read_bytes())
SET_A, SET_B, STRIDE = 0x100d5b30, bd.SET_B, 0x448
START = 0x40005080           # moveq #-1,d0 ; cmpl d3,d0 (the "no lock" check)
SITE = 0x400050ce            # jsr h_set_d0
STOP = 0x400050d4
DEFAULT_BYTE = 5             # track default slot, used when d3 == -1


def mvsb(b):
    return b if b < 0x80 else (b | 0xffffff00)


def run(plock_byte):
    mu = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    for a, s in [(0x40000000, 0x2000000), (0x10000000, 0x400000),
                 (0x46000000, 0x1000000), (0x80000000, 0x10000), (0x00008000, 0x8000)]:
        mu.mem_map(a, s)
    mu.mem_write(BASE, IMG)
    mu.reg_write(UC_M68K_REG_D3, mvsb(plock_byte))   # effective slot arg (mvsb of the p-lock byte)
    mu.reg_write(UC_M68K_REG_D1, DEFAULT_BYTE)       # track default byte (used iff d3 == -1)
    mu.reg_write(UC_M68K_REG_D4, 0)                  # STATIC type
    mu.reg_write(UC_M68K_REG_D5, 1)                  # pass the audio-track gate (bit1 clear, non-zero)
    mu.reg_write(UC_M68K_REG_D6, 0x40)               # skip the @297/0x400d8120 param path
    mu.mem_write(0x800065b8, (1).to_bytes(4, "big")) # "audio track" == 1
    mu.mem_write(0x460d172a, (0).to_bytes(4, "big")) # gate flag == 0
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
    return mu.reg_read(UC_M68K_REG_D0), st["site"]


def tag(a):
    if SET_A <= a < SET_A + 256 * STRIDE: return f"SET-A[{(a-SET_A)//STRIDE}]"
    if SET_B <= a < SET_B + 128 * STRIDE: return f"SET-B[{(a-SET_B)//STRIDE}]"
    return f"0x{a:08x}"


def main():
    print(f"SET-B=0x{SET_B:08x}  DEFAULT slot={DEFAULT_BYTE}  (p-lock byte -> mvsb -> FUN_40005030)\n")
    allok = True
    # 128..254 must resolve to SET-B; 0xff (255) must fall to the default (inherent no-lock collision)
    cases = [(0x80, "SET-B[0]"), (0xc8, "SET-B[72]"), (0xfe, "SET-B[126]"),
             (0x39, "SET-A[57]"), (0xff, "-> DEFAULT (no-lock)")]
    for b, note in cases:
        d0, sited = run(b)
        if b == 0xff:
            ok = (d0 == SET_A + DEFAULT_BYTE * STRIDE)     # used default
            got = tag(d0) + " (=default, slot 255 not lockable)"
        else:
            exp = (SET_B if b >= 0x80 else SET_A) + ((b - 0x80) if b >= 0x80 else b) * STRIDE
            ok = sited and d0 == exp
            got = tag(d0)
        allok &= ok
        print(f"  [{'OK ' if ok else 'FAIL'}] p-lock byte=0x{b:02x} ({b:>3}) -> {got}")
    print("\n" + ("ALL GREEN -- SAMPLE-LOCK reads correctly for slots 0..254 (128..254 -> SET-B via mvzb "
                  "recovery); slot 255 is the sole inherent limit (0xff == the no-lock sentinel) and falls "
                  "back to the track default. NO firmware change needed for p-lock 128..254."
                  if allok else "FAILURES -- re-examine"))


if __name__ == "__main__":
    main()
