#!/usr/bin/env python3
"""
site_facts.py — deterministic mechanical facts for every STATIC-settings base-add site, so the
redirect patch can be generated mechanically (no reliance on prose classification). For each site
that adds the static base (addi.l/adda.l #0x100d5b30-or-folded), extract:
  - the destination register (dN / aN),
  - the exact constant added (base, or base+field for folded accessors),
  - whether a `muls #1096` index-scale precedes it within 16 bytes (RANDOM vs walk/literal),
  - the nearest guard immediate before it (#128 static bound / #135 flex bound) if any.

KEY DESIGN (why this matters): the redirect is a UNIFORM linear transform on the STATIC pointer:
    if ptr >= 0x100f7f30 (== base + 128*0x448, i.e. idx>=128):  ptr += (TABLE_B - 0x100f7f30)
It is behaviour-identical to stock for every idx<128 (all existing 128-slot ops, incl. load/save
walks that only ever see 0..127), and only diverts idx>=128 into table B. So replacing each static
base-add with a per-(reg,const) helper is SAFE even at serializer sites (they never see idx>=128 on
a stock file). This removes the A/B-classification risk from the pointer path; A/B only governs the
separate LOAD ROUTE for 128-255 (the sidecar).

    python3 tools/site_facts.py
"""
import subprocess, re

BASE = 0x40000400
STATIC = 0x100d5b30
STATIC_END = 0x100f7f30

# 47 static base-add sites (immediate offset VA) from census_accessors.py
SITES = [
    0x400050d0, 0x4000f4b6, 0x40021e3e, 0x4002263e, 0x40023e36, 0x40023f4c, 0x40024574,
    0x40024fbc, 0x40025000, 0x400252b4, 0x40027728, 0x400277f8, 0x40029026, 0x4004411a,
    0x40044df8, 0x4004ff2e, 0x4006da9a, 0x40077e0a, 0x40079450, 0x40084c6e, 0x40084cb4,
    0x40086022, 0x40086472, 0x400869ce, 0x4008996e, 0x40089fa6, 0x4008b906, 0x4008f42c,
    0x4008f76a, 0x4008f8c8, 0x4008f9e2, 0x4008fb0a, 0x40090854, 0x40090f94, 0x400910f6,
    0x40091340, 0x400936cc, 0x400939a4, 0x40093f88, 0x40094380, 0x40098d0a, 0x400991dc,
    0x40099412, 0x40004f54, 0x40004ff4, 0x4000c6b8, 0x400893f0,
]


def dis(start, stop):
    out = subprocess.run(
        ["m68k-elf-objdump", "-D", "-b", "binary", "-m", "m68k:68040",
         "--adjust-vma=0x40000400", f"--start-address=0x{start:x}",
         f"--stop-address=0x{stop:x}", "out/stock_mainos.bin"],
        capture_output=True, text=True).stdout.splitlines()
    return [l for l in out if re.match(r"^4[0-9a-f]{7}:", l)]


# the instruction that CONTAINS the immediate at VA `site` starts 2 bytes before (opcode word).
def decode_site(site):
    lines = dis(site - 0x20, site + 8)
    # find the line whose instruction covers `site-2` (the opcode word)
    op_va = site - 2
    row = None
    for l in lines:
        va = int(l.split(":")[0], 16)
        if va == op_va:
            row = l
            break
    reg = const = mn = None
    if row:
        txt = row.split("\t")[-1].strip()
        mn = txt
        m = re.search(r"#(0x[0-9a-f]+|\d+),%?([ad]\d)", txt)
        if m:
            const = int(m.group(1), 0)
            reg = m.group(2)
        else:
            m2 = re.search(r"#(0x[0-9a-f]+|\d+),%?(sp|a7)", txt)
            if m2:
                const = int(m2.group(1), 0); reg = "a7"
    return mn, reg, const


def facts(site):
    mn, reg, const = decode_site(site)
    win = dis(site - 0x18, site + 2)
    has_muls = any("muls" in l for l in win)
    # nearest guard immediate 128/135 in a slightly larger pre-window
    gwin = dis(site - 0x40, site + 0x20)
    guard = None
    for l in gwin:
        if re.search(r"#(0x80|128)\b", l.split("\t")[-1]):
            guard = 128
        if re.search(r"#(0x87|135)\b", l.split("\t")[-1]):
            guard = 135
    return mn, reg, const, has_muls, guard


def main():
    from collections import Counter
    print(f"{'SITE':>10}  {'reg':>3} {'const':>10} field  muls guard  mnemonic")
    regc = Counter(); folded = []
    for s in SITES:
        mn, reg, const, muls, guard = facts(s)
        fld = (const - STATIC) if (const and STATIC <= const < STATIC + 0x448) else 0
        rc = f"{reg}/{const:#010x}" if reg and const else "??"
        regc[rc] += 1
        if fld:
            folded.append((s, reg, fld))
        print(f"0x{s:08x}  {str(reg):>3} {const if const else 0:#010x} +0x{fld:03x}"
              f"  {'Y' if muls else '.'}   {str(guard):>4}  {mn}")
    print(f"\nHELPER FAMILY needed — distinct (reg, const) pairs: {len(regc)}")
    for rc, n in sorted(regc.items()):
        print(f"    {rc}   x{n}")
    print(f"\nfolded-field sites: {len(folded)}  {[(hex(s),r,hex(f)) for s,r,f in folded]}")


if __name__ == "__main__":
    main()
