#!/usr/bin/env python3
"""
verify_helpers_b.py — emu-verify the REAL dual-table STATE accessor contract (no flashing).

Assembles tools/patch_state_helpers_b.s, loads the blob into Unicorn, and calls each of the 9
helpers across representative slot indices, asserting the two-sided redirect contract:

    idx 0..128      -> table A (0x46c90a78 + product), incl. the index-128 TEMPLATE at 0x46c92078
    idx 129..255    -> table B (0x46c96000 + (idx-128)*44)   [verified-free window]
    idx >= 256, -1  -> table A (stock behaviour; sentinels/OOR never reach the boot-fresh table B)

    python3 tools/verify_helpers_b.py     # -> ALL PASS / FAILURES
"""
import subprocess, pathlib, sys
from unicorn import *
from unicorn.m68k_const import *

TA, ADJ_B = 0x46c90a78, 0x46c94a00       # table A base; table B: 0x46c96000 - 0x1600
REG = {"sh_d0": UC_M68K_REG_D0, "sh_d1": UC_M68K_REG_D1, "sh_d2": UC_M68K_REG_D2,
       "sh_d4": UC_M68K_REG_D4, "sh_d5": UC_M68K_REG_D5, "sh_a0": UC_M68K_REG_A0,
       "sh_a2": UC_M68K_REG_A2, "sh_a3": UC_M68K_REG_A3, "sh_a5": UC_M68K_REG_A5}


def expect(product):
    p = product & 0xffffffff
    return (TA + p) & 0xffffffff if (p <= 0x1600 or p > 0x2bf4) else (ADJ_B + p) & 0xffffffff


def build():
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", "out/_shb.o",
                    "tools/patch_state_helpers_b.s"], check=True)
    subprocess.run(["m68k-elf-ld", "-Ttext=0x400d7400", "-o", "out/_shb.elf", "out/_shb.o"],
                   capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/_shb.elf", "out/_shb.bin"], check=True)
    nm = subprocess.run(["m68k-elf-nm", "out/_shb.elf"], capture_output=True, text=True).stdout
    sym = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    return pathlib.Path("out/_shb.bin").read_bytes(), sym


def call(blob, sym, helper, product):
    mu = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    mu.mem_map(0x400d7000, 0x1000)
    mu.mem_map(0x00010000, 0x1000)
    mu.mem_write(0x400d7400, blob)
    sp, ret = 0x00010800, 0x00010ffc
    mu.mem_write(sp, ret.to_bytes(4, "big"))
    mu.reg_write(UC_M68K_REG_A7, sp)
    mu.reg_write(REG[helper], product & 0xffffffff)
    mu.emu_start(sym[helper], ret, count=10)
    return mu.reg_read(REG[helper])


def main():
    blob, sym = build()
    tests = {0: "idx0", 44: "idx1", 127 * 44: "idx127", 128 * 44: "idx128-TEMPLATE",
             129 * 44: "idx129", 200 * 44: "idx200", 255 * 44: "idx255",
             256 * 44: "idx256-OOR", 300 * 44: "idx300-OOR", 0xffffffd4: "idx-1-sentinel"}
    bad = 0
    for helper in REG:
        for prod, label in tests.items():
            got = call(blob, sym, helper, prod)
            if got != expect(prod):
                bad += 1
                print(f"  FAIL {helper} {label} prod=0x{prod & 0xffffffff:08x} "
                      f"-> 0x{got:08x} want 0x{expect(prod):08x}")
    for f in ("out/_shb.o", "out/_shb.elf", "out/_shb.bin"):
        pathlib.Path(f).unlink(missing_ok=True)
    print(f"helper blob {len(blob)} B; {'ALL PASS' if bad == 0 else str(bad)+' FAILURES'} "
          f"({len(REG)} helpers x {len(tests)} indices)")
    sys.exit(0 if bad == 0 else 1)


if __name__ == "__main__":
    main()
