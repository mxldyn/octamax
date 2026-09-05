#!/usr/bin/env python3
"""
Emulate FUN_40007960 (the per-frame recorder-voice PLAY/MUTE decision) under Unicorn.
Unlike the frame builder, this function uses no ColdFire EMAC -> it RUNS. So we can
verify which state makes it take PLAY vs a MUTE branch, WITHOUT flashing.

MUTE branches: 0x40008110 (->FUN_40006820 stop), 0x4000812c (MUTE2), 0x40008f78.
PLAY continues past 0x400079cc (calls FUN_40001598, then writes DSP params).

Usage: python3 tools/emu_recvoice.py
"""
from unicorn import *
from unicorn.m68k_const import *
import struct, pathlib

IMG = pathlib.Path("out/mainos.bin").read_bytes(); BASE = 0x40000400
V6 = 0x80004dc8            # voice[6]
M = 0x46c939cc            # R7 recorder metadata
MUTE = {0x40008110: "MUTE-stop(FUN_40006820)", 0x4000812c: "MUTE2", 0x40008f78: "clr-path"}


def run(label, voice, meta, args=None, maxins=8000):
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    uc.mem_map(0x40000000, 0x200000); uc.mem_write(BASE, IMG[:0x200000 - 0x400])
    uc.mem_map(0x46000000, 0x1000000); uc.mem_map(0x80000000, 0x20000)
    uc.mem_map(0x10000000, 0x1000000); uc.mem_map(0x41000000, 0x20000)
    uc.mem_map(0x20000000, 0x1000); uc.mem_map(0xFC000000, 0x100000)
    uc.hook_add(UC_HOOK_MEM_UNMAPPED, lambda uc, a, ad, s, v, u: (uc.mem_map(ad & ~0xFFF, 0x1000), True)[1])
    uc.reg_write(UC_M68K_REG_SR, 0x2700)
    # seed voice[6] + metadata
    for off, val in voice.items():
        uc.mem_write(V6 + off, struct.pack(">I", val & 0xffffffff))
    for off, val in meta.items():
        uc.mem_write(M + off, struct.pack(">I", val & 0xffffffff))
    # args frame (A6-relative): (0x8,A6)=oldSP+4 ... (0x12,A6)word=oldSP+0xe track
    sp = 0x41010000; RET = 0x401f0000
    a = args or {}
    for off, val in {4: a.get(0x8, 0), 8: a.get(0xc, 0), 0xe: (6 << 16) | a.get(0x12, 0),
                     0x10: a.get(0x14, 0), 0x18: a.get(0x1c, 0)}.items():
        uc.mem_write(sp + off, struct.pack(">I", val & 0xffffffff))
    uc.mem_write(sp, struct.pack(">I", RET)); uc.reg_write(UC_M68K_REG_A7, sp)
    outcome = ["(ran to RET = PLAY-complete)"]
    reached = []
    def code(uc, pc, sz, u):
        if pc in MUTE:
            outcome[0] = MUTE[pc]; reached.append(pc); uc.emu_stop()
        elif pc == 0x400079cc:
            reached.append(pc)      # passed metadata+gen+active checks; entering FUN_40001598 stage
    uc.hook_add(UC_HOOK_CODE, code)
    err = None
    try:
        uc.emu_start(0x40007960, RET, count=maxins)
    except UcError as e:
        err = "%s @0x%08x" % (e, uc.reg_read(UC_M68K_REG_PC)); outcome[0] = "CRASH " + err
    passed = "passed-checks@79cc " if 0x400079cc in reached else ""
    print(f"  {label:42s} -> {passed}{outcome[0]}")
    return outcome[0]


GOOD_VOICE = {0x0: 0xFF000000, 0x4: 0x46c939cc, 0x10: 8}
GOOD_META = {0x8: 0, 0x10: 0x1000, 0x14: 8}   # state=0, length>0, gen==voice+0x10

if __name__ == "__main__":
    print("FUN_40007960 PLAY/MUTE decision — what state mutes R7?\n")
    run("valid (hot_recmeta target)", GOOD_VOICE, GOOD_META)
    run("length=0 (metadata zeroed)", GOOD_VOICE, {**GOOD_META, 0x10: 0})
    run("state!=0 (meta+0x8=1)", GOOD_VOICE, {**GOOD_META, 0x8: 1})
    run("gen mismatch (meta+0x14=9)", GOOD_VOICE, {**GOOD_META, 0x14: 9})
    run("voice+0x10=9 (voice gen changed)", {**GOOD_VOICE, 0x10: 9}, GOOD_META)
    run("o0=0 (voice inactive)", {**GOOD_VOICE, 0x0: 0}, GOOD_META)
    run("voice+0x4=0 (meta ptr null)", {**GOOD_VOICE, 0x4: 0}, GOOD_META)
