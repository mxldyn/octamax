#!/usr/bin/env python3
"""emu_otreader.py -- function-level EMULATOR proof for CORE wave 19 (the .ot sidecar reader
FUN_4008b8d0). The prologue resolves the destination SETTINGS record and the STRIDE4 flag entry
from (type d5, slot d4):

    STATIC (d5==0): cmpi.l #255,d4 ; bhiw bail(-2)          <- clamp raised from #128 by the wave
                    d0 = d4*1096 ; a3 = d0 ; jsr h_set_a3   <- was adda.l #SET_A,a3
                    ... a0 = d4*4 ; jsr h_s42_a0            <- was adda.l #S42_A,a0
    FLEX (d5==1|4): #135 clamp + 0x100b14f0 / h_s41_a0      <- table stock, flag via helper (family
                                                               convention, same as copypaste/resetslot)

Asserts, per idx: a3 lands in SETTINGS-A/-B per the aligned contract (128->B[0]), a0 lands in the
matching STRIDE4 table, idx=256 bails at the clamp WITHOUT reaching the resolver, and the bail path
returns -2 (the "SAMPLE LOAD ERRORS!" popup source for high slots before this wave).

    python3 tools/emu_otreader.py [image]     (default out/mainos_persist256.bin)
"""
import pathlib, sys
from unicorn import *
from unicorn.m68k_const import *
sys.path.insert(0, "tools")
import build_dual256 as bd

BASE = 0x40000400
IMGPATH = sys.argv[1] if len(sys.argv) > 1 else "out/mainos_persist256.bin"
IMG = bytes(pathlib.Path(IMGPATH).read_bytes())
print(f"[emu_otreader] image: {IMGPATH}")

SET_A, SET_B, STRIDE = bd.SET_A, bd.SET_B, bd.SET_STRIDE
S42_A, S42_B = bd.S42_A, bd.S42_B
S41_A, S41_B = bd.S41_A, bd.S41_B
FLEX_A = 0x100b14f0

CLAMP   = 0x4008b8ee          # cmpi.l #bound,%d4 (STATIC branch)
SITE_A3 = 0x4008b904          # jsr h_set_a3 (was adda.l #SET_A,a3)
SITE_S42= 0x4008b946          # jsr h_s42_a0
SITE_S41= 0x4008b950          # jsr h_s41_a0 (FLEX flag)
STOP    = 0x4008b956          # clrl %a0@  -- both resolvers done
BAIL    = 0x4008be16          # moveq #-2 (STATIC clamp bail)
ENTRY   = 0x4008b8ea          # tstl %d5 (skip the stream-NULL test; d3 preset nonzero)


def run(typ, idx):
    mu = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    for a, s in [(0x40000000, 0x2000000), (0x10000000, 0x400000),
                 (0x46000000, 0x1000000), (0x00008000, 0x8000)]:
        mu.mem_map(a, s)
    mu.mem_write(BASE, IMG)
    mu.reg_write(UC_M68K_REG_D3, 0x00009000)      # fake nonzero stream
    mu.reg_write(UC_M68K_REG_D5, typ)
    mu.reg_write(UC_M68K_REG_D4, idx)
    mu.reg_write(UC_M68K_REG_A7, 0x0000c000)
    st = {"site": False, "bail": False}
    def hk(mu, addr, size, ud):
        if addr in (SITE_A3, SITE_S42, SITE_S41):
            st["site"] = True
        if addr == BAIL:
            st["bail"] = True
            mu.emu_stop()
        if addr == STOP:
            mu.emu_stop()
    mu.hook_add(UC_HOOK_CODE, hk)
    try:
        mu.emu_start(ENTRY, STOP, count=2000)
    except UcError:
        pass
    return mu.reg_read(UC_M68K_REG_A3), mu.reg_read(UC_M68K_REG_A0), st


def tag(a):
    for base, n, s, name in [(SET_A, 129, STRIDE, "SET-A"), (SET_B, 128, STRIDE, "SET-B"),
                             (FLEX_A, 136, STRIDE, "FLEX-A"),
                             (S42_A, 129, 4, "S42-A"), (S42_B, 128, 4, "S42-B"),
                             (S41_A, 136, 4, "S41-A"), (S41_B, 128, 4, "S41-B")]:
        if base <= a < base + n * s:
            return f"{name}[{(a-base)//s}]"
    return f"0x{a:08x}"


def main():
    allok = True
    print("STATIC (d5=0): dest a3=SETTINGS, flag a0=STRIDE4#2")
    for idx, exp_a3, exp_a0 in [(57,  SET_A + 57 * STRIDE,  S42_A + 57 * 4),
                                (128, SET_B,                S42_B),
                                (139, SET_B + 11 * STRIDE,  S42_B + 11 * 4),   # UI slot 140
                                (255, SET_B + 127 * STRIDE, S42_B + 127 * 4)]:
        a3, a0, st = run(0, idx)
        ok = st["site"] and not st["bail"] and a3 == exp_a3 and a0 == exp_a0
        allok &= ok
        print(f"  [{'OK ' if ok else 'FAIL'}] idx={idx:3d}: a3={tag(a3)} a0={tag(a0)}")
    _, _, st = run(0, 256)
    ok = st["bail"] and not st["site"]
    allok &= ok
    print(f"  [{'OK ' if ok else 'FAIL'}] idx=256: {'bails -2 before any resolver' if ok else 'DID NOT BAIL'}")
    print("FLEX (d5=1): dest a3=FLEX-A stock, flag a0=STRIDE4#1")
    for idx, exp_a3, exp_a0 in [(5,   FLEX_A + 5 * STRIDE,  S41_A + 5 * 4),
                                (135, FLEX_A + 135 * STRIDE, S41_B + 7 * 4)]:  # recorder: flag in B (family convention)
        a3, a0, st = run(1, idx)
        ok = st["site"] and not st["bail"] and a3 == exp_a3 and a0 == exp_a0
        allok &= ok
        print(f"  [{'OK ' if ok else 'FAIL'}] idx={idx:3d}: a3={tag(a3)} a0={tag(a0)}")
    print("\n" + ("ALL GREEN -- the .ot reader resolves SET-B/S42-B for idx 128..255, stock for <128, "
                  "bails -2 only past 255. (Function-level proof: does NOT prove the reader is reached.)"
                  if allok else "FAILURES -- do not flash"))
    sys.exit(0 if allok else 1)


if __name__ == "__main__":
    main()
