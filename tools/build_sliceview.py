#!/usr/bin/env python3
"""
build_sliceview.py -- SLICE PLAYHEAD: readable SRC>SLICES view, behind a PERSONALIZE toggle.

Applies tools/patch_sliceview.s on top of an image that ALREADY carries the maxolydian r10
patch (the PERSONALIZE menu arrays must live at their relocated cave addresses with 18
entries — this builder appends the 19th). Run after build_all's other steps:

    python3 tools/build_sliceview.py            # out/mainos_all.bin -> out/mainos_sliceview.bin

Hooks:
    0x40044cf0  sv_render   the SLICES arm of the view-content renderer (pea 0x400beafa)
    0x40056c92  sv_tick     timer task, right after the countdown-tick call (tstl 0x46104ca8)
Menu:
    entry 19 of the relocated PERSONALIZE arrays (label/getter/setter at +72), and the
    item-count moveq at 0x40068fb2 goes #17 -> #18.
"""
import pathlib, subprocess, sys

sys.path.insert(0, "tools")
from hookcheck import check_holes

BASE = 0x40000400
CAVE = 0x400d70c0
CAVE_LIMIT = 0x400d7400            # dual-256 helper family starts here
SRC = pathlib.Path("out/mainos_all.bin")
OUT = pathlib.Path("out/mainos_sliceview.bin")

# the relocated PERSONALIZE arrays (maxolydian r10 layout, 18 entries each, stride 0x50)
MENU_LBL = 0x400d6a00
MENU_GET = 0x400d6a50
MENU_SET = 0x400d6aa0
MENU_ENTRY = 18                    # 0-based index of the slot we claim (19th entry, max 20)
COUNT_SITE = 0x40068fb2            # moveq #17 (7211) -> moveq #18 (7212)

DETOURS = [
    # site,        symbol,      expected original bytes
    (0x40044cf0, "sv_render", "4879400beafa"),   # pea 0x400beafa (the grid bitmap arg)
    (0x40056c92, "sv_tick",   "4ab946104ca8"),   # tstl 0x46104ca8 (after the tick call)
]

APPLIED = []   # (addr, bytes) written outside the cave/detours, filled in by main()


def off(a):
    return a - BASE


def jmp(t):
    return b"\x4e\xf9" + t.to_bytes(4, "big")


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
        sys.exit(f"missing {SRC} — run python3 tools/build_all.py first")
    img = bytearray(SRC.read_bytes())

    blob, syms = assemble("patch_sliceview", CAVE)
    end = CAVE + len(blob)
    print(f"patch_sliceview: {len(blob)} B @ 0x{CAVE:08x} .. 0x{end-1:08x}")
    for s in ("sv_render", "sv_tick", "lbl_sliceview", "get_sliceview", "set_sliceview", "sv_msg"):
        print(f"  {s:14s} 0x{syms[s]:08x}")
    if end > CAVE_LIMIT:
        sys.exit(f"blob ends 0x{end:08x}, past the cave limit 0x{CAVE_LIMIT:08x}")
    if any(img[off(CAVE):off(end)]):
        sys.exit(f"cave at 0x{CAVE:08x} is NOT free in {SRC}")
    img[off(CAVE):off(end)] = blob
    print("  cave verified free, blob placed")

    check_holes(bytes(img), [(site, 6) for site, _, _ in DETOURS])
    for site, sym, exp in DETOURS:
        o = off(site)
        if bytes(img[o:o + 6]).hex() != exp:
            sys.exit(f"detour 0x{site:08x} unexpected: {bytes(img[o:o+6]).hex()} (want {exp})")
        img[o:o + 6] = jmp(syms[sym])
        print(f"  detour 0x{site:08x} -> {sym} 0x{syms[sym]:08x}")

    # 19th PERSONALIZE entry. APPLIED records every write outside the cave and the detour
    # holes, so build_all can exempt them when it re-verifies the maxolydian hunks.
    APPLIED.clear()
    for table, sym in ((MENU_LBL, "lbl_sliceview"), (MENU_GET, "get_sliceview"), (MENU_SET, "set_sliceview")):
        o = off(table + MENU_ENTRY * 4)
        if any(img[o:o + 4]):
            sys.exit(f"menu slot at 0x{table + MENU_ENTRY*4:08x} is not free: {bytes(img[o:o+4]).hex()}")
        img[o:o + 4] = syms[sym].to_bytes(4, "big")
        APPLIED.append((table + MENU_ENTRY * 4, syms[sym].to_bytes(4, "big")))
    o = off(COUNT_SITE)
    if bytes(img[o:o + 2]) != b"\x72\x11":
        sys.exit(f"count moveq at 0x{COUNT_SITE:08x} is {bytes(img[o:o+2]).hex()}, want 7211")
    img[o:o + 2] = b"\x72\x12"
    APPLIED.append((COUNT_SITE, b"\x72\x12"))
    print(f"  PERSONALIZE entry {MENU_ENTRY + 1} appended, item count 18 -> 19")

    OUT.write_bytes(bytes(img))
    src = SRC.read_bytes()
    d = sum(1 for a, b in zip(src, img) if a != b)
    print(f"\n{OUT}: {len(img):,} bytes, {d} changed vs {SRC.name}")


if __name__ == "__main__":
    main()
