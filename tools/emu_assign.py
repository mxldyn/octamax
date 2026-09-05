#!/usr/bin/env python3
"""emu_assign.py -- emulate ui_apply 0x40079428 (the YES-commit that assigns the selected sample slot to
the current track's STATIC machine) for idx=128, SEEDED WITH THE REAL STATE-B[0] measured on hardware
(P19 probe: @8=0, @16=0x1090628, @20=7, @36=89). This tests, OFFLINE, whether the assign logic writes the
selected slot (128) into the track's per-part machine slot byte, or bails on some branch -- answering
"does the assign actually commit slot 129 to the track" without another flash.

Seeds the UI globals: 0x46c8d19c=selected slot, 0x46c8d1a0=machine type(0=STATIC), 0x100b14cc=track,
0x100b14cf=pattern. Stubs the two non-slot subcalls (0x40027e00, 0x400972fc). Traces the gate branch
(0x40079506) and the slot-byte writes (0x400795c0 = moveb d1,a0@ ; 0x400795c8 = moveb d1,a1@(0,a3:l)).

    python3 tools/emu_assign.py
"""
import pathlib
from unicorn import *
from unicorn.m68k_const import *

BASE = 0x40000400
IMG = pathlib.Path("out/mainos_persist256.bin").read_bytes()
UIAPPLY = 0x40079428
STATE_B0 = 0x40ab79e0
SET_B0 = 0x40a955e0
# real measured STATE-B[0]
S_AT8, S_AT16, S_AT20, S_AT36 = 0, 0x01090628, 7, 89
SEL_SLOT = 0x46c8d19c
SEL_TYPE = 0x46c8d1a0
G_TRACK = 0x100b14cc
G_PAT   = 0x100b14cf
FLEXFLAG = 0x46105408
PARTTBL = 0x46c82456
STUBS = {0x40027e00, 0x400972fc, 0x40001f18, 0x4004d780, 0x4004d948, 0x4009da20, 0x40021d94, 0x40083bc0}


def run(sel_slot):
    mu = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    for a, s in [(0x40000000, 0x2000000), (0x00008000, 0x40000), (0x80000000, 0x20000),
                 (0x10000000, 0x800000), (0x46000000, 0x2000000)]:
        mu.mem_map(a, s)
    mu.mem_write(BASE, IMG)

    def wl(a, v): mu.mem_write(a, v.to_bytes(4, "big"))
    def wb(a, v): mu.mem_write(a, bytes([v]))
    wl(SEL_SLOT, sel_slot)
    wb(SEL_TYPE, 0)                    # STATIC
    wb(G_TRACK, 0)                     # track 0
    wb(G_PAT, 0)                       # pattern 0
    wl(FLEXFLAG, 0)
    wl(PARTTBL, 0x47000000)            # *0x46c82456 = ptr to per-part table (scratch, in mapped 0x46.. region)
    # STATE-B[0] (measured)
    wl(STATE_B0 + 8, S_AT8); wl(STATE_B0 + 16, S_AT16); wl(STATE_B0 + 20, S_AT20); wl(STATE_B0 + 36, S_AT36)
    # SETTINGS-B[0] path non-empty
    mu.mem_write(SET_B0, b"yok-vox.aif\x00")

    log = {"gate": None, "wrote": [], "reached_write": False, "end": None}

    def hook(mu, address, size, ud):
        if address in STUBS:
            sp = mu.reg_read(UC_M68K_REG_A7)
            ret = int.from_bytes(mu.mem_read(sp, 4), "big")
            mu.reg_write(UC_M68K_REG_D0, 0)
            mu.reg_write(UC_M68K_REG_A7, sp + 4)
            mu.reg_write(UC_M68K_REG_PC, ret)
            return
        if address == 0x40079506:      # bnew 0x40079684 (gate: STATE@8 != 0 -> reject)
            d0 = mu.reg_read(UC_M68K_REG_D0)
            log["gate"] = d0 & 0xffffffff
        if address == 0x400795c0:      # moveb d1,a0@  (write slot to per-part byte)
            log["reached_write"] = True
            a0 = mu.reg_read(UC_M68K_REG_A0); d1 = mu.reg_read(UC_M68K_REG_D1)
            log["wrote"].append((a0 & 0xffffffff, d1 & 0xff))
        if address in (0x40079672, 0x40079684):
            log["end"] = ("SKIP/branch", hex(address))

    mu.hook_add(UC_HOOK_CODE, hook)

    def fault(mu, access, address, size, value, ud):
        pc = mu.reg_read(UC_M68K_REG_PC)
        log["fault"] = (hex(pc), hex(address), access)
        return False
    mu.hook_add(UC_HOOK_MEM_READ_UNMAPPED | UC_HOOK_MEM_WRITE_UNMAPPED, fault)

    sp = 0x00030000
    RET = 0x0000a000
    mu.mem_write(RET, b"\x4e\x75")
    mu.mem_write(sp, RET.to_bytes(4, "big"))
    mu.reg_write(UC_M68K_REG_A7, sp)
    try:
        mu.emu_start(UIAPPLY, RET, count=20000)
    except UcError as e:
        log["err"] = str(e)
    # read the per-part slot byte the write targeted
    return log


def main():
    for sel in (50, 128):
        L = run(sel)
        print(f"=== assign selected slot idx={sel} (UI {sel+1}) ===")
        print(f"  gate STATE@8 read = {L['gate']}  (0 => gate PASSES, proceeds to write)")
        if L["reached_write"]:
            for a0, v in L["wrote"]:
                print(f"  WROTE slot byte = {v} to per-part 0x{a0:08x}  {'<-- correct!' if v==sel else '** WRONG **'}")
        else:
            print(f"  did NOT reach the slot write; branch/end = {L.get('end')}  err={L.get('err')}")
        print()


if __name__ == "__main__":
    main()
