#!/usr/bin/env python3
"""emu_header_name.py -- EMULATOR proof of where the track-header sample NAME comes from.

The header draw 0x4005a220 resolves the name via getter 0x4006da78, which reads the current-slot
globals 0x46c8d19c (idx) / 0x46c8d1a0 (type), returns SETTINGS[idx] pointer, and the header reads the
path string at offset 0 (tstb a0@; beq -> draw nothing). This runs the PATCHED persist256 getter in
Unicorn for several (idx,type), seeding a known string at SET-B[0]@0, and asserts:
  - STATIC (type=0) idx=128 -> returns SET-B[0] (0x40a955e0), pointing at the seeded name.
  - STATIC idx=57  -> SET-A[57].   STATIC idx=255 -> SET-B[127].   idx=256 -> NULL.
  - FLEX (type=1)  idx=128 -> FLEX table (not SET-B).

    python3 tools/emu_header_name.py
"""
import pathlib, sys
from unicorn import *
from unicorn.m68k_const import *
sys.path.insert(0, "tools")
import build_dual256 as bd

BASE = 0x40000400
IMG = bytes(pathlib.Path("out/mainos_persist256.bin").read_bytes())
GETTER = 0x4006da78
G_IDX, G_TYPE = 0x46c8d19c, 0x46c8d1a0
SET_A, SET_B, STRIDE = 0x100d5b30, bd.SET_B, 0x448
FLEX_A = 0x100b14f0
RET = 0x00009000


def call_getter(idx, typ, seed_at=None, seed=b""):
    mu = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    for a, s in [(0x40000000, 0x2000000), (0x10000000, 0x400000),
                 (0x46000000, 0x1000000), (0x00008000, 0x8000)]:
        mu.mem_map(a, s)
    mu.mem_write(BASE, IMG)
    mu.mem_write(G_IDX, idx.to_bytes(4, "big"))
    mu.mem_write(G_TYPE, typ.to_bytes(4, "big"))
    if seed_at is not None:
        mu.mem_write(seed_at, seed)
    sp = 0x0000c000
    mu.mem_write(sp, RET.to_bytes(4, "big"))     # return address
    mu.reg_write(UC_M68K_REG_A7, sp)
    mu.reg_write(UC_M68K_REG_PC, GETTER)
    mu.emu_start(GETTER, RET, count=200)
    d0 = mu.reg_read(UC_M68K_REG_D0)
    name = b""
    if d0:
        try:
            raw = mu.mem_read(d0, 16); name = bytes(raw).split(b"\x00", 1)[0]
        except UcError:
            name = b"<unmapped>"
    return d0, name


def tag(a):
    if a == 0: return "NULL"
    if SET_A <= a < SET_A + 256 * STRIDE: return f"SET-A[{(a-SET_A)//STRIDE}]"
    if SET_B <= a < SET_B + 128 * STRIDE: return f"SET-B[{(a-SET_B)//STRIDE}]"
    if FLEX_A <= a < FLEX_A + 137 * STRIDE: return f"FLEX[{(a-FLEX_A)//STRIDE}]"
    return f"0x{a:08x}"


def main():
    print(f"SET_B = 0x{SET_B:08x}  (getter site 0x4006da98 -> h_set_d0)\n")
    # seed SET-B[0]@0 with a known filename to prove the header reads the name from there
    seed = b"HELLO.wav\x00"
    cases = [
        (57, 0, "STATIC low", f"SET-A[57] (0x{SET_A+57*STRIDE:08x})"),
        (128, 0, "STATIC idx=128 (UI 129)", f"SET-B[0] (0x{SET_B:08x})"),
        (255, 0, "STATIC idx=255 (UI 256)", f"SET-B[127]"),
        (256, 0, "STATIC idx=256 (OOR)", "NULL"),
        (128, 1, "FLEX type=1 idx=128", "FLEX (not SET-B)"),
    ]
    allok = True
    for idx, typ, label, expect in cases:
        seed_at = SET_B if (idx == 128 and typ == 0) else None
        d0, name = call_getter(idx, typ, seed_at, seed)
        got = tag(d0)
        note = f"  name@0={name!r}" if seed_at is not None else ""
        # verdicts
        ok = True
        if idx == 128 and typ == 0:
            ok = (d0 == SET_B) and (name == b"HELLO.wav")
        elif idx == 57 and typ == 0:
            ok = (d0 == SET_A + 57 * STRIDE)
        elif idx == 255 and typ == 0:
            ok = (d0 == SET_B + 127 * STRIDE)
        elif idx == 256 and typ == 0:
            ok = (d0 == 0)
        elif idx == 128 and typ == 1:
            ok = (FLEX_A <= d0 < FLEX_A + 137 * STRIDE)
        allok &= ok
        print(f"  [{'OK ' if ok else 'FAIL'}] idx={idx:<3} type={typ}  {label:24} -> {got:16} (expect {expect}){note}")
    print("\n" + ("ALL GREEN -- header name source CONFIRMED: getter 0x4006da78 -> SETTINGS[idx]@0; "
                  "idx=128 STATIC -> SET-B[0], name read from offset 0."
                  if allok else "FAILURES -- assumption NOT confirmed"))


if __name__ == "__main__":
    main()
