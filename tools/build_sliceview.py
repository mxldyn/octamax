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
CAVE = 0x400d70a8                  # right after the serializer-ext (ends 0x400d70a2)
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
    (0x400444fc, "sv_led",    "103980000000"),   # moveb 0x80000000 (trig-LED refresher tail)
    (0x40056f24, "sv_beat",   "4eb940013784"),   # jsr LEDFLASH (the tempo-LED beat arm)
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
    for s in ("sv_render", "sv_tick", "sv_led", "sv_beat", "lbl_sliceview", "get_sliceview",
              "set_sliceview", "sv_msg"):
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

    # Persistence: the PERSONALIZE runtime words are volatile DSP shared RAM; the real
    # store is the checksummed battery-SRAM block at 0x100fff00, restored to 0x80000070
    # with length 0x64 — one byte short of our words. Extend all three `pea 0x64` to
    # 0x70 (0x800000d4..df ride along; source stays inside the checksummed block and
    # the defaults path zero-fills it, so unconfigured units still read 0 = off).
    for site in (0x4001f322, 0x4001f3be, 0x4001fb24):
        o = off(site)
        if bytes(img[o:o + 4]) != b"\x48\x78\x00\x64":
            sys.exit(f"restore-length pea at 0x{site:08x} is {bytes(img[o:o+4]).hex()}, want 48780064")
        img[o + 3] = 0x70
    print("  settings-restore length 0x64 -> 0x70 at 3 sites (boot/validate/defaults)")

    # Repoint the r10 NO TIMER / LAZY setters (menu entries 16/17) to the shadow-writing
    # replacements, so those toggles persist too. The r10 stubs stay, just unreferenced.
    for idx, old, sym in ((16, 0x400d693e, "sv_set_notimer"), (17, 0x400d697e, "sv_set_lazy")):
        o = off(MENU_SET + idx * 4)
        got = int.from_bytes(img[o:o + 4], "big")
        if got != old:
            sys.exit(f"menu setter[{idx}] is 0x{got:08x}, want the r10 stub 0x{old:08x}")
        img[o:o + 4] = syms[sym].to_bytes(4, "big")
        APPLIED.append((MENU_SET + idx * 4, syms[sym].to_bytes(4, "big")))
    print("  r10 setters repointed to persistent replacements (entries 16/17)")

    OUT.write_bytes(bytes(img))
    src = SRC.read_bytes()
    d = sum(1 for a, b in zip(src, img) if a != b)
    print(f"\n{OUT}: {len(img):,} bytes, {d} changed vs {SRC.name}")


if __name__ == "__main__":
    main()
