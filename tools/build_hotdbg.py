#!/usr/bin/env python3
"""
HOT CHANGE DEBUG INSTRUMENT builder (on R11). Two detours that log track-6's
recorder-playback voice state to /HOTDBG.TXT on the CF (BEFORE the change, AFTER
the load). Pure observability, no fix. See tools/patch_hotdbg.s.

    python3 tools/build.py          # -> out/mainos.bin (R11)
    python3 tools/build_hotdbg.py   # -> out/mainos_dbg.bin
"""
import pathlib, subprocess, sys

BASE = 0x40000400
CAVE_AT = 0x400d7240
R11 = pathlib.Path("out/mainos.bin")
OUT = pathlib.Path("out/mainos_dbg.bin")

DETOURS = [(0x40063e28, "hot_dbg_change", "4aaf00046618"),
           (0x400238a4, "hot_dbg_resync", "2f0a4eb94009")]


def off(a):
    return a - BASE


def main():
    if not R11.exists():
        sys.exit(f"missing {R11} — run tools/build.py first")
    img = bytearray(R11.read_bytes())

    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", "out/hd.o",
                    "tools/patch_hotdbg.s"], check=True)
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{CAVE_AT:x}", "-o", "out/hd.elf",
                    "out/hd.o"], capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/hd.elf",
                    "out/hd.bin"], check=True)
    nm = subprocess.run(["m68k-elf-nm", "out/hd.elf"], capture_output=True,
                        text=True).stdout
    sym = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    blob = pathlib.Path("out/hd.bin").read_bytes()
    print(f"dbg cave {len(blob)} B @ 0x{CAVE_AT:08x}")
    if any(img[off(CAVE_AT):off(CAVE_AT) + len(blob)]):
        sys.exit("cave not free in R11")
    img[off(CAVE_AT):off(CAVE_AT) + len(blob)] = blob

    for site, s, exp in DETOURS:
        o = off(site)
        n_exp = len(exp) // 2
        if not bytes(img[o:o + n_exp]).hex().startswith(exp):
            sys.exit(f"detour 0x{site:08x}: {bytes(img[o:o+n_exp]).hex()} want {exp}")
        img[o:o + 6] = b"\x4e\xf9" + sym[s].to_bytes(4, "big")
        print(f"  detour 0x{site:08x} -> {s} 0x{sym[s]:08x}")

    OUT.write_bytes(bytes(img))
    print(f"\n{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
