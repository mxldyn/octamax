#!/usr/bin/env python3
"""
HOT SWAP validation #1 builder (on R11). See tools/patch_hotswap.s.
Triggers a sample RELOAD (FUN_4009083c) from the CHANGE PROJECT gesture, with recorder
slots preserved (hot_unload), to check whether the recorder voice survives a flex reload.

    python3 tools/build.py         # -> out/mainos.bin (R11)
    python3 tools/build_hotswap.py # -> out/mainos_swap.bin
"""
import pathlib, subprocess, sys

BASE = 0x40000400
CAVE_AT = 0x400d7240
R11 = pathlib.Path("out/mainos.bin")
OUT = pathlib.Path("out/mainos_swap.bin")

DETOURS = [(0x40063bf8, "hs_trigger", "4aaf0004661c"),   # RELOAD confirm (CHANGE left stock)
           (0x40096300, "hot_unload", "4fefffd848d7")]


def off(a):
    return a - BASE


def main():
    if not R11.exists():
        sys.exit(f"missing {R11} — run tools/build.py first")
    img = bytearray(R11.read_bytes())
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", "out/hs.o", "tools/patch_hotswap.s"], check=True)
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{CAVE_AT:x}", "-o", "out/hs.elf", "out/hs.o"], capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/hs.elf", "out/hs.bin"], check=True)
    nm = subprocess.run(["m68k-elf-nm", "out/hs.elf"], capture_output=True, text=True).stdout
    sym = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    blob = pathlib.Path("out/hs.bin").read_bytes()
    print(f"swap cave {len(blob)} B @ 0x{CAVE_AT:08x}")
    if any(img[off(CAVE_AT):off(CAVE_AT) + len(blob)]):
        sys.exit("cave not free in R11")
    img[off(CAVE_AT):off(CAVE_AT) + len(blob)] = blob
    for site, s, exp in DETOURS:
        o = off(site)
        if not bytes(img[o:o + len(exp) // 2]).hex().startswith(exp):
            sys.exit(f"detour 0x{site:08x}: {bytes(img[o:o+6]).hex()} want {exp}")
        img[o:o + 6] = b"\x4e\xf9" + sym[s].to_bytes(4, "big")
        print(f"  detour 0x{site:08x} -> {s} 0x{sym[s]:08x}")
    OUT.write_bytes(bytes(img))
    print(f"\n{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
