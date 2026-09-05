#!/usr/bin/env python3
"""census_unmigrated.py -- exhaustive census of per-slot table base immediates in the stock image,
cross-checked against the migrated set in build_dual256.CORE (+ T24/VOICE_S4/WAVE_RD/folded). Reports
every UN-MIGRATED redirect-class site (addi/adda/lea/movea/pea computing base + idx*stride) so we catch
all remaining gaps (like the track-header name reader 0x40023e34) in one pass.

    python3 tools/census_unmigrated.py
"""
import sys, pathlib
sys.path.insert(0, "tools")
import build_dual256 as bd
from otdis import dis, BASE

IMG = pathlib.Path("out/stock_mainos.bin").read_bytes()

# per-slot bases we care about (redirectable random-access tables). folded settings variants included.
BASES = {
    0x100d5b30: "SETTINGS-A",
    0x100d5c3e: "SETTINGS-A+0x10e",
    0x100d5c59: "SETTINGS-A+0x129",
    0x46c90a78: "STATE-A",
    0x46c920a4: "STRIDE4#1",
    0x46c93a24: "STRIDE4#2",
    0x46aaa980: "WAVEFORM",
    0x46947c56: "T24",
}

# ---- build the set of migrated IMM VAs (the location of the 4-byte immediate) ----
migrated_imm = set()
for fn, spec in bd.CORE.items():
    for imm_va, hn in spec["sites"]:
        migrated_imm.add(imm_va)             # CORE stores imm_va (instr+2)
for instr_va, hn in bd.T24_ADDA_SITES:
    migrated_imm.add(instr_va + 2)
for instr_va in bd.T24_LEA_SITES:
    migrated_imm.add(instr_va + 2)
for instr_va, base, hn in bd.VOICE_S4_LEA_SITES:
    migrated_imm.add(instr_va + 2)
migrated_imm.add(bd.WAVE_RD_HOOK + 2)        # waveform reader

# opcode word (the 2 bytes before the immediate) -> class
def classify(op):
    hi = op >> 8
    lo = op & 0xff
    # addi.l #imm,Dn : 0000 0110 10xx xreg  (0x068N)
    if (op & 0xfff8) == 0x0680: return "addi.l Dn", "redirect"
    # adda.l #imm,An : 1101 areg 11 111 100 -> dNfc
    if (op & 0xf1ff) == 0xd1fc: return "adda.l An", "redirect"
    # lea #imm,An : 0100 areg 111 111 001 -> 4Xf9
    if (op & 0xf1ff) == 0x41f9: return "lea An", "redirect"
    # movea.l #imm,An : 0010 areg 001 111 100 -> 2Xfc
    if (op & 0xf1ff) == 0x207c: return "movea.l An", "redirect"
    # move.l #imm,Dn : 0010 000 dreg 001 111 100? move.l #imm,Dn = 203c (d0) .. 2E3C ; pattern 2X3C
    if (op & 0xf1ff) == 0x203c: return "move.l #imm,Dn", "leave?"
    # cmpi.l #imm,Dn : 0c8N
    if (op & 0xfff8) == 0x0c80: return "cmpi.l Dn", "leave(bound)"
    # cmpa.l #imm,An : bXfc
    if (op & 0xf1ff) == 0xb1fc: return "cmpa.l An", "leave(bound)"
    # pea #imm : 4879
    if op == 0x4879: return "pea", "leave(global)"
    return f"op=0x{op:04x}", "?"

def instr_text(instr_va):
    try:
        rows = dis(instr_va, instr_va + 8)
        return rows[0].strip() if rows else ""
    except Exception:
        return ""

print(f"migrated imm VAs known: {len(migrated_imm)}\n")
tot_unmig = 0
for base, label in BASES.items():
    tb = base.to_bytes(4, "big")
    hits = [k for k in range(0, len(IMG) - 4, 2) if IMG[k:k + 4] == tb]
    print(f"=== {label}  0x{base:08x}  ({len(hits)} immediate hits) ===")
    for k in hits:
        imm_va = BASE + k
        instr_va = imm_va - 2
        op = int.from_bytes(IMG[k - 2:k], "big")
        name, cls = classify(op)
        mig = imm_va in migrated_imm
        if cls == "redirect" and not mig:
            tot_unmig += 1
            print(f"  UNMIGRATED  instr=0x{instr_va:08x} imm=0x{imm_va:08x}  {name:12s}  {instr_text(instr_va)}")
        elif cls == "redirect" and mig:
            pass  # migrated, skip in output
    print()
print(f"TOTAL un-migrated redirect-class sites: {tot_unmig}")
