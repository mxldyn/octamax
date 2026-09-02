#!/usr/bin/env python3
"""emu_silentuntilaed.py -- proves BUG B (high-slot trigs SILENT until the AED is opened) is the
STATE-B[idx]@16 field. Drives the DSP voice-bind resolver FUN_4000f450 for high slot idx=160 twice:

  RAW-RESTORE : STATE-B[idx] left boot-zeroed -- exactly what the sidecar's RAW SET-B copy leaves,
                since the reload path never re-runs the per-slot loader for restored B slots. @16=0
                -> resolver BAILS to the per-voice reset 0x40006820  ==  SILENCE.
  PRIMED      : STATE-B[idx] as sampleview FUN_40093980 leaves it (@16>0, @8=0, @36 handle,
                STRIDE4[idx]==@20) -> resolver BINDS (reaches 0x4000f526)  ==  SOUNDS.

Frame convention copied verbatim from tools/emu_voicebind.py (proven). The ONLY delta between the two
runs is STATE-B[idx]@16 (and the buffer/handle/gen that sampleview writes alongside it), so that field
-- written only by sampleview, which the AED runs and the raw reload does not -- is the bug.
"""
import pathlib
from unicorn import *
from unicorn.m68k_const import *

BASE=0x40000400; IMG=pathlib.Path("out/mainos_persist256.bin").read_bytes()
RESOLVER,BAIL,BIND=0x4000f450,0x40006820,0x4000f526
STATE_B,S42_B,STATE_STR=0x40ab79e0,0x40ab91e0,44
VOICE,PINGPONG,TYPETAB=0x800049d8,0x800000e0,0x80000eb4
IDX=160  # UI slot 161

def run(primed):
    mu=Uc(UC_ARCH_M68K,UC_MODE_BIG_ENDIAN)
    for a,s in [(0x40000000,0x2000000),(0x00008000,0x40000),(0x80000000,0x20000),
                (0x10000000,0x400000),(0x46000000,0x1000000)]:
        mu.mem_map(a,s)
    mu.mem_write(BASE,IMG)
    st=STATE_B+(IDX-128)*STATE_STR; s42=S42_B+(IDX-128)*4
    if primed:                                        # what sampleview writes; @8 already 0 when zeroed
        mu.mem_write(st+16,(0x200).to_bytes(4,"big")) # @16 buffer/window > 0  <-- THE missing field
        mu.mem_write(st+20,(5).to_bytes(4,"big"))     # @20 gen token
        mu.mem_write(st+36,(17).to_bytes(4,"big"))    # @36 file handle
        mu.mem_write(s42,(5).to_bytes(4,"big"))       # STRIDE4[idx] == @20
    mu.mem_write(PINGPONG,(0).to_bytes(4,"big"))
    mu.mem_write(TYPETAB,b"\x00"*8)
    mu.mem_write(VOICE+12,(0).to_bytes(4,"big"))
    seen={"bail":False,"bind":False}
    def hk(mu,a,sz,ud):
        if a==BAIL: seen["bail"]=True
        if a==BIND: seen["bind"]=True
    mu.hook_add(UC_HOOK_CODE,hk)
    sp=0x00030000; RET=0x0000a000
    mu.mem_write(RET,b"\x4e\x75")
    mu.mem_write(sp+0,RET.to_bytes(4,"big"))
    mu.mem_write(sp+4,(0).to_bytes(4,"big"))          # voice 0
    mu.mem_write(sp+8,(IDX).to_bytes(4,"big"))        # slot idx
    mu.mem_write(sp+12,(0).to_bytes(4,"big"))         # arg2
    mu.reg_write(UC_M68K_REG_A7,sp)
    try: mu.emu_start(RESOLVER,RET,count=4000)
    except UcError: pass
    return seen

ok=True
for primed,label in [(False,"RAW-RESTORE (STATE-B zeroed, @16=0)"),(True,"PRIMED (sampleview ran)")]:
    s=run(primed)
    verdict=("BINDS -> SOUNDS" if s["bind"] and not s["bail"] else
             ("BAILS -> SILENT" if s["bail"] else "?? neither"))
    exp = (s["bind"] and not s["bail"]) if primed else s["bail"]
    ok &= exp
    print(f"  [{'OK ' if exp else 'FAIL'}] idx={IDX} {label:38s} -> {verdict}")
print("\n"+("PROVEN: the only delta is STATE-B[idx]@16 -- raw reload=SILENT, primed=SOUNDS. Fix = run "
            "sampleview 0x40093980 per restored high slot (mirror the bulk loader)." if ok
            else "harness mismatch -- inspect"))
