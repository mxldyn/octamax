#!/usr/bin/env python3
"""
build_autoptn.py -- BANK AUTO PTN 1: picking a bank in SELECT BANK also picks its pattern 1,
behind a PERSONALIZE toggle (the 20th and last entry the relocated menu arrays can hold).

Applies tools/patch_autoptn.s on top of an image that ALREADY carries the maxolydian r10 patch
and the slice playhead (the PERSONALIZE arrays must live at their relocated cave addresses with
19 entries -- this builder appends the 20th). build_all.py runs it as its last step:

    python3 tools/build_autoptn.py            # out/mainos_sliceview.bin -> out/mainos_autoptn.bin

Hook:
    0x4007b344  ap_stub   the bank store at the tail of FUN_4007b2fc's phase-0 path
                          (move.l D2,(0x460e73b8).l -- one 6-byte instruction)
Menu:
    entry 20 of the relocated PERSONALIZE arrays (label/getter/setter at +76), and the
    item count at 0x40068fb2 becomes an unconditional 20: `moveq #19 ; sub.l D0,D1` (19 + the
    MKII hardware flag 0x46c8d18c) -> `moveq #20 ; nop`. Stock used the flag to hide LED
    BRIGHTNESS (entry 16) on a MKI; with appended entries the flag only hid the LAST entry on
    a MKI, which would have been this one.
Flag:
    0x800000a8 runtime / 0x100fff38 battery shadow -- inside the stock 0x64-byte restore, so
    no restore-length change is needed (the sliceview builder already extended it anyway).
"""
import pathlib, subprocess, sys

sys.path.insert(0, "tools")
from hookcheck import check_holes

BASE = 0x40000400
CAVE = 0x400d7b60                  # after the arp blob (0x400d7920 + 548 B = 0x400d7b44)
CAVE_LIMIT = 0x400d7c3c            # stock data resumes here
SRC = pathlib.Path("out/mainos_sliceview.bin")
OUT = pathlib.Path("out/mainos_autoptn.bin")

# the relocated PERSONALIZE arrays (maxolydian r10 layout, stride 0x50 = 20 entries max)
MENU_LBL = 0x400d6a00
MENU_GET = 0x400d6a50
MENU_SET = 0x400d6aa0
MENU_ENTRY = 19                    # 0-based index of the slot we claim (20th entry, the last)
COUNT_SITE = 0x40068fb2            # moveq #18 (7212) -> moveq #20 (7214)
COUNT_SUB = 0x40068fb4             # sub.l D0,D1 (9280) -> nop (4e71): drop the MKII-flag term

DETOURS = [
    # site,        symbol,    expected original bytes
    (0x4007b344, "ap_stub", "23c2460e73b8"),   # move.l D2,(0x460e73b8).l  (bank store)
]

F_AUTOPTN, SH_AUTOPTN = 0x800000a8, 0x100fff38

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

    blob, syms = assemble("patch_autoptn", CAVE)
    end = CAVE + len(blob)
    print(f"patch_autoptn: {len(blob)} B @ 0x{CAVE:08x} .. 0x{end-1:08x}")
    for s in ("ap_stub", "lbl_autoptn", "get_autoptn", "set_autoptn"):
        print(f"  {s:14s} 0x{syms[s]:08x}")
    assert syms["F_AUTOPTN"] == F_AUTOPTN and syms["SH_AUTOPTN"] == SH_AUTOPTN, "flag words drifted"
    if end > CAVE_LIMIT:
        sys.exit(f"blob ends 0x{end:08x}, past the cave limit 0x{CAVE_LIMIT:08x}")
    if any(img[off(CAVE):off(CAVE_LIMIT)]):
        sys.exit(f"cave 0x{CAVE:08x}..0x{CAVE_LIMIT:08x} is NOT free in {SRC}")
    img[off(CAVE):off(end)] = blob
    print("  cave verified free, blob placed")

    check_holes(bytes(img), [(site, 6) for site, _, _ in DETOURS])
    for site, sym, exp in DETOURS:
        o = off(site)
        if bytes(img[o:o + 6]).hex() != exp:
            sys.exit(f"detour 0x{site:08x} unexpected: {bytes(img[o:o+6]).hex()} (want {exp})")
        img[o:o + 6] = jmp(syms[sym])
        print(f"  detour 0x{site:08x} -> {sym} 0x{syms[sym]:08x}")

    # 20th PERSONALIZE entry. APPLIED records every write outside the cave and the detour
    # holes, so build_all can exempt them when it re-verifies the maxolydian hunks.
    APPLIED.clear()
    for table, sym in ((MENU_LBL, "lbl_autoptn"), (MENU_GET, "get_autoptn"), (MENU_SET, "set_autoptn")):
        o = off(table + MENU_ENTRY * 4)
        if any(img[o:o + 4]):
            sys.exit(f"menu slot at 0x{table + MENU_ENTRY*4:08x} is not free: {bytes(img[o:o+4]).hex()}")
        prev = off(table + (MENU_ENTRY - 1) * 4)
        if not any(img[prev:prev + 4]):
            sys.exit(f"menu slot {MENU_ENTRY - 1} at 0x{table + (MENU_ENTRY-1)*4:08x} is empty: "
                     f"{SRC} does not carry the slice playhead entry")
        img[o:o + 4] = syms[sym].to_bytes(4, "big")
        APPLIED.append((table + MENU_ENTRY * 4, syms[sym].to_bytes(4, "big")))
    o = off(COUNT_SITE)
    if bytes(img[o:o + 4]) != b"\x72\x12\x92\x80":
        sys.exit(f"count at 0x{COUNT_SITE:08x} is {bytes(img[o:o+4]).hex()}, want 7212 9280 (moveq #18 ; sub.l D0,D1)")
    img[o:o + 4] = b"\x72\x14\x4e\x71"
    APPLIED.append((COUNT_SITE, b"\x72\x14"))
    APPLIED.append((COUNT_SUB, b"\x4e\x71"))
    print(f"  PERSONALIZE entry {MENU_ENTRY + 1} appended, item count 19/20 -> 20 unconditionally (MKII flag term dropped)")

    # the flag word must be inside the boot restore (0x80000070 + 0x64 in stock, 0x70 after the
    # sliceview builder): both hold, this is just the guard against someone moving it
    for site in (0x4001f322, 0x4001f3be, 0x4001fb24):
        n = img[off(site) + 3]
        assert 0x80000070 + n > F_AUTOPTN, f"restore length 0x{n:x} at 0x{site:08x} misses the flag"

    OUT.write_bytes(bytes(img))
    src = SRC.read_bytes()
    d = sum(1 for a, b in zip(src, img) if a != b)
    print(f"\n{OUT}: {len(img):,} bytes, {d} changed vs {SRC.name}")


if __name__ == "__main__":
    main()
