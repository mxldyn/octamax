#!/usr/bin/env python3
"""
DIAG #2 (MAXODIAG) — spare recorder/pickup voices from the per-track voice-stop.

Built from STOCK. Changes:
  1. cave @0x400d7000 (patch_poolswap_diag2.s): ps_change + ps_stop + g_swap.
  2. detour FUN_40063e28 -> ps_change (arm g_swap + skip teardown + open picker).
  3. detour FUN_40006820 -> ps_stop (skip stopping recorder/pickup voices while
     g_swap is set).
  4. in-place FUN_40096a5c unload bound 0x88 -> 0x80 (preserve recorder pages).

Test: play/hold a recorder buffer so it sounds; mute all other tracks; CHANGE
PROJECT to a SAME-FORMAT sibling. Does the recorder survive the load now?

    python3 tools/build_poolswap_diag2.py    # -> out/mainos_poolswap2.bin
"""
import pathlib, subprocess, sys

BASE = 0x40000400
CAVE_AT = 0x400d7000
STOCK = pathlib.Path("out/raw/section_3_MAIN_OS.bin")
OUT = pathlib.Path("out/mainos_poolswap2.bin")

# detour site -> (symbol, expected original 6 bytes)
DETOURS = [(0x40063e28, "ps_change", "4aaf00046618"),
           (0x40006820, "ps_stop",   "2f0a2f02222f")]


def off(a):
    return a - BASE


def main():
    if not STOCK.exists():
        sys.exit(f"missing {STOCK}")
    img = bytearray(STOCK.read_bytes())

    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", "out/ps2.o",
                    "tools/patch_poolswap_diag2.s"], check=True)
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{CAVE_AT:x}", "-o", "out/ps2.elf",
                    "out/ps2.o"], capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/ps2.elf",
                    "out/ps2.bin"], check=True)
    nm = subprocess.run(["m68k-elf-nm", "out/ps2.elf"], capture_output=True,
                        text=True).stdout
    sym = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    blob = pathlib.Path("out/ps2.bin").read_bytes()
    print(f"cave {len(blob)} B @ 0x{CAVE_AT:08x}")
    if any(img[off(CAVE_AT):off(CAVE_AT) + len(blob)]):
        sys.exit("cave not free")
    img[off(CAVE_AT):off(CAVE_AT) + len(blob)] = blob

    for site, s, exp in DETOURS:
        o = off(site)
        if not bytes(img[o:o + len(exp) // 2]).hex().startswith(exp):
            sys.exit(f"detour 0x{site:08x}: {bytes(img[o:o+6]).hex()} want {exp}")
        img[o:o + 6] = b"\x4e\xf9" + sym[s].to_bytes(4, "big")
        print(f"  detour 0x{site:08x} -> {s} 0x{sym[s]:08x}")

    # preserve recorder pages: FUN_40096a5c unload bound 0x88 -> 0x80
    at = 0x40096a70
    o = off(at)
    if bytes(img[o:o + 4]) != (0x88).to_bytes(4, "big"):
        sys.exit(f"FUN_40096a5c bound not 0x88 @0x{at:08x}: {bytes(img[o:o+4]).hex()}")
    img[o:o + 4] = (0x80).to_bytes(4, "big")
    print(f"  0x{at:08x}  flex unload bound 0x88 -> 0x80 (preserve recorders)")

    OUT.write_bytes(bytes(img))
    stock = STOCK.read_bytes()
    n = sum(1 for x, y in zip(stock, img) if x != y)
    print(f"\n{OUT}: {len(img):,} bytes, {n} changed vs stock")


if __name__ == "__main__":
    main()
