#!/usr/bin/env python3
"""
build_aedkey.py -- the [AUDIO EDITOR] key opens the editor on the current track's slot.

After a track copy/paste (or anything else that changes the current track's slot without
re-selecting the track) the AED key reopened the editor on the track's PREVIOUS slot: title,
waveform and slices all belonged to a sample the track no longer plays. See tools/patch_aedkey.s
for the mechanism and the hardware measurement (tools/build_diag_wave1.py).

Applies tools/patch_aedkey.s on top of the image build_all has produced so far:

    python3 tools/build_aedkey.py            # out/mainos_autoptn.bin -> out/mainos_aedkey.bin

Hooks:
    0x4006e274  ak_toggle  the AED key toggle (key-table entry 0x400c080e), 6 B: tstl 0x460e5e4c
    0x4006e250  ak_slices  the open-on-slices shortcut (key-table entry 0x400bf9b8), 8 B:
                           pea 1 ; jsr %pc@(0x4006db58)
Cave: 0x400d6860..0x400d6900, the free tail of the r10 led_stub block (build_all.LED_LIMIT stops
led_stub at 0x400d6860 so the two can never overlap).
"""
import pathlib, subprocess, sys

sys.path.insert(0, "tools")
from hookcheck import check_holes

BASE = 0x40000400
CAVE = 0x400d6860
CAVE_LIMIT = 0x400d6900
SRC = pathlib.Path("out/mainos_autoptn.bin")
OUT = pathlib.Path("out/mainos_aedkey.bin")

DETOURS = [
    # site,        symbol,      expected original bytes,  hole
    (0x4006e274, "ak_toggle", "4ab9460e5e4c", 6),          # tstl 0x460e5e4c
    (0x4006e250, "ak_slices", "487800014ebaf902", 8),      # pea 1 ; jsr %pc@(0x4006db58)
]


def off(a):
    return a - BASE


def assemble(name, at):
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", f"out/{name}.o", f"tools/{name}.s"], check=True)
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{at:x}", "-o", f"out/{name}.elf", f"out/{name}.o"],
                   capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", f"out/{name}.elf", f"out/{name}.bin"], check=True)
    nm = subprocess.run(["m68k-elf-nm", f"out/{name}.elf"], capture_output=True, text=True).stdout
    return (pathlib.Path(f"out/{name}.bin").read_bytes(),
            {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3})


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC} -- run python3 tools/build_all.py")
    img = bytearray(SRC.read_bytes())

    blob, syms = assemble("patch_aedkey", CAVE)
    end = CAVE + len(blob)
    print(f"patch_aedkey: {len(blob)} B @ 0x{CAVE:08x} .. 0x{end-1:08x}")
    if end > CAVE_LIMIT:
        sys.exit(f"blob ends 0x{end:08x}, past the cave limit 0x{CAVE_LIMIT:08x}")
    if any(img[off(CAVE):off(CAVE_LIMIT)]):
        sys.exit(f"cave 0x{CAVE:08x}..0x{CAVE_LIMIT:08x} is NOT free in {SRC}")
    img[off(CAVE):off(end)] = blob

    check_holes(bytes(img), [(site, n) for site, _, _, n in DETOURS])
    for site, sym, exp, n in DETOURS:
        o = off(site)
        if bytes(img[o:o + n]).hex() != exp:
            sys.exit(f"detour 0x{site:08x} unexpected: {bytes(img[o:o+n]).hex()} (want {exp})")
        img[o:o + 6] = b"\x4e\xf9" + syms[sym].to_bytes(4, "big")
        if n == 8:
            img[o + 6:o + 8] = b"\x4e\x71"
        print(f"  detour 0x{site:08x} -> {sym} 0x{syms[sym]:08x}")

    OUT.write_bytes(bytes(img))
    d = sum(1 for a, b in zip(SRC.read_bytes(), img) if a != b)
    print(f"\n{OUT}: {len(img):,} bytes, {d} changed vs {SRC.name}")


if __name__ == "__main__":
    main()
