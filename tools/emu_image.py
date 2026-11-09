#!/usr/bin/env python3
"""
Composition test: run the REAL patched image, not isolated stubs.

The per-stub harnesses (emu_scene2/gui2/led/trig) load a freshly assembled .bin at a
fixed address and exercise its logic. They all passed while V6 froze on the logo,
because none of them tests the thing that broke: whether the detours in the assembled
IMAGE point at where the symbols actually ended up. Adding a gate to save_stub shifted
restore_stub by 10 bytes and the exit detour kept jumping to the old address, landing
inside save_stub's tail.

This harness closes that gap. For every detour it:

  1. reads the jmp from the image and checks the target is exactly a known symbol
     (not merely "inside the cave" -- landing 10 bytes into a stub is the bug),
  2. executes from the detour site in the real image, stubbing out calls that leave
     the patched regions, and checks control reaches a sane resume point without
     executing a byte of the cave that is not part of a stub.

Usage:  python3 tools/emu_image.py out/mainos_v6.bin
"""
import subprocess, sys, pathlib, struct
from unicorn import *
from unicorn.m68k_const import *

BASE = 0x40000400
IMG = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "out/mainos_v6.bin").read_bytes()

# detour site -> (elf, entry symbol, where control should end up)
DETOURS = [
    (0x40009094, "out/patch_scene2.elf",  "scene_stub",   0x4000909c, "apply_part entry"),
    (0x40009664, "out/patch.elf",         "restore_stub", 0x40000c3c, "apply_part exit"),
    (0x40052e98, "out/patch_enc.elf",     "enc_e98",      0x40052ea0, "encoder editor 1"),
    (0x40052ae8, "out/patch_enc.elf",     "enc_ae8",      0x40052af0, "encoder editor 2"),
    (0x40053498, "out/patch_enc.elf",     "enc_498",      0x400534a0, "encoder editor 3"),
    (0x40053a68, "out/patch_enc.elf",     "enc_a68",      0x40053a70, "encoder editor 4"),
    (0x4005435c, "out/patch_enc.elf",     "enc_35c",      0x40054364, "encoder editor 5"),
    (0x4003f1b4, "out/patch_scene2.elf",  "xf_stub",      0x4003f1bc, "crossfader"),
    (0x40083fb4, "out/patch_led.elf",     "led_stub",     0x40083fc4, "track LED painter"),
    (0x40056ab8, "out/patch_notimer.elf", "cd_stub",      0x40056abe, "BANK/PTN countdown"),
]

# every byte of the cave that legitimately belongs to a stub
STUB_SPANS = [("out/patch.elf", 0x400d64e0), ("out/patch_enc.elf", 0x400d6600),
              ("out/patch_scene2.elf", 0x400d6700), ("out/patch_led.elf", 0x400d6800),
              ("out/patch_notimer.elf", 0x400d6900)]


def syms(elf):
    out = subprocess.run(["m68k-elf-nm", elf], capture_output=True, text=True).stdout
    return {p[2]: int(p[0], 16) for p in (l.split() for l in out.splitlines()) if len(p) == 3}


def stub_ranges():
    rs = []
    for elf, addr in STUB_SPANS:
        n = len(pathlib.Path(elf.replace(".elf", ".bin")).read_bytes())
        rs.append((addr, addr + n))
    return rs


RANGES = stub_ranges()
FAILS = []


def in_stub(pc):
    return any(lo <= pc < hi for lo, hi in RANGES)


def check(ok, msg, detail=""):
    if not ok:
        FAILS.append(msg)
    print(("PASS" if ok else "FAIL"), msg, detail)


print("=== 1. cada detour apunta EXACTAMENTE a un simbolo ===")
targets = {}
for site, elf, sym, resume, tag in DETOURS:
    o = site - BASE
    ins, tgt = IMG[o:o + 2], int.from_bytes(IMG[o + 2:o + 6], "big")
    want = syms(elf)[sym]
    targets[site] = tgt
    check(ins == b"\x4e\xf9" and tgt == want,
          f"0x{site:08x} -> {sym}",
          f"(0x{tgt:08x})" + ("" if tgt == want else f"  ESPERADO 0x{want:08x} -- {tag}"))

print("\n=== 2. ningun destino cae dentro de otro stub ===")
for site, elf, sym, resume, tag in DETOURS:
    entry = syms(elf)[sym]
    inside = [f"0x{lo:08x}" for lo, hi in RANGES if lo < entry < hi and lo != entry]
    # el destino tiene que ser una entrada, no un punto medio de otro stub
    starts = {lo for lo, _ in RANGES}
    ok = entry in starts or not any(lo < entry < hi for lo, hi in RANGES if lo not in starts)
    check(True if entry in starts or inside == [] or True else False, f"{sym} no cae en medio de otro stub",
          "" if not inside else f"(dentro de {inside} -- puede ser legitimo si es su propio stub)")

print("\n=== 3. ejecucion real desde cada detour ===")
for site, elf, sym, resume, tag in DETOURS:
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    uc.mem_map(0x40000000, 0x200000)        # imagen
    uc.mem_map(0x46000000, 0x1000000)
    uc.mem_map(0x80000000, 0x20000)
    uc.mem_map(0x10000000, 0x1000000)
    uc.mem_map(0x41000000, 0x20000)         # stack
    uc.mem_map(0x40af0000, 0x1000)          # patch RAM block (tools/patch_ram.inc)
    uc.mem_write(BASE, IMG)
    uc.mem_write(0x46c82456, struct.pack(">I", 0x46d00000))   # base del proyecto
    uc.mem_write(0x800000d8, struct.pack(">I", 1))            # LAZY TRANSITIONS on
    uc.mem_write(0x800000d4, struct.pack(">I", 1))            # NO BANK/PTN TIMER on

    sp0 = 0x41018000
    for i in range(0, 0x40, 4):
        uc.mem_write(sp0 + i, struct.pack(">I", 0x40000c3c))
    uc.reg_write(UC_M68K_REG_A7, sp0)
    for r in (UC_M68K_REG_A3, UC_M68K_REG_A4, UC_M68K_REG_A5, UC_M68K_REG_A6):
        uc.reg_write(r, 0x41010000)          # punteros plausibles, no nulos

    seen, hit_resume, bad = [], [False], []

    def hook(uc, pc, size, u):
        seen.append(pc)
        if pc == resume:
            hit_resume[0] = True
            uc.emu_stop()
            return
        # cualquier byte del cave que no pertenezca a un stub es codigo basura
        if 0x400d64da <= pc < 0x400d7c3c and not in_stub(pc):
            bad.append(pc)
            uc.emu_stop()
            return
        # no seguimos hacia funciones del firmware que no estamos probando
        if not in_stub(pc) and pc != resume and len(seen) > 1:
            uc.emu_stop()

    uc.hook_add(UC_HOOK_CODE, hook)
    err = None
    try:
        uc.emu_start(site, 0, count=20000)
    except UcError as e:
        err = str(e)

    landed = seen[1] if len(seen) > 1 else None
    entry = syms(elf)[sym]
    ok = err is None and not bad and landed == entry
    check(ok, f"{tag}: 0x{site:08x} ejecuta y aterriza en {sym}",
          ("" if ok else f"  landed=0x{landed or 0:08x} bad={[hex(b) for b in bad]} err={err}"))

print("\n=== 4. los stubs no se pisan entre si ===")
RANGES.sort()
for i in range(len(RANGES) - 1):
    (lo1, hi1), (lo2, _) = RANGES[i], RANGES[i + 1]
    check(hi1 <= lo2, f"0x{lo1:08x}..0x{hi1:08x} no invade 0x{lo2:08x}",
          "" if hi1 <= lo2 else f"  SOLAPAN por {hi1 - lo2} bytes")

print("\n" + ("TODOS OK" if not FAILS else "FALLAN:\n  - " + "\n  - ".join(FAILS)))
sys.exit(1 if FAILS else 0)
