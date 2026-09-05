#!/usr/bin/env python3
"""
STATIC settings relocation to a contiguous 256-slot DDR table (Option B) — REBASE core.

Settings must be contiguous (walk + combined loops), so it relocates rather than dual-tables.
This layers the REBASE step on stock: every classified static-ACCESS ref to the SRAM static-
settings base 0x100d5b30 becomes the DDR base 0x46c97600, giving a contiguous 256-slot table
[0x46c97600, 0x46cdbe00) inside the verified-free hole. The flex-walk END bounds (cmpa/cmpi
#0x100d5b30) are KEPT (0x100d5b30 stays the flex end; flex does not move).

  Classification by the opcode preceding the immediate:
    addi.l/adda.l (product-add), lea, move.l#imm  -> REBASE (static access)
    cmpa.l/cmpi.l (#0x100d5b30 as a compare)       -> KEEP  (flex-end bound / compare)

NOT yet done here (next steps, each emu-gated): the 3 COMBINED loops (0x4008f45c/0x4008fa54/
0x40091024) whose loop-2 continues from a2=0x100d5b30 need cave trampolines (load a2=0x46c97600,
bound 0x46cdbe00); open the static-settings bound guards #128->#256; init the DDR table free
flags at boot. So this image ALONE is not flashable -- it exists to emu-verify the rebase in
isolation (static accessors hit 0x46c97600; nothing static-access still points at 0x100d5b30).

    python3 tools/build_settings_reloc.py   # -> out/mainos_settings_reloc.bin
"""
import pathlib, sys
from collections import Counter

BASE = 0x40000400
SRC = pathlib.Path("out/stock_mainos.bin")
OUT = pathlib.Path("out/mainos_settings_reloc.bin")

SETT_A = 0x100d5b30                 # SRAM static-settings base (also the flex-walk END marker)
SETT_B = 0x46c97600                 # DDR contiguous 256-slot base (verified-free hole)

LEA = {0x41, 0x43, 0x45, 0x47, 0x49, 0x4b, 0x4d}          # lea #abs,aN  (b1==0xf9)
CMPA = {0xb1, 0xb3, 0xb5, 0xb7, 0xb9, 0xbb, 0xbd, 0xbf}   # cmpa.l #imm,aN (b1==0xfc)


def classify(img, o):
    """REBASE (static access) | KEEP (flex-end/compare) for the ref at immediate offset o."""
    b0, b1 = img[o - 2], img[o - 1]
    if b0 == 0x06 and (b1 & 0xf8) == 0x80:                 # addi.l #imm,dN
        return "REBASE", "addi.l d%d" % (b1 & 7)
    if b1 == 0xfc and b0 in (0xd1, 0xd3, 0xd5, 0xd7, 0xd9, 0xdb, 0xdd, 0xdf):  # adda.l #imm,aN
        return "REBASE", "adda.l"
    if b1 == 0xf9 and b0 in LEA:                            # lea #abs,aN
        return "REBASE", "lea"
    if b1 == 0x3c and b0 in range(0x20, 0x2f, 2):          # move.l #imm,dN
        return "REBASE", "move.l#"
    if b1 == 0xfc and b0 in CMPA:                          # cmpa.l #imm,aN
        return "KEEP", "cmpa.l"
    if b0 == 0x0c and 0x80 <= b1 <= 0x87:                  # cmpi.l #imm,dN
        return "KEEP", "cmpi.l d%d" % (b1 & 7)
    return "KEEP", "UNKNOWN pre=%02x%02x" % (b0, b1)


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC}")
    img = bytearray(SRC.read_bytes())
    needle = SETT_A.to_bytes(4, "big")
    offs = []
    i = img.find(needle)
    while i != -1:
        if BASE + i < 0x400e0000:
            offs.append(i)
        i = img.find(needle, i + 1)
    if len(offs) != 43:
        sys.exit(f"expected 43 static-settings refs, found {len(offs)}")

    reb = Counter(); kept = []
    for o in offs:
        act, tag = classify(img, o)
        if act == "REBASE":
            img[o:o + 4] = SETT_B.to_bytes(4, "big")
            reb[tag.split()[0]] += 1
        else:
            kept.append((BASE + o, tag))
    print(f"REBASE (static access) 0x{SETT_A:08x} -> 0x{SETT_B:08x}: {sum(reb.values())} refs {dict(reb)}")
    print(f"KEEP (flex-end/compare): {len(kept)}")
    for va, tag in kept:
        print(f"    keep 0x{va:08x} {tag} #0x{SETT_A:08x}")

    # residual: only the KEPT refs should still hold 0x100d5b30
    remain = img.count(needle)
    if remain != len(kept):
        sys.exit(f"residual 0x{SETT_A:08x} = {remain}, want {len(kept)} (kept only)")
    print(f"post-check: {remain} residual 0x{SETT_A:08x} (== kept flex-end/compares) OK")

    # DDR table extent sanity
    end = SETT_B + 256 * 0x448
    print(f"DDR settings-256 [0x{SETT_B:08x}, 0x{end:08x}) inside hole (< 0x46ceb400): {end < 0x46ceb400}")

    OUT.write_bytes(bytes(img))
    print(f"\n{OUT}: {len(img):,} bytes  (rebase only; trampolines/bounds/init still TODO)")


if __name__ == "__main__":
    main()
