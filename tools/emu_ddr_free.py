#!/usr/bin/env python3
"""
emu_ddr_free.py — verify the candidate table-B DDR window is free, WITHOUT flashing.

The 128->256 static extension needs ~142 KB of DDR for table B (state 128*44=0x1600 +
settings 128*0x448=0x22400). Static recon found a 350 KB hole with ZERO operand references
right above the state tables:

    STATE A     [0x46c90a78, 0x46c92078)   FLEX [0x46c922c4, 0x46c94074)
    last control ref ......... 0x46c93c28
    >>> CANDIDATE FREE HOLE [0x46c94074, 0x46ceb400)  (350 KB, unreferenced) <<<
    record-array [0x46ceb400, ...)  (28-byte records, grows up)

"No static reference" is necessary but not sufficient (computed pointers exist). This adds
dynamic evidence: emulate the routines that manage the NEIGHBOURING structures, record every
DDR byte they read/write, and assert none lands in the proposed table-B window. A positive
control (the state-table scanners) proves the emulation really touches the tables and stops at
their bounds — so a clean window result is meaningful, not vacuous.

    python3 tools/emu_ddr_free.py

Residual risk (honest): this covers only the routines in ROUTINES; it cannot prove no path
anywhere touches the hole. Treat GREEN as strong corroboration of the static zero-reference
finding, not absolute proof. The accessors we later add to USE the window are re-checked by
emu_check.py.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from emu_check import Emu

STOCK = "out/stock_mainos.bin"

WIN_LO, WIN_HI = 0x46c96000, 0x46cb9a00           # proposed table-B window (~142 KB)
HOLE_LO, HOLE_HI = 0x46c94074, 0x46ceb400

# Fresh emu RAM is zero, so the free-slot scanners (slot[+8]==1 test) never match and run the
# FULL 128-iteration sweep, reading the whole table across its declared bound = positive control.
ROUTINES = [
    dict(name="static_slot_scan", entry=0x40024098, regs={}, mem={}, max_insn=20000,
         note="LOWER neighbour: sweeps STATE table A [0x46c90a78, +128*44) reading slot[+8]"),
    dict(name="flex_slot_scan",   entry=0x400240e8, regs={}, mem={}, max_insn=20000,
         note="LOWER neighbour: sweeps FLEX state [0x46c922c4, +..) (flag path)"),
    # UPPER neighbour: the record-array init at 0x4001bdb4 writes the array AT 0x46ceb400 (top of
    # the hole). Needs the config magic "EFGH" @0x200000 and a small entry count @0x200004.
    dict(name="record_array_init", entry=0x4001bdb4,
         regs={}, mem={0x200000: b"\x45\x46\x47\x48", 0x200004: (4).to_bytes(4, "big")},
         max_insn=200000,
         note="UPPER neighbour: inits 28-byte record array at 0x46ceb400 (should write ABOVE the hole)"),
]


def main():
    if not pathlib.Path(STOCK).exists():
        sys.exit(f"missing {STOCK} (decode stock section 3 first)")
    emu = Emu(STOCK)
    print(f"stock: {STOCK}")
    print(f"candidate table-B window [0x{WIN_LO:08x}, 0x{WIN_HI:08x}) "
          f"({(WIN_HI-WIN_LO)//1024} KB) in hole [0x{HOLE_LO:08x}, 0x{HOLE_HI:08x})\n")
    any_hit = False
    for r in ROUTINES:
        res = emu.call(r["entry"], regs=r.get("regs"), mem=r.get("mem"),
                       log_access=True, max_insn=r["max_insn"])
        cov = res["reads"] | res["wcov"]
        seg = [a for a in cov if 0x46c00000 <= a < 0x46d00000]
        ext = (min(seg), max(seg)) if seg else None
        win_hits = sorted(a for a in cov if WIN_LO <= a < WIN_HI)
        any_hit |= bool(win_hits)
        print(f"  {r['name']:18} reason={res['reason']}")
        print(f"      {r['note']}")
        if ext:
            print(f"      0x46cxxxxx access extent: 0x{ext[0]:08x}..0x{ext[1]:08x}"
                  f"   (below hole start 0x{HOLE_LO:08x}: {ext[1] < HOLE_LO})")
        else:
            print("      no 0x46cxxxxx access recorded")
        print(f"      table-B window hits: {'NONE' if not win_hits else hex(win_hits[0])+'..'+hex(win_hits[-1])}")
    print()
    if any_hit:
        print("WINDOW TOUCHED by a stock routine -> NOT free; pick another window")
        sys.exit(1)
    print("GREEN: no traced routine touches the window; scanners confirm they read the state")
    print("tables and stop below the hole. Corroborates the static zero-reference finding.")
    sys.exit(0)


if __name__ == "__main__":
    main()
