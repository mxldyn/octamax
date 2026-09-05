#!/usr/bin/env python3
"""
FRAME-LEVEL verifier — the safety net for the force-feed.

The DSP is not emulated, but the DSP's INPUT is: every audio frame the CPU frame
builder (FUN_4000c8a4) writes a per-voice parameter frame into shared RAM
(0x80000000 double-buffer, selector 0x800000e0). If the builder writes a valid
"play R7 on track 6" frame, the real DSP would play it. So we can verify
"is the CPU feeding R7?" WITHOUT hearing audio.

This harness runs the REAL frame builder under Unicorn and dumps what it writes
to the frame region, so we can see (a) what a track-6 recorder frame looks like,
(b) that clearing the trig-set play-state stops producing it, (c) that restoring
it resumes — the exact before/after the force-feed needs.

Usage: python3 tools/emu_frame.py
"""
import subprocess, sys, pathlib, struct
from unicorn import *
from unicorn.m68k_const import *

BASE = 0x40000400
IMG = pathlib.Path("out/mainos.bin").read_bytes()   # R11 base (stock frame builder)

FRAME_BUILDER = 0x4000c8a4
# the trig-set per-track play-state (track index 6 = UI track 7)
PLAYFLAGS = 0x8000188e + 6 * 4      # 0x800018a6
TIMING    = 0x8000186e + 6 * 4      # 0x80001886
DSPASSIGN = 0x80000110 + (6 + 0xbcf) * 2   # 0x800018ba
MTYPE     = 0x46c80354 + 6 * 4      # 0x46c8036c
VOICE6    = 0x800049d8 + 6 * 0xA8   # 0x80004dc8
# frame double-buffer region to watch (voice params live in 0x80000000..0x80001800)
FRAME_LO, FRAME_HI = 0x80000000, 0x80001800


def new_uc():
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    uc.mem_map(0x40000000, 0x200000); uc.mem_write(BASE, IMG[: 0x200000 - 0x400])
    uc.mem_map(0x46000000, 0x1000000)
    uc.mem_map(0x80000000, 0x20000)
    uc.mem_map(0x10000000, 0x1000000)
    uc.mem_map(0x41000000, 0x20000)
    uc.mem_map(0x20000000, 0x1000)
    uc.mem_write(0x20000008, struct.pack(">I", 0x6))
    uc.mem_map(0xFC000000, 0x100000)
    def on_unmapped(uc, access, address, size, value, user):
        uc.mem_map(address & ~0xFFF, 0x1000); return True
    uc.hook_add(UC_HOOK_MEM_UNMAPPED, on_unmapped)
    return uc


def rd(uc, a, n=4): return int.from_bytes(uc.mem_read(a, n), "big")


def run_builder(label, setup, maxins=200000):
    uc = new_uc()
    uc.reg_write(UC_M68K_REG_SR, 0x2700)
    # plausible engine globals
    uc.mem_write(0x46c82456, struct.pack(">I", 0x46d00000))   # project base
    uc.mem_write(0x800000e0, struct.pack(">I", 0x80000200))   # DSP frame double-buffer ptr
    uc.mem_write(0x80001814, struct.pack(">I", 120))          # tempo
    setup(uc)
    # frame writes we care about
    writes = {}
    def on_write(uc, access, address, size, value, user):
        if FRAME_LO <= address < FRAME_HI:
            writes[address] = (value, size)
    uc.hook_add(UC_HOOK_MEM_WRITE, on_write)
    RET = 0x401f0000
    sp = 0x41010000
    sp -= 4; uc.mem_write(sp, struct.pack(">I", RET))
    uc.reg_write(UC_M68K_REG_A7, sp)
    err = None
    try:
        uc.emu_start(FRAME_BUILDER, RET, count=maxins)
    except UcError as e:
        err = "%s @ PC=0x%08x" % (e, uc.reg_read(UC_M68K_REG_PC))
    print(f"\n=== {label} ===")
    if err: print(f"   [stopped: {err}]  frame writes so far: {len(writes)}")
    else:   print(f"   [ran to completion]  frame writes: {len(writes)}")
    # summarize writes near track-6 voice slots (heuristic: group by 0x40 stride)
    for a in sorted(writes)[:40]:
        v, sz = writes[a]
        print(f"     [0x{a:08x}] = 0x{v:08x} ({sz}B)")
    return writes


def playing(uc):
    """track 6 set up as 'playing R7' (recorder buffer, machine type 4/flex)."""
    uc.mem_write(MTYPE, struct.pack(">I", 0x40))            # flex machine
    uc.mem_write(VOICE6, struct.pack(">B", 1))              # voice active
    uc.mem_write(VOICE6 + 0x14, struct.pack(">b", 4))       # voice type = recorder playback
    uc.mem_write(PLAYFLAGS, struct.pack(">I", 0x140))       # play flags (bit8 set + machine)
    uc.mem_write(TIMING, struct.pack(">I", 0x1000))         # some loop timing
    uc.mem_write(DSPASSIGN, struct.pack(">H", (4 << 10) | 0x86))  # (type<<10)|slot(R7=0x86)


def cleared(uc):
    """simulate the mid-load state: play-state cleared."""
    uc.mem_write(MTYPE, struct.pack(">I", 0))
    uc.mem_write(VOICE6, struct.pack(">B", 0))
    uc.mem_write(PLAYFLAGS, struct.pack(">I", 0))
    uc.mem_write(TIMING, struct.pack(">I", 0))
    uc.mem_write(DSPASSIGN, struct.pack(">H", 0))


if __name__ == "__main__":
    print("FRAME builder 0x%08x  | track6 state: playflags@0x%08x timing@0x%08x assign@0x%08x"
          % (FRAME_BUILDER, PLAYFLAGS, TIMING, DSPASSIGN))
    a = run_builder("A. track6 PLAYING R7", playing)
    b = run_builder("B. track6 CLEARED (mid-load)", cleared)
    # diff: which frame addresses appear in A but not B (that's track 6's contribution)
    only_a = sorted(set(a) - set(b))
    print(f"\n### frame addresses written ONLY when track6 is playing: {len(only_a)} ###")
    for x in only_a[:40]:
        print(f"     [0x{x:08x}] = 0x{a[x][0]:08x}")
