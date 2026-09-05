#!/usr/bin/env python3
"""emu_plock_author.py -- function-level EMULATOR proof for wave 20 (p-lock AUTHORING caps).

Three in-place cap rewrites let the sample-lock VALUE reach 254 instead of 127:
  1. main setter FUN_4004f8dc @0x4004fa64 (value reloaded from sp@(16) into d3)
  2. live-rec  FUN_40043664 @0x40043682 (cap #1, value in d3 from sp@(28))
  3. live-rec  FUN_40043664 @0x400436a2 (cap #2 on the d0==1 path -- the spec missed it)

Contract: value 0..254 passes every cap; 255 (== the 0xff no-lock sentinel in table 0x46c7dff9),
300 and -1 bail. Playback of high-slot locks was already proven (emu_seq_plock) -- this only proves
the write gates.

    python3 tools/emu_plock_author.py [image]     (default out/mainos_persist256.bin)
"""
import pathlib, sys
from unicorn import *
from unicorn.m68k_const import *

BASE = 0x40000400
IMGPATH = sys.argv[1] if len(sys.argv) > 1 else "out/mainos_persist256.bin"
IMG = bytes(pathlib.Path(IMGPATH).read_bytes())
print(f"[emu_plock_author] image: {IMGPATH}")


def mk():
    mu = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    for a, s in [(0x40000000, 0x2000000), (0x10000000, 0x400000),
                 (0x46000000, 0x1000000), (0x80000000, 0x10000), (0x00008000, 0x8000)]:
        mu.mem_map(a, s)
    mu.mem_write(BASE, IMG)
    return mu


def run_until(mu, entry, accept_va, bail_va, count=300):
    st = {"hit": None}
    def hk(mu, addr, size, ud):
        if addr == accept_va:
            st["hit"] = "accept"; mu.emu_stop()
        elif addr == bail_va:
            st["hit"] = "bail"; mu.emu_stop()
    mu.hook_add(UC_HOOK_CODE, hk)
    try:
        mu.emu_start(entry, 0, count=count)
    except UcError:
        pass
    return st["hit"]


def setter_cap(value):
    """FUN_4004f8dc tail: entry 0x4004fa54 pushes d3,d2 (8 bytes) then reloads from the OUTER frame:
    sp@(12)->d2, sp@(16)->d3=VALUE, sp@(20)->d0=mode; relative to entry sp that is +4/+8/+12."""
    mu = mk()
    sp = 0x0000b000
    for i, v in enumerate([0xdeadbeef, 0, value & 0xffffffff, 1]):
        mu.mem_write(sp + i * 4, v.to_bytes(4, "big"))
    mu.reg_write(UC_M68K_REG_A7, sp)
    return run_until(mu, 0x4004fa54, 0x4004fa6c, 0x4004fb8e)


def liverec_caps(value):
    """FUN_40043664: args sp@(24)=track sp@(28)=value sp@(32)=mode AFTER lea -20 + moveml, i.e.
    at entry sp@(4)=track sp@(8)=value sp@(12)=mode. Gate 0x80000012 must be nonzero; mode=1 routes
    through BOTH caps; accept == reaching 0x400436a8 (past cap #2), bail == 0x4004371c."""
    mu = mk()
    mu.mem_write(0x80000012, b"\x00\x00\x00\x01")
    sp = 0x0000b000
    for i, v in enumerate([0xdeadbeef, 0, value & 0xffffffff, 1]):
        mu.mem_write(sp + i * 4, v.to_bytes(4, "big"))
    mu.reg_write(UC_M68K_REG_A7, sp)
    return run_until(mu, 0x40043664, 0x400436a8, 0x4004371c)


def main():
    allok = True
    cases = [(0, "accept"), (64, "accept"), (127, "accept"),      # stock range: must not regress
             (128, "accept"), (200, "accept"), (254, "accept"),   # new range
             (255, "bail"), (300, "bail"), (0xffffffff, "bail")]  # sentinel / OOR / -1
    for label, fn in [("setter 0x4004fa64", setter_cap), ("live-rec both caps", liverec_caps)]:
        row = []
        for v, exp in cases:
            got = fn(v)
            ok = got == exp
            allok &= ok
            row.append(f"{v if v < 0x80000000 else -1}:{got}{'' if ok else '<<EXP:'+exp}")
        print(f"  [{'OK ' if all('<<' not in r for r in row) else 'FAIL'}] {label}: " + " ".join(row))
    print("\n" + ("ALL GREEN -- p-lock authoring accepts 0..254 and still rejects 255/-1/OOR on every "
                  "write gate. (Function-level proof only.)" if allok else "FAILURES -- do not flash"))
    sys.exit(0 if allok else 1)


if __name__ == "__main__":
    main()
