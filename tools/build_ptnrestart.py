#!/usr/bin/env python3
"""
build_ptnrestart.py -- [PTN] + the playing pattern restarts it at the next CHAIN BEHAVIOR window.

Pressing [PTN] + the trig of the pattern that is playing cues a restart: at the next window the
pattern starts again from step 1, through the same switch a cue to another pattern takes. The
trig shows the cue like a cued pattern's trig; a second press cancels it. Always on (stock does
nothing for that press). See tools/patch_ptnrestart.s for the mechanism.

    python3 tools/build_ptnrestart.py      # out/mainos_aedkey.bin -> out/mainos_ptnrestart.bin

Hooks:
    0x40056b68  rs_pick   [PTN] trig handler: jsr 0x400a1030 -> jsr rs_pick           (6 B)
    0x400a0570  rs_entry  cue function prologue: lea -20(sp),sp ; moveml d2-d6,(sp)   (8 B)
    0x400a432a  rs_pend   switch decision: mvsb 0x800065be,d1                        (6 B)
    0x400a43a0  rs_take   switch: movel (a2),d0 ; moveq #1,d2 ; orl d2,d0             (6 B)
    0x4003549e  rs_led    pattern-trig LED painter: mvsb 0x800065c0,d5                (6 B)
Caves (free holes of the main cave):
    .ra 0x400d6996..0x400d6a00   .rb 0x400d702a..0x400d7080   .rc 0x400d7be6..0x400d7c3c
    .rd 0x400d7788..0x400d77c0 (padding after the dual-256 helper family; zero and unreferenced)
"""
import pathlib, subprocess, sys

sys.path.insert(0, "tools")
from hookcheck import check_holes

BASE = 0x40000400
SRC = pathlib.Path("out/mainos_aedkey.bin")
OUT = pathlib.Path("out/mainos_ptnrestart.bin")
NAME = "patch_ptnrestart"

SECTIONS = {            # section: (start, limit)
    ".ra": (0x400d6996, 0x400d6a00),
    ".rb": (0x400d702a, 0x400d7080),
    ".rc": (0x400d7be6, 0x400d7c3c),
    ".rd": (0x400d7788, 0x400d77c0),
}

DETOURS = [
    # site,        symbol,     expected original bytes,     hole, opcode
    (0x40056b68, "rs_pick",  "4eb9400a1030",              6, b"\x4e\xb9"),   # jsr: a call
    (0x400a0570, "rs_entry", "4fefffec48d7007c",          8, b"\x4e\xf9"),
    (0x400a432a, "rs_pend",  "7339800065be",              6, b"\x4e\xf9"),
    (0x400a43a0, "rs_take",  "201274018082",              6, b"\x4e\xf9"),
    (0x4003549e, "rs_led",   "7b39800065c0",              6, b"\x4e\xf9"),
]


def off(a):
    return a - BASE


def assemble():
    o, elf = f"out/{NAME}.o", f"out/{NAME}.elf"
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", o, f"tools/{NAME}.s"], check=True)
    starts = [f"--section-start={s}=0x{a:x}" for s, (a, _) in SECTIONS.items()]
    subprocess.run(["m68k-elf-ld", *starts, "-e", "rs_pick", "-o", elf, o], check=True,
                   capture_output=True)
    blobs = {}
    for s in SECTIONS:
        b = f"out/{NAME}{s.replace('.', '_')}.bin"
        subprocess.run(["m68k-elf-objcopy", "-O", "binary", "-j", s, elf, b], check=True)
        blobs[s] = pathlib.Path(b).read_bytes()
    nm = subprocess.run(["m68k-elf-nm", elf], capture_output=True, text=True).stdout
    syms = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    return blobs, syms


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC} -- run python3 tools/build_all.py")
    img = bytearray(SRC.read_bytes())
    blobs, syms = assemble()

    for s, (lo, hi) in SECTIONS.items():
        blob = blobs[s]
        end = lo + len(blob)
        print(f"{NAME} {s}: {len(blob)} B @ 0x{lo:08x} .. 0x{end-1:08x} (limit 0x{hi:08x})")
        if end > hi:
            sys.exit(f"{s} ends 0x{end:08x}, past its limit 0x{hi:08x}")
        if any(img[off(lo):off(hi)]):
            sys.exit(f"cave 0x{lo:08x}..0x{hi:08x} is NOT free in {SRC}")
        img[off(lo):off(end)] = blob

    check_holes(bytes(img), [(site, n) for site, _, _, n, _ in DETOURS])
    for site, sym, exp, n, op in DETOURS:
        o = off(site)
        if bytes(img[o:o + n]).hex() != exp:
            sys.exit(f"detour 0x{site:08x} unexpected: {bytes(img[o:o+n]).hex()} (want {exp})")
        img[o:o + 6] = op + syms[sym].to_bytes(4, "big")
        if n == 8:
            img[o + 6:o + 8] = b"\x4e\x71"
        print(f"  detour 0x{site:08x} -> {sym} 0x{syms[sym]:08x}")
    print(f"  RS_FLAG @ 0x{syms['RS_FLAG']:08x}")

    OUT.write_bytes(bytes(img))
    d = sum(1 for a, b in zip(SRC.read_bytes(), img) if a != b)
    print(f"\n{OUT}: {len(img):,} bytes, {d} changed vs {SRC.name}")


if __name__ == "__main__":
    main()
