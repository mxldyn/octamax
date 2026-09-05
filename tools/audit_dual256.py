#!/usr/bin/env python3
"""audit_dual256.py -- image-wide bug hunter for the 128->256 STATIC extension (built image).

CHECK 1 (OOB): every per-slot base-add (SETTINGS/STATE/STRIDE4, incl folded) that is STILL a stock add
(NOT redirected to a jsr helper) is examined together with its nearest preceding clamp (cmpi.l/cmpa.l
#imm + bhi/bhs). If that clamp was RAISED (imm >= 129) the add is reachable for idx>=128 -> OOB. A clamp is only
CLOSED when it actually excludes idx=128: `cmpi #128 + bhs/bcc` does, but `cmpi #128 + bhi` does NOT
(bhi bails on idx > 128, so idx == 128 falls through to the stock add -> SETTINGS-A[128] = OOB). That
off-by-one is invisible in stock (slot 128 never occurs) and reachable in the 256 build, so it is
reported as a first-class finding rather than counted safe. This generalizes the CORE OOB-gate to the WHOLE image
(catches clamps opened outside CORE, e.g. SENTINEL_FIX/CAPS).

CHECK 2 (helper bounds): every installed helper maps idx=255 within the reserved region.

    python3 tools/audit_dual256.py [--img out/mainos_persist256.bin]
"""
import pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd

BASE = 0x40000400
IMGPATH = sys.argv[sys.argv.index("--img") + 1] if "--img" in sys.argv else "out/mainos_persist256.bin"
IMG = bytearray(pathlib.Path(IMGPATH).read_bytes())
def off(a): return a - BASE

SLOT_BASES = {0x100d5b30: "SETTINGS-A", 0x100d5c3e: "SETTINGS-A+0x10e", 0x100d5c59: "SETTINGS-A+0x129",
              0x46c90a78: "STATE-A", 0x46c920a4: "STRIDE4#1", 0x46c93a24: "STRIDE4#2"}
RESERVE_LO, RESERVE_HI = 0x40a955e0, 0x40af55e0

# reviewed-safe (manually verified NOT reachable for idx>=128) -- keep so the audit flags only NEW issues.
WHITELIST = {
    0x40025546: "index a2 is a constant 0 (subal a2,a2 @0x4002550a dominates) -> STATE-A[0], in-bounds",
    0x4008b946: "serializer CLASS-B; STATIC branch (d5==0) bounded by #128 @0x4008b8ee; not fed idx>=129",
    0x4008b950: "serializer CLASS-B; FLEX branch (d5!=0) STRIDE4#1 bounded by FLEX #135; static gen unaffected",
}


def is_slot_add(k):
    """True if bytes at k are a per-slot base immediate whose opcode (k-2) is a stock addi/adda."""
    v = int.from_bytes(IMG[k:k + 4], "big")
    if v not in SLOT_BASES:
        return None
    b0, b1 = IMG[k - 2], IMG[k - 1]
    is_addi = (b0 == 0x06 and 0x80 <= b1 <= 0x87)
    is_adda = (b1 == 0xfc and b0 in (0xd1, 0xd3, 0xd5, 0xd7, 0xd9, 0xdb, 0xdd, 0xdf))
    is_lea = (b0 in (0x41, 0x43, 0x45, 0x47, 0x49, 0x4b, 0x4d, 0x4f) and b1 == 0xf9)
    if is_addi or is_adda:
        return ("add", v)
    if is_lea:
        return ("lea", v)
    return None


def nearest_clamp(instr_va):
    """Scan back up to 0x40 bytes for a cmpi.l/cmpa.l #imm followed within a few bytes by bhi/bhs/bcc.
    Return (clamp_va, imm, branch_opcode) or None."""
    for back in range(2, 0x44, 2):
        a = instr_va - back
        k = off(a)
        w = int.from_bytes(IMG[k:k + 2], "big")
        is_cmpi = (w & 0xfff8) == 0x0c80          # cmpi.l #imm,dN
        is_cmpa = (w & 0xf1ff) == 0xb0fc          # cmpa.l #imm,aN (bXfc)
        if is_cmpi or is_cmpa:
            imm = int.from_bytes(IMG[k + 2:k + 6], "big")
            # require a conditional branch (bhi 0x62 / bhs-bcc 0x64 / bls 0x63) shortly after the cmp
            br = IMG[k + 6]
            if br in (0x62, 0x63, 0x64) or IMG[k + 6:k + 8] in (b"\x62\x00", b"\x63\x00", b"\x64\x00"):
                return a, imm, br
    return None


def main():
    print(f"img={IMGPATH}\n=== CHECK 1: un-migrated per-slot adds vs their clamp (OOB hunt) ===")
    # our INJECTED code caves (helpers/stubs) legitimately embed base immediates in their A-fallback arms;
    # exclude the whole cave region [0x400d6400,0x400d7c00) so only REAL firmware sites are audited.
    CAVE_LO, CAVE_HI = off(0x400d6400), off(0x400d7c00)
    oob = []; safe = 0; walks = 0
    for k in range(2, len(IMG) - 4, 2):
        if CAVE_LO <= k - 2 < CAVE_HI:
            continue
        r = is_slot_add(k)
        if not r:
            continue
        kind, base = r
        instr_va = BASE + k - 2
        if kind == "lea":
            walks += 1
            continue
        c = nearest_clamp(instr_va)
        if c is None:
            # unclamped stock add reachable by any idx -> only safe if the helper self-bounds; but this is
            # a RAW add (not migrated) with NO clamp -> idx>=128 flows straight in -> OOB. Flag it.
            oob.append((instr_va, base, None, "NO CLAMP (unclamped raw add)"))
            continue
        cva, imm, br = c
        if imm >= 129:
            oob.append((instr_va, base, cva, f"clamp #{imm} OPEN"))
        elif imm == 128 and br == 0x62:
            # cmpi #128 + bhi bails only when idx > 128, so idx == 128 FALLS THROUGH into the
            # stock add -> SETTINGS-A[128] / STATE-A[128], one stride past the end of table A.
            # Stock-safe only because slot 128 is unreachable there; in the 256 build it IS reachable.
            oob.append((instr_va, base, cva, "clamp #128 + bhi (>) -- OFF-BY-ONE, idx=128 passes"))
        elif imm == 128 and br == 0x63:
            oob.append((instr_va, base, cva, "clamp #128 + bls -- branch polarity unclear, REVIEW"))
        else:
            safe += 1
    real = [x for x in oob if x[0] not in WHITELIST]
    wl = [x for x in oob if x[0] in WHITELIST]
    for va, base, cva, why in wl:
        print(f"  [reviewed-safe] add 0x{va:08x} ({SLOT_BASES[base]}) -- {WHITELIST[va]}")
    if real:
        for va, base, cva, why in real:
            cs = f"clamp 0x{cva:08x}" if cva else "no clamp"
            print(f"  [OOB?] add 0x{va:08x} ({SLOT_BASES[base]})  {cs}  {why}  <<< NEW -- investigate")
    else:
        print("  no NEW reachable OOB -- every un-migrated per-slot add is CLOSED-#128 or reviewed-safe.")
    print(f"  ({safe} un-migrated adds safely closed; {walks} lea walk-starts skipped; {len(wl)} whitelisted)")
    oob = real

    print("\n=== CHECK 3: raised-clamp branch consistency (idx=255 must pass) ===")
    # scan real firmware for cmpi.l/cmpa.l #255 or #256, check the branch type so idx=255 is NOT dropped:
    #   #255 must pair with bhi (0x62: bail if >255 -> 255 passes). bhs/bcc (0x64: >=255) would DROP 255.
    #   #256 pairs with bhs/bcc/bls (bail if >=256 -> 255 passes). bhi #256 lets 256 through (helper->A, ok).
    c3 = []
    for k in range(2, len(IMG) - 8, 2):
        if off(0x400d6400) <= k < off(0x400d7c00):
            continue
        w = int.from_bytes(IMG[k:k + 2], "big")
        is_cmpi = (w & 0xfff8) == 0x0c80
        is_cmpa = (w & 0xf1ff) == 0xb0fc
        if not (is_cmpi or is_cmpa):
            continue
        imm = int.from_bytes(IMG[k + 2:k + 6], "big")
        if imm not in (255, 256):
            continue
        br = IMG[k + 6]
        va = BASE + k
        if imm == 255 and br == 0x64:      # bhs/bcc with #255 -> drops slot 255
            c3.append((va, "cmp #255 + bhs/bcc -> DROPS idx=255 (should be bhi/#255 or bhs/#256)"))
        # (bhi #256 letting 256 through is harmless: helper maps >=256 to A.)
    if c3:
        for va, why in c3:
            print(f"  [BUG?] clamp 0x{va:08x}  {why}  <<< investigate")
    else:
        print("  none -- every raised #255/#256 clamp lets idx=255 through.")

    print("\n=== CHECK 2: helper family maps idx=255 within the reserve ===")
    # reuse verify_dual256's assembled helpers by calling them via emu would be ideal; here just report the
    # ADJ-derived B target for idx=255 per table and confirm it's in [RESERVE_LO,RESERVE_HI).
    tables = [("SETTINGS", 0x40a731e0, 0x448), ("SETTINGS+0x10e", 0x40a732ee, 0x448),
              ("STATE", 0x40ab63e0, 44), ("STRIDE4#1", 0x40ab8de0, 4), ("STRIDE4#2", 0x40ab8fe0, 4)]
    allok = True
    for name, adj, stride in tables:
        tgt = (adj + 255 * stride) & 0xffffffff
        ok = RESERVE_LO <= tgt < RESERVE_HI
        allok &= ok
        print(f"  [{'OK ' if ok else 'OOR'}] {name:16} idx=255 -> 0x{tgt:08x}")
    print("\n" + ("AUDIT CLEAN -- no reachable OOB per-slot add; all idx=255 targets in-reserve."
                  if (not oob and allok) else ">>> REVIEW the flagged items above <<<"))


if __name__ == "__main__":
    main()
