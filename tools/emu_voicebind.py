#!/usr/bin/env python3
"""emu_voicebind.py -- run the STATIC voice-bind resolver 0x4000f450 in Unicorn for a low slot (idx=1,
A tables) and a high slot (idx=128, B tables), with STATE/SETTINGS/STRIDE4 populated EXACTLY as a
correct load should leave them, and observe whether the resolver BINDS the voice (reaches 0x4000f526)
or bails to the per-voice reset 0x40006820. This isolates the CONSUME side (resolver + our helpers)
from the LOAD side (whether STATE-B actually gets those values on hardware).

Voice-bind gate (from disasm): STATE@16>0 AND STATE@8==0 AND STRIDE4[idx]==STATE@20 -> bind; else reset.

    python3 tools/emu_voicebind.py
"""
import pathlib, sys
from unicorn import *
from unicorn.m68k_const import *

BASE = 0x40000400
IMG = pathlib.Path("out/mainos_persist256.bin").read_bytes()
RESOLVER = 0x4000f450
BAIL     = 0x40006820          # per-voice reset (== silence)
BIND_OK  = 0x4000f526          # falls here when the gen check passes

# table bases (A) + B homes
STATE_A, STATE_STR = 0x46c90a78, 44
SET_A,   SET_STR   = 0x100d5b30, 1096
S42_A              = 0x46c93a24           # STRIDE4#2 (STATIC generation token), stride 4
STATE_B = 0x40ab79e0
SET_B   = 0x40a955e0
S42_B   = 0x40ab91e0
VOICE   = 0x800049d8                       # stride 168
PINGPONG = 0x800000e0
TYPETAB  = 0x80000eb4

def state_ptr(idx): return STATE_B if idx >= 128 else STATE_A + idx*STATE_STR
def set_ptr(idx):   return SET_B   if idx >= 128 else SET_A + idx*SET_STR
def s42_ptr(idx):   return (S42_B) if idx >= 128 else S42_A + idx*4   # B[idx-128]=S42_B for idx=128


def run_one(idx, gen=5):
    mu = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    for a, s in [(0x40000000, 0x2000000), (0x00008000, 0x40000), (0x80000000, 0x20000),
                 (0x10000000, 0x400000), (0x46000000, 0x1000000)]:
        mu.mem_map(a, s)
    mu.mem_write(BASE, IMG)

    # populate the slot's STATE / SETTINGS / STRIDE4 as a correct load would
    st = state_ptr(idx)
    mu.mem_write(st + 8,  (0).to_bytes(4, "big"))          # @8  status = 0  (required)
    mu.mem_write(st + 16, (0x200).to_bytes(4, "big"))      # @16 length/window > 0 (required)
    mu.mem_write(st + 20, (gen).to_bytes(4, "big"))        # @20 generation token
    mu.mem_write(st + 36, (17).to_bytes(4, "big"))         # @36 file handle (nonzero)
    mu.mem_write(s42_ptr(idx), (gen).to_bytes(4, "big"))   # STRIDE4[idx] = gen  (must match @20)

    # voice 0, machine type STATIC (0)
    mu.mem_write(PINGPONG, (0).to_bytes(4, "big"))
    mu.mem_write(TYPETAB, b"\x00" * 8)                     # type byte for (pingpong*8+voice)=0 -> 0=STATIC
    mu.mem_write(VOICE + 12, (0).to_bytes(4, "big"))       # voice@12 channel sub-ptr

    outcome = {"pc_bail": False, "pc_bind": False, "voice4": None, "trace": []}
    def hook(mu, address, size, ud):
        if address == BAIL:  outcome["pc_bail"] = True
        if address == BIND_OK: outcome["pc_bind"] = True
        if 0x4000f4dc <= address <= 0x4000f530:
            d0 = mu.reg_read(UC_M68K_REG_D0); d1 = mu.reg_read(UC_M68K_REG_D1)
            a5 = mu.reg_read(UC_M68K_REG_A5); a0 = mu.reg_read(UC_M68K_REG_A0)
            outcome["trace"].append((address, d0 & 0xffffffff, d1 & 0xffffffff, a5 & 0xffffffff, a0 & 0xffffffff))
    mu.hook_add(UC_HOOK_CODE, hook)

    # stack frame: [ret][voice][idx][arg2]
    sp = 0x00030000
    RET = 0x0000a000
    mu.mem_write(RET, b"\x4e\x75")                          # rts (unused; we stop on RET)
    mu.mem_write(sp + 0,  RET.to_bytes(4, "big"))
    mu.mem_write(sp + 4,  (0).to_bytes(4, "big"))           # arg0 voice=0
    mu.mem_write(sp + 8,  (idx).to_bytes(4, "big"))         # arg1 idx
    mu.mem_write(sp + 12, (0).to_bytes(4, "big"))           # arg2
    mu.reg_write(UC_M68K_REG_A7, sp)

    try:
        mu.emu_start(RESOLVER, RET, count=4000)
    except UcError as e:
        # bail path calls into 0x40006820 which touches unmapped stuff -> that's fine, we detected it
        pass
    outcome["voice4"] = int.from_bytes(mu.mem_read(VOICE + 4, 4), "big")
    outcome["voice8"] = int.from_bytes(mu.mem_read(VOICE + 8, 4), "big")
    return outcome


def main():
    for idx in (1, 128):
        o = run_one(idx)
        verdict = "BIND OK (sounds)" if o["pc_bind"] and not o["pc_bail"] else \
                  "BAIL -> reset (SILENT)" if o["pc_bail"] else "?? (neither marker hit)"
        print(f"idx={idx:3d}  STATE={state_ptr(idx):#010x} SET={set_ptr(idx):#010x} "
              f"S42={s42_ptr(idx):#010x}")
        print(f"          voice@4(STATE)={o['voice4']:#010x} voice@8(SET)={o['voice8']:#010x}  "
              f"bind={o['pc_bind']} bail={o['pc_bail']}  -> {verdict}")
        for (pc, d0, d1, a5, a0) in o["trace"]:
            print(f"            pc={pc:#08x} d0={d0:#010x} d1={d1:#010x} a5={a5:#010x} a0={a0:#010x}")


if __name__ == "__main__":
    main()
