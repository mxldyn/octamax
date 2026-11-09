#!/usr/bin/env python3
"""
emu_lazy.py -- LAZY TRANSITIONS on the REAL image: restore_stub (apply_part's exit) and
enc_apply (the encoder-editor trampolines), run from their detour targets in the built image.

    python3 tools/emu_lazy.py [out/mainos_all.bin]

What it asserts (OCTAMAX_2h):
  restore_stub  a sounding track is kept on its SOURCE params only when its (bank, part) changes;
                a re-apply with the same (bank, part) stands (stock result untouched); a track that
                never had a part applied (0xFF) or is silent is not protected; LZ_SNAPOK records
                exactly the protected tracks; the destination params are parked in LZ_DEST; the
                caller's registers, the stack and post()'s arguments reach 0x40000c3c untouched.
  enc_apply     moving an encoder commits the track only when it is in transition (protected and
                still behind the active bank/part): the voice buffer gets LZ_DEST, the per-track
                bytes the active (bank, part), LZ_SNAPOK is cleared, SR is restored, and the
                editor's displaced prologue runs (resume 0x40052ea0 with the same registers).
The RAM block must live outside the stock analysis-task buffer 0x80006964..0x80007574.
"""
import pathlib, struct, sys
from unicorn import *
from unicorn.m68k_const import *

BASE = 0x40000400
IMG = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "out/mainos_all.bin").read_bytes()

F_LAZY = 0x800000d8
VOICE = 0x80000a50
TRK_BANK, TRK_PART = 0x8000182a, 0x80001832
ARG_BANK, ARG_PART = 0x80001828, 0x80001829      # apply_part's arguments
ACT_BANK, ACT_PART = 0x80000002, 0x80000003
VOICES = 0x800049d8                               # byte 0 of each 0xa8 struct = active
CUR_TRACK = 0x100b14cc
RAM = 0x40af0000
LZ_SAVE, LZ_PART, LZ_PART_B = RAM, RAM + 0x200, RAM + 0x208
LZ_PLAYING, LZ_SNAPOK, LZ_DEST = RAM + 0x220, RAM + 0x228, RAM + 0x400
RESTORE, POST = 0x400d6542, 0x40000c3c
ENC_E98, ENC_RESUME = 0x400d6600, 0x40052ea0

CALLEE = [UC_M68K_REG_D2, UC_M68K_REG_D3, UC_M68K_REG_D4, UC_M68K_REG_D5, UC_M68K_REG_D6,
          UC_M68K_REG_D7, UC_M68K_REG_A2, UC_M68K_REG_A3, UC_M68K_REG_A4, UC_M68K_REG_A5,
          UC_M68K_REG_A6]
FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        FAILS.append(name)


def machine():
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    uc.mem_map(0x40000000, 0x200000)
    uc.mem_write(BASE, IMG)
    uc.mem_map(0x40af0000, 0x1000)
    uc.mem_map(0x80000000, 0x10000)
    uc.mem_map(0x10000000, 0x200000)
    uc.mem_map(0x41000000, 0x20000)
    return uc


def blk(uc, a, n=0x40):
    return bytes(uc.mem_read(a, n))


def pat(seed):
    return bytes((seed + i) & 0xff for i in range(0x40))


def setup(uc, lazy, tracks, arg_bank, arg_part):
    """tracks: {t: (playing, saved_bank, saved_part, stale_snapok)} ; voice = DEST pattern (what
    apply_part just wrote), LZ_SAVE = SOURCE pattern."""
    uc.mem_write(F_LAZY, struct.pack(">I", lazy))
    uc.mem_write(ARG_BANK, bytes([arg_bank, arg_part]))
    for t in range(8):
        playing, sb, sp_, stale = tracks.get(t, (0, arg_bank, arg_part, 0))
        uc.mem_write(LZ_PLAYING + t, bytes([playing]))
        uc.mem_write(LZ_PART + t, bytes([sb]))
        uc.mem_write(LZ_PART_B + t, bytes([sp_]))
        uc.mem_write(LZ_SNAPOK + t, bytes([stale]))
        uc.mem_write(TRK_BANK + t, bytes([arg_bank]))      # what apply_part just wrote
        uc.mem_write(TRK_PART + t, bytes([arg_part]))
        uc.mem_write(VOICE + t * 0x40, pat(0x80 + t))       # destination
        uc.mem_write(LZ_SAVE + t * 0x40, pat(0x10 + t))     # source
        uc.mem_write(LZ_DEST + t * 0x40, b"\xee" * 0x40)


def run_restore(uc):
    uc.mem_write(POST, b"\x4e\x75")                  # post(): rts (we stop on arrival)
    sp0 = 0x41018000
    uc.mem_write(sp0, struct.pack(">III", 0xdead0001, 0x11112222, 0x33334444))  # ret, q, msg
    uc.reg_write(UC_M68K_REG_A7, sp0)
    for i, r in enumerate(CALLEE):
        uc.reg_write(r, 0x5a000000 + i)
    got = {}

    def hook(uc, addr, size, _):
        if addr == POST:
            got["sp"] = uc.reg_read(UC_M68K_REG_A7)
            got["regs"] = [uc.reg_read(r) for r in CALLEE]
            got["args"] = struct.unpack(">III", uc.mem_read(got["sp"], 12))
            uc.emu_stop()
    uc.hook_add(UC_HOOK_CODE, hook)
    uc.emu_start(RESTORE, 0, count=20000)
    ok = (got.get("sp") == sp0 and got.get("regs") == [0x5a000000 + i for i in range(len(CALLEE))]
          and got.get("args") == (0xdead0001, 0x11112222, 0x33334444))
    return ok, got


def restore_case(name, lazy, tracks, arg_bank, arg_part, protected):
    uc = machine()
    setup(uc, lazy, tracks, arg_bank, arg_part)
    clean, got = run_restore(uc)
    m = [] if clean else [f"registers/stack/post args disturbed: {got}"]
    for t in range(8):
        pr = t in protected
        snap = uc.mem_read(LZ_SNAPOK + t, 1)[0]
        if snap != (1 if pr else 0):
            m.append(f"t{t} SNAPOK={snap}")
        if pr:
            if blk(uc, VOICE + t * 0x40) != pat(0x10 + t):
                m.append(f"t{t} voice not restored to SOURCE")
            if blk(uc, LZ_DEST + t * 0x40) != pat(0x80 + t):
                m.append(f"t{t} DEST not parked")
            want = (tracks[t][1], tracks[t][2])
            if (uc.mem_read(TRK_BANK + t, 1)[0], uc.mem_read(TRK_PART + t, 1)[0]) != want:
                m.append(f"t{t} per-track bytes not the source")
        else:
            if blk(uc, VOICE + t * 0x40) != pat(0x80 + t):
                m.append(f"t{t} voice touched (stock result must stand)")
            if (uc.mem_read(TRK_BANK + t, 1)[0], uc.mem_read(TRK_PART + t, 1)[0]) != (arg_bank, arg_part):
                m.append(f"t{t} per-track bytes touched")
    check(name, not m, "; ".join(m))


def enc_case(name, lazy, track, bank, part, act_bank, act_part, snapok, commits):
    uc = machine()
    uc.mem_write(F_LAZY, struct.pack(">I", lazy))
    uc.mem_write(CUR_TRACK, bytes([track]))
    uc.mem_write(ACT_BANK, bytes([act_bank, act_part]))
    for t in range(8):
        uc.mem_write(TRK_BANK + t, bytes([bank if t == track else act_bank]))
        uc.mem_write(TRK_PART + t, bytes([part if t == track else act_part]))
        uc.mem_write(LZ_SNAPOK + t, bytes([snapok if t == track else 0]))
        uc.mem_write(VOICE + t * 0x40, pat(0x10 + t))
        uc.mem_write(LZ_DEST + t * 0x40, pat(0x80 + t))
    sp0 = 0x41018000
    uc.reg_write(UC_M68K_REG_SR, 0x2000)          # first: writing SR banks the stack pointer
    uc.reg_write(UC_M68K_REG_A7, sp0)
    for i, r in enumerate(CALLEE):
        uc.reg_write(r, 0x5a000000 + i)
    for r, v in ((UC_M68K_REG_D0, 0xd0d0d0d0), (UC_M68K_REG_D1, 0xd1d1d1d1),
                 (UC_M68K_REG_A0, 0xa0a0a0a0), (UC_M68K_REG_A1, 0xa1a1a1a1)):
        uc.reg_write(r, v)
    got = {}

    def hook(uc, addr, size, _):
        if addr == ENC_RESUME:
            got["sp"] = uc.reg_read(UC_M68K_REG_A7)
            got["sr"] = uc.reg_read(UC_M68K_REG_SR)
            got["d01a01"] = [uc.reg_read(r) for r in (UC_M68K_REG_D0, UC_M68K_REG_D1,
                                                       UC_M68K_REG_A0, UC_M68K_REG_A1)]
            got["saved"] = struct.unpack(">8I", uc.mem_read(got["sp"], 32))
            uc.emu_stop()
    uc.hook_add(UC_HOOK_CODE, hook)
    uc.emu_start(ENC_E98, 0, count=20000)
    m = []
    # displaced prologue: lea -0x20,sp ; movem.l d2-d7/a2-a3,(sp)  (mask 0x0cfc)
    if got.get("sp") != sp0 - 0x20:
        m.append(f"resume sp {got.get('sp')}")
    elif got["saved"] != tuple(0x5a000000 + i for i in range(8)):
        m.append(f"prologue saved {got['saved']}")
    if got.get("d01a01") != [0xd0d0d0d0, 0xd1d1d1d1, 0xa0a0a0a0, 0xa1a1a1a1]:
        m.append("scratch registers handed to the editor changed")
    if got.get("sr", 0) & 0x0700 != 0:
        m.append(f"SR left masked {got.get('sr'):#x}")
    v = blk(uc, VOICE + track * 0x40)
    bytes_now = (uc.mem_read(TRK_BANK + track, 1)[0], uc.mem_read(TRK_PART + track, 1)[0])
    snap = uc.mem_read(LZ_SNAPOK + track, 1)[0]
    if commits:
        if v != pat(0x80 + track): m.append("voice not committed from DEST")
        if bytes_now != (act_bank, act_part): m.append(f"per-track bytes {bytes_now}")
        if snap != 0: m.append("SNAPOK not cleared")
    else:
        if v != pat(0x10 + track): m.append("voice touched")
        if bytes_now != (bank, part): m.append("per-track bytes touched")
        if snap != snapok: m.append("SNAPOK touched")
    for t in range(8):
        if t != track and blk(uc, VOICE + t * 0x40) != pat(0x10 + t):
            m.append(f"other track {t} touched")
    check(name, not m, "; ".join(m))


print("== restore_stub (apply_part exit)")
restore_case("bank+part change, track sounding: protected", 1,
             {3: (1, 2, 1, 0)}, 5, 0, {3})
restore_case("part change inside the bank: protected", 1,
             {3: (1, 5, 1, 0)}, 5, 0, {3})
restore_case("re-apply, same bank+part (edit / scene assign): stock stands", 1,
             {3: (1, 5, 0, 0)}, 5, 0, set())
restore_case("re-apply clears a stale SNAPOK", 1,
             {3: (1, 5, 0, 1)}, 5, 0, set())
restore_case("never applied (0xFF bytes): not protected", 1,
             {4: (1, 0xff, 0xff, 0)}, 5, 0, set())
restore_case("silent track: not protected, stale SNAPOK cleared", 1,
             {6: (0, 2, 1, 1)}, 5, 0, set())
restore_case("mixed: t0 change, t1 same, t2 silent, t7 change", 1,
             {0: (1, 2, 3, 0), 1: (1, 5, 0, 0), 2: (0, 1, 1, 0), 7: (1, 5, 2, 0)}, 5, 0, {0, 7})
restore_case("LAZY off: nothing", 0,
             {3: (1, 2, 1, 0)}, 5, 0, set())

print("== enc_apply (encoder editor 0x40052e98)")
enc_case("in transition (part behind): commit", 1, 3, 5, 1, 5, 0, 1, True)
enc_case("in transition (bank behind): commit", 1, 3, 2, 0, 5, 0, 1, True)
enc_case("protected but already caught up by a trig: nothing", 1, 3, 5, 0, 5, 0, 1, False)
enc_case("behind but no snapshot (boot 0xFF): nothing", 1, 3, 0xff, 0xff, 5, 0, 0, False)
enc_case("LAZY off: nothing", 0, 3, 5, 1, 5, 0, 1, False)
enc_case("track 7: commit", 1, 7, 5, 3, 5, 0, 1, True)

print("\n" + ("ALL GREEN" if not FAILS else "FAIL: " + ", ".join(FAILS)))
sys.exit(1 if FAILS else 0)
