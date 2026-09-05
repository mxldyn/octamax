#!/usr/bin/env python3
# Validate the ARP key-scale extension caves (decode_cave + lookup_cave) in a
# ColdFire emulator against a reference model, for every scale value and note.
#
#   decode_cave: scale byte -> local_44 = 12*quality + (12-root)   (0 for OFF)
#   lookup_cave: D1=idx, D0=note -> note + UT[quality*12 + idx], stored at (A2)
#
# The original firmware between them computes idx = (note+local_44) % 12, which
# we reproduce here so the two halves are tested exactly as they compose live.
import pathlib, struct
from unicorn import *
from unicorn.m68k_const import *

import subprocess
# The blob's load address comes from the ELF, not a constant: tools/build_all.py relocates the arp
# cave to fit alongside the maxolydian and dual-256 stubs, and this gate must follow it.
BLOB = pathlib.Path("out/patch_arp.bin").read_bytes()
_hdr = subprocess.run(["m68k-elf-objdump", "-h", "out/patch_arp.elf"], capture_output=True, text=True).stdout
ARP_AT = next(int(l.split()[3], 16) for l in _hdr.splitlines() if " .text " in l)
_nm = subprocess.run(["m68k-elf-nm", "out/patch_arp.elf"], capture_output=True, text=True).stdout
_sym = {p[2]: int(p[0], 16) for p in (l.split() for l in _nm.splitlines()) if len(p) == 3}
DECODE, LOOKUP = _sym["decode_cave"], _sym["lookup_cave"]
RET1, RET2 = 0x4009fb00, 0x4009fb80          # jmp targets the caves return to

QUAL = ["MAJ","MIN","DOR","PHR","LYD","MIX","LOC","BLU","PHD","MEL","OCT","HIR"]
SCALES = {"MAJ":[0,2,4,5,7,9,11],"MIN":[0,2,3,5,7,8,10],"DOR":[0,2,3,5,7,9,10],
          "PHR":[0,1,3,5,7,8,10],"LYD":[0,2,4,6,7,9,11],"MIX":[0,2,4,5,7,9,10],
          "LOC":[0,1,3,5,6,8,10],"BLU":[0,3,5,6,7,10],"PHD":[0,1,4,5,7,8,10],
          "MEL":[0,2,3,5,7,9,11],"OCT":[0,2,3,5,6,8,9,11],"HIR":[0,2,3,7,8]}
NEAREST = {"BLU","OCT","HIR"}

def snap(p, q):
    s = set(SCALES[q])
    if p in s: return 0
    if q in NEAREST:
        for d in range(1,12):
            if (p-d)%12 in s: return -d
            if (p+d)%12 in s: return d
        return 0
    for d in range(1,12):
        if (p-d)%12 in s: return -d
    return 0

FRAME = 0x41010000          # A6
STRUCT = 0x41000100         # A0 (scale byte at +0x31)
BUF = 0x41000200            # A2 (note buffer)

def mkuc():
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    uc.mem_map(0x40000000, 0x400000)
    uc.mem_map(0x41000000, 0x40000)
    uc.mem_write(ARP_AT, BLOB)
    def stop(uc, addr, size, u):
        if addr in (RET1, RET2): uc.emu_stop()
    uc.hook_add(UC_HOOK_CODE, stop)
    uc.reg_write(UC_M68K_REG_A7, 0x41030000)
    return uc

def run_decode(uc, scale):
    uc.mem_write(STRUCT + 0x31, bytes([scale & 0xff]))
    uc.reg_write(UC_M68K_REG_A0, STRUCT)
    uc.reg_write(UC_M68K_REG_A6, FRAME)
    uc.mem_write(FRAME - 0x40, b"\xde\xad\xbe\xef")
    uc.emu_start(DECODE, 0, count=200)
    return struct.unpack(">i", uc.mem_read(FRAME - 0x40, 4))[0]

def run_lookup(uc, local_44, note, idx):
    uc.reg_write(UC_M68K_REG_A6, FRAME)
    uc.mem_write(FRAME - 0x40, struct.pack(">i", local_44))
    uc.reg_write(UC_M68K_REG_D0, note & 0xffffffff)
    uc.reg_write(UC_M68K_REG_D1, idx & 0xffffffff)
    uc.reg_write(UC_M68K_REG_A2, BUF)
    uc.mem_write(BUF, bytes([note & 0xff]))
    uc.emu_start(LOOKUP, 0, count=200)
    return struct.unpack(">b", uc.mem_read(BUF, 1))[0]   # signed byte result

def main():
    uc = mkuc()
    errs = 0
    # --- decode: local_44 for every scale value ---
    for v in range(0, 145):
        got = run_decode(uc, v)
        if v == 0:
            exp = 0
        else:
            r, q = (v - 1) // 12, (v - 1) % 12
            exp = 12 * q + (12 - r)
        if got != exp:
            print(f"DECODE FAIL v={v}: got local_44={got}, exp={exp}"); errs += 1
    print(f"decode: checked 145 scale values, {errs} errors")

    # --- lookup: snapped note for every scale x note, vs reference ---
    lerr = 0; checked = 0
    for v in range(1, 145):
        r, q = (v - 1) // 12, (v - 1) % 12
        local_44 = 12 * q + (12 - r)
        for note in range(0, 128):
            idx = (note + local_44) % 12
            got = run_lookup(uc, local_44, note, idx)
            p = (note - r) % 12
            raw = note + snap(p, QUAL[q])
            exp = ((raw + 128) & 0xff) - 128     # stored as a signed byte; if <0 the
            checked += 1                          # firmware drops the note downstream
            if got != exp:
                if lerr < 12:
                    print(f"LOOKUP FAIL v={v} {QUAL[q]} root={r} note={note}: got={got} exp={exp}")
                lerr += 1
    print(f"lookup: checked {checked} (scale,note) pairs, {lerr} errors")

    # --- MAJ/MIN must reproduce the stock snap table exactly ---
    stock = [0,-1,0,-1,0,0,-1,0,-1,0,-1,0]
    smaj = ferr = 0
    for note in range(0, 128):
        # stock major, root C (v=1): local_44 = 12
        idx = (note + 12) % 12
        got = run_lookup(uc, 12, note, idx)
        exp = note + stock[(note) % 12]
        if got != exp: ferr += 1
    print(f"stock MAJ (C, v=1) parity: {ferr} mismatches over 128 notes")

    print("\nRESULT:", "ALL PASS" if (errs + lerr + ferr) == 0 else f"FAILURES ({errs+lerr+ferr})")

if __name__ == "__main__":
    main()
