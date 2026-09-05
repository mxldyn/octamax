#!/usr/bin/env python3
"""
Pool move + settings->DDR with CORRECT boundary disambiguation + boot-zero.

  The settings table [0x100d5b30, 0x100f7f30) (128 slots x 0x448) is flanked by two
  neighbours that SHARE its boundary addresses, so the instruction TYPE decides ownership:

    * 0x100d5b30 (settings BASE) is ALSO the END of "Table A" at 0x100b14f0 (136 slots,
      0x100b14f0 + 136*0x448 == 0x100d5b30). Loops walk a4/a2/a3/fp +0x448 UP from
      0x100b14f0 and stop with `cmpa.l #0x100d5b30`. Relocating those 5 cmpa bounds to
      0x40a955e0 turned them into runaway loops (walk SRAM 0x100b14f0 -> DDR 0x40a955e0)
      => hang + garbage audio right after the LOADING popup. So: base-loads/arith to
      0x100d5b30 relocate (settings base); cmpa to 0x100d5b30 do NOT (Table-A end).

    * 0x100f7f30 (settings END) is ALSO the base of a global struct above the table.
      cmpa/cmpi/arith to it are settings loop bounds (relocate); pea base-loads are the
      global's pointer (do NOT relocate) -- the mirror of the rule above.

  Plus boot-zero of the reserved DDR window (stock zeroes the SRAM the table came from).

    python3 tools/build.py          # -> out/mainos.bin (R11)
    python3 tools/build_tablefix.py # -> out/mainos_tablefix.bin
"""
import pathlib, subprocess, sys
from collections import Counter

BASE = 0x40000400
R11 = pathlib.Path("out/mainos.bin")
OUT = pathlib.Path("out/mainos_tablefix.bin")

OLD_POOL, NEW_POOL = 0x40a955e0, 0x40af55e0
COUNT_AT, OLD_COUNT, NEW_COUNT = 0x40096f82, 0x390A, 0x38CA
TAB_LO, TAB_HI = 0x100d5b30, 0x100f7f31
TAB_BASE = 0x100d5b30      # shared with Table-A END (cmpa here = Table A, keep)
TAB_END = 0x100f7f30       # shared with a global base (base-loads here = global, keep)
TAB_DELTA = 0x40a955e0 - 0x100d5b30
CODE_END = 0x400e0000
BASE_LOADS = {"lea", "pea", "movea#", "move.l#", "move.l#abs", "jsr/jmp"}

CAVE_AT = 0x400d72a0
DETOUR_AT = 0x4001fa64
DETOUR_EXPECT = "41f910000000"
RESUME_AT = 0x4001fa6a


def off(a):
    return a - BASE


def opname(b0, b1):
    if b1 == 0xf9 and b0 in (0x41, 0x43, 0x45, 0x47, 0x49, 0x4b, 0x4d): return "lea"
    if (b0 << 8 | b1) == 0x4879: return "pea"
    if (b0 << 8 | b1) in (0x4eb9, 0x4ef9): return "jsr/jmp"
    if b1 == 0x7c and b0 in range(0x20, 0x2d, 2): return "movea#"
    if b1 == 0x3c and b0 in range(0x20, 0x2f, 2): return "move.l#"
    if (b0 << 8 | b1) == 0x23fc: return "move.l#abs"
    if b1 == 0xfc and b0 in (0xd1, 0xd3, 0xd5, 0xd7, 0xd9, 0xdb, 0xdd, 0xdf): return "adda#"
    if b1 == 0xfc and b0 in (0x91, 0x93, 0x95, 0x97, 0x99, 0x9b, 0x9d, 0x9f): return "suba#"
    if b1 == 0xfc and b0 in (0xb1, 0xb3, 0xb5, 0xb7, 0xb9, 0xbb, 0xbd, 0xbf): return "cmpa#"
    if b0 in (0x00, 0x02, 0x04, 0x06, 0x0a, 0x0c) and 0x80 <= b1 <= 0x87: return "immarith"
    return None


def main():
    if not R11.exists():
        sys.exit(f"missing {R11} — run tools/build.py first")
    img = bytearray(R11.read_bytes())

    # step 1: pool
    n = img.count(OLD_POOL.to_bytes(4, "big"))
    if not (18 <= n <= 30):
        sys.exit(f"pool-base count {n} unexpected")
    img = bytearray(img.replace(OLD_POOL.to_bytes(4, "big"), NEW_POOL.to_bytes(4, "big")))
    o = off(COUNT_AT)
    if int.from_bytes(img[o:o + 4], "big") != OLD_COUNT:
        sys.exit("count mismatch")
    img[o:o + 4] = NEW_COUNT.to_bytes(4, "big")
    print(f"step 1: pool moved ({n} refs)")

    # step 2: relocate settings, disambiguating both shared boundaries by op type
    reloc = Counter(); skip_base = []; skip_end = []
    N = len(img)
    for i in range(2, N - 3):
        v = (img[i] << 24) | (img[i + 1] << 16) | (img[i + 2] << 8) | img[i + 3]
        if not (TAB_LO <= v < TAB_HI and (BASE + i) < CODE_END):
            continue
        op = opname(img[i - 2], img[i - 1])
        if not op:
            continue
        # Table-A END bound (not settings base): cmpa OR cmpi (immarith with 0x0c prefix)
        if v == TAB_BASE and (op == "cmpa#" or (op == "immarith" and img[i - 2] == 0x0c)):
            skip_base.append(BASE + i); continue
        if v == TAB_END and op in BASE_LOADS:      # global base above the table
            skip_end.append(BASE + i); continue
        img[i:i + 4] = (v + TAB_DELTA).to_bytes(4, "big")
        reloc[v] += 1
    total = sum(reloc.values())
    print(f"step 2: {total} relocated;  skip cmpa@base(Table-A end): {len(skip_base)};  skip pea@end(global): {len(skip_end)}")
    for a in skip_base: print(f"    keep 0x{a:08x} cmpa/cmpi #0x{TAB_BASE:08x} (Table-A end)")
    for a in skip_end:  print(f"    keep 0x{a:08x} base-load #0x{TAB_END:08x} (global)")
    if not (total == 47 and len(skip_base) == 7 and len(skip_end) == 2):
        sys.exit(f"unexpected: {total}/{len(skip_base)}/{len(skip_end)} (want 47/7/2)")

    # boot-zero hook
    r = subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", "out/bootzero.o", "tools/patch_bootzero.s"])
    if r.returncode:
        sys.exit("assembler failed")
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{CAVE_AT:x}", "-o", "out/bootzero.elf", "out/bootzero.o"],
                   capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/bootzero.elf", "out/bootzero.bin"], check=True)
    nm = subprocess.run(["m68k-elf-nm", "out/bootzero.elf"], capture_output=True, text=True).stdout
    sym = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    blob = pathlib.Path("out/bootzero.bin").read_bytes()
    end = CAVE_AT + len(blob)
    if end > 0x400d7c3c:
        sys.exit("blob overruns cave")
    if any(img[off(CAVE_AT):off(end)]):
        sys.exit("cave not free")
    img[off(CAVE_AT):off(end)] = blob
    o = off(DETOUR_AT)
    if bytes(img[o:o + 6]).hex() != DETOUR_EXPECT:
        sys.exit(f"detour 0x{DETOUR_AT:08x}: {bytes(img[o:o+6]).hex()} want {DETOUR_EXPECT}")
    img[o:o + 6] = b"\x4e\xf9" + sym["bootzero_stub"].to_bytes(4, "big")
    print(f"boot-zero: detour 0x{DETOUR_AT:08x} -> 0x{sym['bootzero_stub']:08x}")

    OUT.write_bytes(bytes(img))
    print(f"\n{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
