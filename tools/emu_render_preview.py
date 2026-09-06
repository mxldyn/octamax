#!/usr/bin/env python3
"""
emu_render_preview.py -- execute sv_render with the REAL firmware draw functions and dump
the resulting pixels as ASCII, so display layout changes can be iterated without flashing.

The screen surface 0x400bf10a is {w=128, h=64, stride=2 longs/column, plane0=0x46c7e0ea,
plane1=0x46c7ca38}, column-major, 32 pixels per longword. Only POST is stubbed.

    python3 tools/emu_render_preview.py [image] [slice_idx] [pos] [start] [end] [loop]
"""
import pathlib, struct, sys
from unicorn import *
from unicorn.m68k_const import *

IMG_PATH = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "out/mainos_all.bin")
BASE = 0x40000400
F_FLAG, VIEW, MODAL = 0x800000dc, 0x460d16f0, 0x460d1aec
CURTRACK, VOICES = 0x100b14cc, 0x800049d8
POST = 0x40000c3c
RENDER_SITE, ARM_EXIT = 0x40044cf0, 0x400453e2
PLANE0 = 0x46c7e0ea

args = [int(a, 0) for a in sys.argv[2:]] or []
slice_idx = args[0] if len(args) > 0 else 4      # display: 5
pos       = args[1] if len(args) > 1 else 1600
start     = args[2] if len(args) > 2 else 1000
end       = args[3] if len(args) > 3 else 2000
loop      = args[4] if len(args) > 4 else 1750

uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
uc.mem_map(0x40000000, 0x200000)
uc.mem_write(BASE, IMG_PATH.read_bytes())
uc.mem_map(0x80000000, 0x10000)
uc.mem_map(0x10000000, 0x100000)
uc.mem_map(0x46000000, 0x1100000)
uc.mem_map(0x41000000, 0x20000)
uc.mem_write(POST, b"\x4e\x75")

def w32(a, v): uc.mem_write(a, struct.pack(">I", v & 0xFFFFFFFF))
def w8(a, v): uc.mem_write(a, bytes([v & 0xFF]))

w32(F_FLAG, 1); w32(VIEW, 3); w32(MODAL, 0)
track = 2
w8(CURTRACK, track)
v = VOICES + track * 0xA8
w8(v + 0, 0xFF)
S = 0x100d5b30
w32(v + 8, S)
w8(v + 32, slice_idx)
w32(v + 68, pos)
e = S + 300 + (slice_idx + 1) * 12
w32(e + 0, start); w32(e + 4, end); w32(e + 8, loop)

done = {"hit": False}
def stop(uc_, addr, size, user):
    if addr == ARM_EXIT:
        done["hit"] = True
        uc_.emu_stop()
uc.hook_add(UC_HOOK_CODE, stop)
uc.reg_write(UC_M68K_REG_A7, 0x41010000 - 12)
try:
    uc.emu_start(RENDER_SITE, 0, count=5_000_000)
except UcError as ex:
    print(f"UcError: {ex} at pc={uc.reg_read(UC_M68K_REG_PC):#x}")
if not done["hit"]:
    sys.exit("never reached ARM_EXIT")

plane = uc.mem_read(PLANE0, 128 * 2 * 4)
def px(x, y):
    lw = struct.unpack(">I", plane[(x * 2 + (y >> 5)) * 4:(x * 2 + (y >> 5)) * 4 + 4])[0]
    return (lw >> (y & 31)) & 1

X0, X1, Y0, Y1 = 55, 122, 6, 28
print(f"   {''.join(str(x % 10) for x in range(X0, X1 + 1))}")
for y in range(Y0, Y1 + 1):
    row = "".join("#" if px(x, y) else "." for x in range(X0, X1 + 1))
    print(f"{y:2d} {row}")
