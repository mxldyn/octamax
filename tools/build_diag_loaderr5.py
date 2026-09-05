#!/usr/bin/env python3
"""build_diag_loaderr5.py -- MEASURING build v4 (fixes nothing). Successor to build_diag_loaderr4.py.

What v3 (P37) established on hardware:
  * B fired once, result -2, a2 = 0x460364e4 = entry 0 of the loader's 32 x 26 B request pool.
  * N1/N2 both zero -> neither direct `moveq #-2;rts` is involved. Clean negative, both leads dropped.
  * S: type=0 (STATIC) slot=139, four calls -> the slice function IS reached for the high slot and its
    STATE/SETTINGS resolutions are already migrated. (v3 also proved the P36 S records were type=1 FLEX
    recorders: the probe's fields are TYPE at sp@(4) and SLOT at sp@(8), not arg1/slot.)

`-2` is produced at four branch targets in the loader state machine (0x4008498c / 0x400849de /
0x40084a80 / 0x40084b20), reached by two identical guards:

    movel %fp@(-470),%d0 ; addql #1,%d0 ; beq -> -2       ; pointer == -1 (defensive, ~never true)
    movel %d0,%sp@-      ; jsr 0x40013db0 ; tstl %d0 ; ble -> -2

`0x40013db0` is **strlen** (`moveal sp@(4),a0 ; clrl d0 ; 1: addql #1,d0 ; tstb a0@(0,d0:l) ; bne 1b`),
so -2 means **the path string is EMPTY**. The pointer handed to strlen is the block's %a2, a per-slot
record whose offset 0 IS the path (the SETTINGS layout). Capturing it names table and slot outright:
  SET-A -> (p - 0x100d5b30) / 0x448        SET-B -> 128 + (p - SET_B) / 0x448

Probes:
  B  0x40022b50 (6 B) -> [result][caller_PC][a2]                  -- kept, the anchor
  G1 0x40084a12 (6 B) -> [strptr][a2][16 bytes of the string]     -- the strlen guard, block 1
  G2 0x40084ab8 (6 B) -> [strptr][a2][16 bytes of the string]     -- the strlen guard, block 2
G1/G2 replace a `jsr 0x40013db0`: the stub records, performs the same `jsr`, then jumps to the
instruction after the original call, so d0 (the strlen result) and the stack are unchanged.

PROBE 0x40ab65e0 = project.256 offset 0x21000:
    +0x00 magic 0x10ADE111  +0x04 cntB  +0x08 cntG1  +0x0c cntG2
    +0x20  B[i]  [result][callerPC][a2]     12 B x 8
    +0x80  G1[i] [strptr][a2][str16]        24 B x 8
    +0x140 G2[i] [strptr][a2][str16]        24 B x 8

DELETE <project>/project.256 before the run. The probe block overlaps ONE high slot -- printed below.

    python3 tools/build_diag_loaderr5.py    # -> out/mainos_diag_loaderr5.bin
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd

SRC = pathlib.Path("out/mainos_persist256.bin")
BASE_VA = 0x40000400
OUT = pathlib.Path("out/mainos_diag_loaderr5.bin")
CODE, PROBE = 0x400d7100, 0x40ab65e0
MAGIC = 0x10ade111

ASM = f"""    .cpu 5407
    .text
| ---- shared: allocate a ring entry.  in: d1=counter offset, d2=array offset, d3=entry size.
|      out: a1 = entry address, or 0 when the ring is full.  preserves d0. -------------------------
rec_alloc:
    lea     0x{PROBE:x},%a0
    movea.l #0x{MAGIC:x},%a1
    move.l  %a1,(%a0)
    adda.l  %d1,%a0
    move.l  (%a0),%d1
    cmpi.l  #8,%d1
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

| ---- shared: copy 16 bytes of the string at a0 to a1, NUL-padded. clobbers d1,d2,a0,a1. ----------
str16:
    moveq   #15,%d2
sc_loop:
    move.b  (%a0),%d1
    move.b  %d1,(%a1)
    addq.l  #1,%a1
    tst.b   %d1
    beq.b   sc_pad
    addq.l  #1,%a0
    subq.l  #1,%d2
    bpl.b   sc_loop
    rts
sc_pad:
    subq.l  #1,%d2
    bmi.b   sc_done
    move.b  #0,(%a1)
    addq.l  #1,%a1
    bra.b   sc_pad
sc_done:
    rts

| ============ B: 0x40022b50 `tstl sp@(4)` / `bge 0x40022b6e` -- record negatives =================
b_probe:
    lea     -24(%sp),%sp                | orig sp@(0)->24(%sp), sp@(4)->28(%sp)
    movem.l %d0-%d3/%a0-%a1,(%sp)
    move.l  28(%sp),%d0                 | result
    tst.l   %d0
    bge.b   1f
    moveq   #4,%d1
    moveq   #0x20,%d2
    moveq   #12,%d3
    bsr.w   rec_alloc
    move.l  %a1,%d1
    tst.l   %d1
    beq.b   1f
    move.l  %d0,(%a1)
    move.l  24(%sp),%d0
    move.l  %d0,4(%a1)
    move.l  %a2,8(%a1)
1:  movem.l (%sp),%d0-%d3/%a0-%a1
    lea     24(%sp),%sp
    tst.l   4(%sp)
    bge.b   2f
    jmp     0x40022b56
2:  jmp     0x40022b6e

| ==== G1: replaces `jsr 0x40013db0` at 0x40084a12. At entry sp@(0) = the string pointer. =========
g1_probe:
    lea     -24(%sp),%sp
    movem.l %d0-%d3/%a0-%a1,(%sp)
    moveq   #8,%d1
    move.l  #0x80,%d2
    moveq   #24,%d3
    bsr.w   rec_alloc
    move.l  %a1,%d0
    tst.l   %d0
    beq.b   1f
    move.l  24(%sp),%d0                 | the string pointer
    move.l  %d0,(%a1)
    move.l  %a2,4(%a1)
    tst.l   %d0
    beq.b   1f
    movea.l %d0,%a0
    lea     8(%a1),%a1
    bsr.w   str16
1:  movem.l (%sp),%d0-%d3/%a0-%a1
    lea     24(%sp),%sp
    jsr     0x40013db0
    jmp     0x40084a18

| ==== G2: replaces `jsr 0x40013db0` at 0x40084ab8. ==============================================
g2_probe:
    lea     -24(%sp),%sp
    movem.l %d0-%d3/%a0-%a1,(%sp)
    moveq   #12,%d1
    move.l  #0x140,%d2
    moveq   #24,%d3
    bsr.w   rec_alloc
    move.l  %a1,%d0
    tst.l   %d0
    beq.b   1f
    move.l  24(%sp),%d0
    move.l  %d0,(%a1)
    move.l  %a2,4(%a1)
    tst.l   %d0
    beq.b   1f
    movea.l %d0,%a0
    lea     8(%a1),%a1
    bsr.w   str16
1:  movem.l (%sp),%d0-%d3/%a0-%a1
    lea     24(%sp),%sp
    jsr     0x40013db0
    jmp     0x40084abe
"""

# (va, expected_bytes, symbol). The hole size comes FROM expected_bytes -- never hand-counted. P34/P35
# both bricked the unit because a "pad_nops=2" field meant two NOPs (4 bytes) where the 8-byte hole had
# room for one, clobbering the first half of the next instruction.
HOOKS = [
    (0x40022b50, "4aaf00046c18", "b_probe"),
    (0x40084a12, "4eb940013db0", "g1_probe"),
    (0x40084ab8, "4eb940013db0", "g2_probe"),
]


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC}")
    img = bytearray(SRC.read_bytes())
    p = "out/_lerr5"
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

    # A cave must be one the project has already PROVEN free at runtime -- "the bytes are zero in the
    # image" does not prove the OS never writes there (that is what BSS looks like).
    VALIDATED_CAVES = [(0x400d6a00, 0x400d6b00),   # P33D/P36 ran from here
                       (0x400d7100, 0x400d7400)]   # tail of the ALLOC_STUB cave; P37 ran from here
    if not any(lo <= CODE and CODE + len(blob) <= hi for lo, hi in VALIDATED_CAVES):
        sys.exit(f"REFUSING: [0x{CODE:08x},0x{CODE + len(blob):08x}) ({len(blob)} B) is not inside a "
                 f"validated cave {['0x%08x-0x%08x' % c for c in VALIDATED_CAVES]}.")
    assert not any(img[bd.off(CODE):bd.off(CODE) + len(blob)]), "cave not empty"
    img[bd.off(CODE):bd.off(CODE) + len(blob)] = blob
    base = bytes(SRC.read_bytes())
    for va, exp, name in HOOKS:
        o, hole = bd.off(va), len(exp) // 2
        got = bytes(img[o:o + hole]).hex()
        assert got == exp, f"{name}: expected {exp} at 0x{va:x}, got {got}"
        assert hole >= 6 and hole % 2 == 0, f"{name}: hole {hole} B cannot take a 6 B jmp"
        img[o:o + 6] = b"\x4e\xf9" + sym[name].to_bytes(4, "big")
        img[o + 6:o + hole] = b"\x4e\x71" * ((hole - 6) // 2)      # fill EXACTLY the hole
        print(f"  hook 0x{va:08x} -> {name:9} @0x{sym[name]:08x}  (hole {hole} B, {(hole - 6) // 2} nop)")
    # HARD INVARIANT: outside the hooks and the cave, the image must be byte-identical to its base.
    allowed = set()
    for va, exp, _ in HOOKS:
        allowed |= set(range(bd.off(va), bd.off(va) + len(exp) // 2))
    allowed |= set(range(bd.off(CODE), bd.off(CODE) + len(blob)))
    stray = [i for i in range(len(base)) if img[i] != base[i] and i not in allowed]
    if stray:
        sys.exit(f"REFUSING: {len(stray)} byte(s) changed outside the hooks/cave, first at "
                 f"0x{BASE_VA + stray[0]:08x}. A hook overran its instruction.")
    OUT.write_bytes(bytes(img))
    poff = PROBE - bd.SET_B
    bidx = poff // 0x448
    print(f"blob {len(blob)} B / cave {0x400d7400 - CODE} B; PROBE 0x{PROBE:08x} = project.256 offset 0x{poff:05x}")
    print(f"  probe block spans 0x{poff:05x}..0x{poff + 0x200:05x}; SET-B[{bidx}] spans "
          f"0x{bidx * 0x448:05x}..0x{(bidx + 1) * 0x448:05x}  ->  DO NOT USE UI SLOT {129 + bidx}")
    print(f"{OUT}: {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
