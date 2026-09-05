#!/usr/bin/env python3
"""
emu_load_real.py -- run the FULL STATIC [SAMPLE] parser over the REAL project.work, with reset-slot
0x40099148 ACTUALLY EXECUTING (not skipped), to reproduce the hardware behaviour where STATIC SLOT=129
leaves SETTINGS-B[0] empty. reset-slot uses privileged movew %sr ops + DSP/IO subcalls that Unicorn
m68k cannot run -> we hook those (SR ops -> skip; subcalls -> stub return 0) so the rest of reset-slot's
body executes with its migrated base-add helpers. After the parse we dump SETTINGS-B[0][0:64] (slot 129
storage) to see whether the PATH survives.

    python3 tools/emu_load_real.py [path-to-project.work]
"""
import sys, pathlib
from unicorn import *
from unicorn.m68k_const import *

BASE = 0x40000400
IMG = bytearray(pathlib.Path("out/mainos_persist256.bin").read_bytes())
SET_A, SET_B, STRIDE = 0x100d5b30, 0x40a955e0, 0x448
GETC = 0x40016564
VTBL = 0x46c8241e
G_IDX, G_TYPE, G_PTR = 0x400d1668, 0x400d166c, 0x460fab50
RESET_SLOT = 0x40099148

if len(sys.argv) > 1:
    TEXT = pathlib.Path(sys.argv[1]).read_bytes()
else:
    # minimal: one low STATIC slot + the SLOT=129 block (same as emu_parser_full), isolates reset-slot
    TEXT = (b"[SAMPLE]\r\nTYPE=STATIC\r\nSLOT=057\r\nPATH=yok-vox.aif\r\n[/SAMPLE]\r\n"
            b"[SAMPLE]\r\nTYPE=STATIC\r\nSLOT=129\r\nPATH=yok-b.aif\r\n[/SAMPLE]\r\n")

# reset-slot privileged SR ops: (addr, size, dest_reg_to_set_or_None)
SR_OPS = {
    0x400992cc: (2, UC_M68K_REG_D2),   # movew %sr,%d2
    0x400992ce: (4, None),             # movew #imm,%sr
    0x400992e8: (2, None),             # movew %d2,%sr
    0x40099324: (2, UC_M68K_REG_D1),   # movew %sr,%d1
    0x40099326: (4, None),             # movew #imm,%sr
    0x40099332: (2, None),             # movew %d1,%sr
}
# reset-slot hardware/DSP subcalls -> stub (return d0=0, pop retaddr). Caller cleans args.
# 0x400204a8 = strrchr(path,'/') (pure) -> run NATIVELY (stubbing it to 0 falsely triggers the clrb).
STUB_CALLS = {0x40020ad8, 0x40099090, 0x40004f9c}

WATCH = {0x40086940: "reset-slot CALL", 0x400869fc: "store dest", 0x40086a60: "PATH sprintf",
         0x40086a70: "PATH strlcpy", 0x40099148: "reset-slot ENTRY", 0x40099362: "reset-slot OK",
         0x40099366: "reset-slot ERR(-1)"}


def run():
    mu = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    for a, s in [(0x40000000, 0x2000000), (0x10000000, 0x400000), (0x46000000, 0x1000000),
                 (0x47700000, 0x200000), (0x00008000, 0x40000)]:
        mu.mem_map(a, s)
    mu.mem_write(BASE, bytes(IMG))
    RTS = 0x00009000
    mu.mem_write(RTS, b"\x4e\x75")
    mu.mem_write(VTBL, RTS.to_bytes(4, "big"))

    st = {"pos": 0, "log": [], "rs_idx": None}

    def hook(mu, address, size, ud):
        # GENERIC privileged SR-op skipper (Unicorn m68k faults on any %sr access)
        opw = int.from_bytes(mu.mem_read(address, 2), "big")
        if 0x40c0 <= opw <= 0x40c7:                       # move %sr,%dN  -> dN=0x2700, skip 2
            mu.reg_write(UC_M68K_REG_D0 + (opw & 7), 0x2700)
            mu.reg_write(UC_M68K_REG_PC, address + 2); return
        if 0x46c0 <= opw <= 0x46c7:                       # move %dN,%sr  -> nop, skip 2
            mu.reg_write(UC_M68K_REG_PC, address + 2); return
        if opw == 0x46fc:                                 # move #imm,%sr -> nop, skip 4
            mu.reg_write(UC_M68K_REG_PC, address + 4); return
        if opw in (0x007c, 0x027c, 0x0a7c):               # ori/andi/eori #imm,%sr -> skip 4
            mu.reg_write(UC_M68K_REG_PC, address + 4); return
        if opw == 0x4e72:                                 # stop #imm -> skip 4
            mu.reg_write(UC_M68K_REG_PC, address + 4); return
        if address in SR_OPS:
            sz, reg = SR_OPS[address]
            if reg is not None:
                mu.reg_write(reg, 0x2700)
            mu.reg_write(UC_M68K_REG_PC, address + sz)
            return
        if address in STUB_CALLS:
            sp = mu.reg_read(UC_M68K_REG_A7)
            ret = int.from_bytes(mu.mem_read(sp, 4), "big")
            mu.reg_write(UC_M68K_REG_D0, 0)
            mu.reg_write(UC_M68K_REG_A7, sp + 4)
            mu.reg_write(UC_M68K_REG_PC, ret)
            return
        if address == GETC:
            sp = mu.reg_read(UC_M68K_REG_A7)
            buf = int.from_bytes(mu.mem_read(sp + 8, 4), "big")
            if st["pos"] < len(TEXT):
                mu.mem_write(buf, TEXT[st["pos"]:st["pos"] + 1])
                st["pos"] += 1
                mu.reg_write(UC_M68K_REG_D0, 1)
            else:
                mu.reg_write(UC_M68K_REG_D0, 0)
            ret = int.from_bytes(mu.mem_read(sp, 4), "big")
            mu.reg_write(UC_M68K_REG_A7, sp + 4)
            mu.reg_write(UC_M68K_REG_PC, ret)
            return
        if address in WATCH:
            idx = int.from_bytes(mu.mem_read(G_IDX, 4), "big")
            typ = int.from_bytes(mu.mem_read(G_TYPE, 4), "big")
            ptr = int.from_bytes(mu.mem_read(G_PTR, 4), "big")
            # only log around the high slots to keep it readable
            if address == RESET_SLOT:
                st["rs_idx"] = idx
            if idx >= 126 or address in (0x40099362, 0x40099366):
                st["log"].append((address, WATCH[address], idx, typ, ptr))

    mu.hook_add(UC_HOOK_CODE, hook)

    def wr(mu, access, address, size, value, ud):
        if SET_B <= address < SET_B + 8:
            pc = mu.reg_read(UC_M68K_REG_PC)
            st["log"].append(("WR", f"[0x{address:08x}]={value:#x} sz{size}", pc, 0, 0))
    mu.hook_add(UC_HOOK_MEM_WRITE, wr, begin=SET_B, end=SET_B + 8)

    sp = 0x00030000
    RET = 0x0000a000
    mu.mem_write(RET, b"\x4e\x75")
    mu.mem_write(sp, RET.to_bytes(4, "big"))
    mu.mem_write(sp + 4, (0x0000b000).to_bytes(4, "big"))
    mu.mem_write(sp + 8, (1).to_bytes(4, "big"))       # flag=1 (REAL)
    mu.reg_write(UC_M68K_REG_A7, sp)
    try:
        mu.emu_start(0x400866c4, RET, count=50_000_000)
    except UcError as e:
        st["log"].append(("ERR", str(e), mu.reg_read(UC_M68K_REG_PC), 0, 0))

    def tag(a):
        if SET_A <= a < SET_A + 256 * STRIDE: return f"SET-A[{(a-SET_A)//STRIDE}]"
        if SET_B <= a < SET_B + 128 * STRIDE: return f"SET-B[{(a-SET_B)//STRIDE}]"
        return f"0x{a:08x}" if a else "NULL"

    print(f"=== REAL parser + reset-slot RUNNING, text={len(TEXT)}B ===")
    for e in st["log"]:
        if e[0] == "ERR":
            print(f"  EMU ERROR: {e[1]} pc=0x{e[2]:08x}"); continue
        if e[0] == "WR":
            print(f"  WRITE {e[1]:30} by PC=0x{e[2]:08x}"); continue
        va, name, idx, typ, ptr = e
        print(f"  0x{va:08x} {name:18} idx={idx:<4} TYPE={typ} dest={tag(ptr)}")
    b0 = bytes(mu.mem_read(SET_B, 64))
    print(f"\n  SETTINGS-B[0] (slot129) [0:64]: {b0}")
    z = b0.find(b'\x00')
    print(f"  SETTINGS-B[0] path: {b0[:z if z>=0 else 64]!r}  {'<== POPULATED' if b0[0] else '<== EMPTY (reproduces HW!)'}")


if __name__ == "__main__":
    run()
