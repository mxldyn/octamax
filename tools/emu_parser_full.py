#!/usr/bin/env python3
"""
emu_parser_full.py -- run the FULL STATIC [SAMPLE] parser (0x400866c4) in Unicorn over a small
project.work text, to find WHY a STATIC SLOT=129 block does not populate SET-B on hardware.

Feeds bytes via a getc hook (0x40016564). Lets the pure string helpers (strcmp/atoi/strchr/strlen/
strcpy/strlcpy/sprintf) run natively. Hooks/neutralises the few hardware-ish calls. Instruments key
VAs to log the slot index, the cap gate result, the computed destination (0x460fab50), and the PATH
write for every SLOT= line -- so we can see the exact point the SLOT=129 path diverges from SLOT=057.

    python3 tools/emu_parser_full.py
"""
import pathlib
from unicorn import *
from unicorn.m68k_const import *

BASE = 0x40000400
IMG = bytearray(pathlib.Path("out/mainos_persist256.bin").read_bytes())
import sys as _sys; _sys.path.insert(0, "tools")
import build_dual256 as _bd
SET_A, SET_B, STRIDE = 0x100d5b30, _bd.SET_B, 0x448   # SET_B relocated to reclaimed reserve 0x40a955e0
GETC = 0x40016564
VTBL = 0x46c8241e            # indirect call target in parser setup (0x4008670a)
G_IDX, G_TYPE, G_PTR = 0x400d1668, 0x400d166c, 0x460fab50

TEXT = (b"[SAMPLE]\r\nTYPE=STATIC\r\nSLOT=057\r\nPATH=yok-vox.aif\r\n[/SAMPLE]\r\n"
        b"[SAMPLE]\r\nTYPE=STATIC\r\nSLOT=129\r\nPATH=yok-b.aif\r\n[/SAMPLE]\r\n")

# VAs to trace
WATCH = {
    0x40086910: "store idx",
    0x40086922: "cap #256,d1",
    0x40086930: "blew ERROR (idx>=cap)",
    0x40086934: "cap PASS",
    0x400869ae: "addr-comp start",
    0x400869c2: "bhis NULL (addr bound)",
    0x400869fc: "store dest->0x460fab50",
    0x40086a06: "DRY -> scratch dest",
    0x40086d34: "SLOT ERROR exit",
    0x40086a3c: "PATH: load dest",
    0x40086a60: "PATH write (sprintf ../%s)",
    0x40086a70: "PATH write (strlcpy)",
}


def run(flag):
    mu = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    for a, s in [(0x40000000, 0x2000000), (0x10000000, 0x400000), (0x46000000, 0x1000000),
                 (0x47700000, 0x200000), (0x00008000, 0x40000)]:
        mu.mem_map(a, s)
    mu.mem_write(BASE, bytes(IMG))
    # rts stub for the vtable call (inside the already-mapped stack region)
    RTS = 0x00009000
    mu.mem_write(RTS, b"\x4e\x75")           # rts
    mu.mem_write(VTBL, RTS.to_bytes(4, "big"))

    state = {"pos": 0, "log": []}

    RESET_SLOT = 0x40099148
    def hook_code(mu, address, size, ud):
        if address == RESET_SLOT:                 # hardware reset-slot: skip (emu can't run it)
            sp = mu.reg_read(UC_M68K_REG_A7)
            ret = int.from_bytes(mu.mem_read(sp, 4), "big")
            mu.reg_write(UC_M68K_REG_D0, 0)
            mu.reg_write(UC_M68K_REG_A7, sp + 4)
            mu.reg_write(UC_M68K_REG_PC, ret)
            return
        if address == GETC:
            sp = mu.reg_read(UC_M68K_REG_A7)
            buf = int.from_bytes(mu.mem_read(sp + 8, 4), "big")   # &buf (pea sp@(1471))
            if state["pos"] < len(TEXT):
                mu.mem_write(buf, TEXT[state["pos"]:state["pos"] + 1])
                state["pos"] += 1
                mu.reg_write(UC_M68K_REG_D0, 1)
            else:
                mu.reg_write(UC_M68K_REG_D0, 0)                   # EOF -> parser ends (-29)
            ret = int.from_bytes(mu.mem_read(sp, 4), "big")
            mu.reg_write(UC_M68K_REG_A7, sp + 4)
            mu.reg_write(UC_M68K_REG_PC, ret)
            return
        if address in WATCH:
            idx = int.from_bytes(mu.mem_read(G_IDX, 4), "big")
            typ = int.from_bytes(mu.mem_read(G_TYPE, 4), "big")
            ptr = int.from_bytes(mu.mem_read(G_PTR, 4), "big")
            d0 = mu.reg_read(UC_M68K_REG_D0); d1 = mu.reg_read(UC_M68K_REG_D1)
            state["log"].append((address, WATCH[address], idx, typ, ptr, d0, d1))

    mu.hook_add(UC_HOOK_CODE, hook_code)

    # build the parser stack frame: [retpc][stream][flag]
    sp = 0x00030000
    RET = 0x0000a000
    mu.mem_write(RET, b"\x4e\x75")            # rts landing (unused; we stop at RET)
    stream = 0x0000b000                        # dummy stream ptr (getc hooked, unused)
    mu.mem_write(sp, RET.to_bytes(4, "big"))
    mu.mem_write(sp + 4, stream.to_bytes(4, "big"))
    mu.mem_write(sp + 8, flag.to_bytes(4, "big"))
    mu.reg_write(UC_M68K_REG_A7, sp)
    try:
        mu.emu_start(0x400866c4, RET, count=5_000_000)
    except UcError as e:
        state["log"].append(("ERR", str(e), mu.reg_read(UC_M68K_REG_PC), 0, 0, 0, 0))

    def tag(a):
        if SET_A <= a < SET_A + 256 * STRIDE: return f"SET-A[{(a-SET_A)//STRIDE}]"
        if SET_B <= a < SET_B + 128 * STRIDE: return f"SET-B[{(a-SET_B)//STRIDE}]"
        return f"0x{a:08x}" if a else "NULL"
    print(f"=== parser run, flag={flag} ({'REAL' if flag else 'DRY'}) ===")
    for va, name, idx, typ, ptr, d0, d1 in state["log"]:
        if va == "ERR":
            print(f"  EMU ERROR: {name} pc=0x{idx:08x}"); continue
        print(f"  0x{va:08x} {name:26} idx={idx:<4} TYPE={typ:<3} dest={tag(ptr):12} d0=0x{d0:08x} d1=0x{d1:08x}")
    # final SET-B content: both [0] (idx=128) and [1] (idx=129) path@0
    for i in (0, 1):
        bi = mu.mem_read(SET_B + i * STRIDE, 32)
        asc = ''.join(chr(c) if 32 <= c < 127 else '.' for c in bi)
        print(f"  SET-B[{i}] @0 (idx={128+i}) after parse: {bytes(bi)!r}  ascii='{asc}'")
    # also SET-A[128] (OOB) in case the write mis-lands there
    ba = mu.mem_read(SET_A + 128 * STRIDE, 32)
    asc = ''.join(chr(c) if 32 <= c < 127 else '.' for c in ba)
    print(f"  SET-A[128] @0 (OOB) after parse: {bytes(ba)!r}  ascii='{asc}'")


if __name__ == "__main__":
    run(1)
    print()
    run(0)
