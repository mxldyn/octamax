#!/usr/bin/env python3
"""build_diag_bugA3.py -- BUG A scan probe. OFFSET-ROBUST: instead of reading one hardcoded field, it
SCANS the whole bank pattern/track region for the assigned high-slot value (159 = idx of UI slot 160)
at reload milestones. Offline/file analysis CONFIRMED: after a reload the value 159 is GONE from the
bank (the per-pattern tagged track array @0x8f1ad had track3 159 -> 0, others intact) => a load-side
validate zeroes idx>=128 track pointers. This locates WHEN in the reload it disappears.

  AS  hook 0x400795ba (assign): records [off=a0-*(0x46c82456)][value] -- reference only.
  M1  hook 0x400908ac (bulk STATIC load-loop, DURING project load): SCANS *(0x46c82456)+[0x8e000,0xa0000)
      for byte==159, records [count][first offset]. If 159 present here => the clear runs AFTER bulk-load;
      if absent => the clear runs BEFORE/AT bulk-load (bank-load / part-parse). Brackets vs the saved
      file (which already shows 159 absent after the full reload+save).

PROCEDURE: assign UI slot 160 to the SAME track, SAVE, RELOAD, (play), SAVE. Delete project.256 first.
Do NOT use UI slots 252/253.  Decode: read_probe --build build_diag_bugA3
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd
from hookcheck import check_holes

SRC = pathlib.Path("out/mainos_persist256.bin")
BASE_VA = 0x40000400
OUT = pathlib.Path("out/mainos_diag_bugA3.bin")
CODE, PROBE = 0x400d7100, 0x40ab65e0
MAGIC = 0x10ade111
BANKPTR = 0x46c82456
SCAN_LO, SCAN_LEN = 0x8e000, 0x12000        # covers per-pattern tagged arrays for patterns ~0..5

ASM = f"""    .cpu 5407
    .text
rec_alloc:
    lea     0x{PROBE:x},%a0
    movea.l #0x{MAGIC:x},%a1
    move.l  %a1,(%a0)
    adda.l  %d1,%a0
    move.l  (%a0),%d1
    cmp.l   %d0,%d1
    bcc.b   ra_full
    addq.l  #1,(%a0)
    muls.l  %d3,%d1
    add.l   %d2,%d1
    lea     0x{PROBE:x},%a1
    adda.l  %d1,%a1
    rts
ra_full:
    suba.l  %a1,%a1
    rts

| ==== WK: per-bank load/save worker 0x4009115c. Count invocations so M1 can tell if banks are already
|      loaded when the STATIC bulk-load runs. Displaced `moveal fp@(28),a2 ; clrl -(sp)` (6 bytes).
wk_probe:
    lea     0x{PROBE:x},%a1
    movea.l #0x{MAGIC:x},%a0
    move.l  %a0,(%a1)
    addq.l  #1,0x18(%a1)                | cntWK
    movea.l %fp@(28),%a2
    clr.l   -(%sp)
    jmp     0x4009116a

| ==== AS: assign. records [off][value] (reference).
as_probe:
    adda.l  #0x8f04a,%a0
    move.l  %a0,-(%sp)
    move.l  %d1,-(%sp)
    lea     -24(%sp),%sp
    movem.l %d0-%d3/%a0-%a1,(%sp)
    moveq   #8,%d0
    moveq   #4,%d1
    moveq   #0x40,%d2
    moveq   #12,%d3
    bsr.w   rec_alloc
    move.l  %a1,%d0
    tst.l   %d0
    beq.b   1f
    move.l  28(%sp),%d0
    movea.l #0x{BANKPTR:x},%a0
    sub.l   (%a0),%d0
    move.l  %d0,(%a1)
    move.l  24(%sp),%d0
    move.l  %d0,4(%a1)
1:  movem.l (%sp),%d0-%d3/%a0-%a1
    lea     24(%sp),%sp
    addq.l  #8,%sp
    jmp     0x400795c0

| ==== M1: bulk-load 0x400908ac. Scan bank for 159, record [count][first_off]. Then replicate
|      `movel d0,d2 ; addql #8,sp ; bge 0x400908d8`.
m1_probe:
    lea     -32(%sp),%sp
    movem.l %d0-%d5/%a0-%a1,(%sp)
    moveq   #8,%d0
    moveq   #8,%d1
    move.l  #0xa0,%d2
    moveq   #12,%d3
    bsr.w   rec_alloc
    move.l  %a1,%d0
    tst.l   %d0
    beq.b   1f
    | scan
    movea.l #0x{BANKPTR:x},%a0
    move.l  (%a0),%d0                   | bankbase
    movea.l %d0,%a0
    adda.l  #0x{SCAN_LO:x},%a0
    moveq   #0,%d2                      | count
    moveq   #-1,%d3                     | first off
    move.l  #0x{SCAN_LEN:x},%d1
scanlp:
    mvz.b   (%a0),%d4
    cmpi.l  #159,%d4
    bne.b   scannx
    addq.l  #1,%d2
    moveq   #-1,%d0
    cmp.l   %d0,%d3
    bne.b   scannx
    move.l  %a0,%d3                     | first hit (absolute; decoder subtracts SCAN base if needed)
scannx:
    addq.l  #1,%a0
    subq.l  #1,%d1
    bne.b   scanlp
    move.l  %d2,(%a1)                   | [0] count of 159
    | witness: is the bank loaded at M1? record the flat track0 long @bankbase+0x8f04a
    movea.l #0x{BANKPTR:x},%a0
    move.l  (%a0),%d0
    movea.l %d0,%a0
    adda.l  #0x8f04a,%a0
    move.l  (%a0),%d1
    move.l  %d1,4(%a1)                  | [4] long@0x8f04a (nonzero => bank loaded OR stale)
    lea     0x{PROBE:x},%a0
    move.l  0x18(%a0),%d1
    move.l  %d1,8(%a1)                  | [8] cntWK so far (>0 => banks loaded before bulk-load)
1:  movem.l (%sp),%d0-%d5/%a0-%a1
    lea     32(%sp),%sp
    move.l  %d0,%d2
    addq.l  #8,%sp
    bge.b   2f
    jmp     0x400908b2
2:  jmp     0x400908d8
"""

LAYOUT = {
    "AS": {"counter": 0x04, "array": 0x40, "entry": 12, "cap": 8,
           "fields": [("off", 0, "hex"), ("value", 4, "s32")]},
    "M1": {"counter": 0x08, "array": 0xa0, "entry": 12, "cap": 8,
           "fields": [("count_159", 0, "s32"), ("bank_witness_0x8f04a", 4, "hex"), ("cntWK_bankloads", 8, "s32")]},
}

HOOKS = [
    (0x400795ba, "d1fc0008f04a", "as_probe"),
    (0x400908ac, "2400508f6c26", "m1_probe"),
    (0x40091164, "246e001c42a7", "wk_probe"),
]


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC}")
    img = bytearray(SRC.read_bytes())
    p = "out/_bugA3"
    pathlib.Path(p + ".s").write_text(ASM)
    r = subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", p + ".o", p + ".s"], capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr)
    subprocess.run(["m68k-elf-ld", "-Ttext=0x%x" % CODE, "-o", p + ".elf", p + ".o"], capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", p + ".elf", p + ".bin"], check=True)
    blob = pathlib.Path(p + ".bin").read_bytes()
    nm = subprocess.run(["m68k-elf-nm", p + ".elf"], capture_output=True, text=True).stdout
    sym = {ln.split()[2]: int(ln.split()[0], 16) for ln in nm.splitlines() if len(ln.split()) == 3}
    for f in (".s", ".o", ".elf", ".bin"):
        pathlib.Path(p + f).unlink(missing_ok=True)
    VALIDATED_CAVES = [(0x400d6a00, 0x400d6b00), (0x400d7100, 0x400d7400)]
    if not any(lo <= CODE and CODE + len(blob) <= hi for lo, hi in VALIDATED_CAVES):
        sys.exit(f"REFUSING: cave overrun {len(blob)} B")
    assert not any(img[bd.off(CODE):bd.off(CODE) + len(blob)]), "cave not empty"
    img[bd.off(CODE):bd.off(CODE) + len(blob)] = blob
    base = bytes(SRC.read_bytes())
    check_holes(base, [(va, len(exp) // 2) for va, exp, _ in HOOKS])
    for va, exp, name in HOOKS:
        o, hole = bd.off(va), len(exp) // 2
        assert bytes(img[o:o + hole]).hex() == exp, f"{name}: bytes"
        img[o:o + 6] = b"\x4e\xf9" + sym[name].to_bytes(4, "big")
        img[o + 6:o + hole] = b"\x4e\x71" * ((hole - 6) // 2)
        print(f"  hook 0x{va:08x} -> {name:9} @0x{sym[name]:08x}")
    allowed = set(range(bd.off(CODE), bd.off(CODE) + len(blob)))
    for va, exp, _ in HOOKS:
        allowed |= set(range(bd.off(va), bd.off(va) + len(exp) // 2))
    stray = [i for i in range(len(base)) if img[i] != base[i] and i not in allowed]
    if stray:
        sys.exit(f"REFUSING: stray at 0x{BASE_VA+stray[0]:08x}")
    OUT.write_bytes(bytes(img))
    print(f"blob {len(blob)} B; scan *(0x{BANKPTR:x})+[0x{SCAN_LO:x},0x{SCAN_LO+SCAN_LEN:x}) for 159")
    print("  -> DO NOT USE UI SLOTS 252, 253")
    print(f"{OUT}: {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
