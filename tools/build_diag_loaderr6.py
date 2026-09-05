#!/usr/bin/env python3
"""build_diag_loaderr6.py -- MEASURING build v5 (fixes nothing). Successor to build_diag_loaderr5.py.

P38 result: B fired (-2, same pool entry 0x460364e4) but **G1 and G2 recorded nothing**. Those two
probes sat on the strlen guards of only two of the FOUR `-2` exits, so they proved the error does not
come from 0x40084a80 / 0x40084b20 -- and nothing more. Instrumenting guards was the wrong choice:
there are four exits, reached by six different branches, and only two shared the strlen shape.

v5 instruments **the error sites themselves**. Whichever one fires, it records the record pointer that
block is working on plus the first 32 raw bytes of that record, so the table and slot fall out:
    SET-A -> (p-0x100d5b30)/0x448 ; SET-B -> 128+(p-SET_B)/0x448 ; STATE-A/B likewise.

  E1 0x4008498c (hole 10) rec = %a2            replay: moveq #-2,d0 ; clr.l 270(a2) ; -> 0x40084e70
  E2 0x400849de (hole 12) rec = %a2            replay: moveq #-2,d0 ; clr.l 522(a2) ;
                                                       push d0 ; push 530(a2) ; -> 0x400849ea
  E3 0x40084a80 (hole 10) rec = -470(%fp)      replay: moveq #-2,d2 ; a0=-470(fp) ; clr.l 262(a0)
                                                       -> 0x40084a8a
  E4 0x40084b20 (hole 10) rec = -482(%fp)      replay: moveq #-2,d2 ; a0=-482(fp) ; clr.l 526(a0)
                                                       -> 0x40084b2a
  B  0x40022b50 (hole 6)  -> [result][caller_PC][a2]   -- kept as the anchor: proves the popup fired

Each stub records BEFORE replaying, and every replay reproduces the replaced instructions exactly,
including the two that leave values live across the hook (E3/E4 set d2 and a0 AFTER the register
restore, since the restore would otherwise clobber them).

PROBE 0x40ab65e0 = project.256 offset 0x21000:
    +0x00 magic 0x10ADE111  +0x04 cntB  +0x08 cntE
    +0x20 B[i] [result][callerPC][a2]        12 B x 8
    +0x80 E[i] [site][rec][32 raw bytes]     40 B x 8

DELETE <project>/project.256 before the run. The probe block overlaps ONE high slot -- printed below.

    python3 tools/build_diag_loaderr6.py    # -> out/mainos_diag_loaderr6.bin
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd

SRC = pathlib.Path("out/mainos_persist256.bin")
BASE_VA = 0x40000400
OUT = pathlib.Path("out/mainos_diag_loaderr6.bin")
CODE, PROBE = 0x400d7100, 0x40ab65e0
MAGIC = 0x10ade111

ASM = f"""    .cpu 5407
    .text
| ---- allocate a ring entry. in d1=counter offset, d2=array offset, d3=entry size. out a1 (0=full).
|      preserves d0. ------------------------------------------------------------------------------
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

| ---- record one error site. in d0 = site id, a0 = record pointer. -------------------------------
rec_err:
    move.l  %a0,-(%sp)
    moveq   #8,%d1
    move.l  #0x80,%d2
    moveq   #40,%d3
    bsr.w   rec_alloc
    movea.l (%sp)+,%a0
    move.l  %a1,%d1
    tst.l   %d1
    beq.b   re_out
    move.l  %d0,(%a1)                   | site id
    move.l  %a0,4(%a1)                  | the record pointer -- this names the slot
    move.l  %a0,%d0
    tst.l   %d0
    beq.b   re_out
    lea     8(%a1),%a1
    moveq   #31,%d2
re_copy:
    move.b  (%a0)+,(%a1)+
    subq.l  #1,%d2
    bpl.b   re_copy
re_out:
    rts

| ================= B: 0x40022b50 -- the anchor ==================================================
b_probe:
    lea     -24(%sp),%sp
    movem.l %d0-%d3/%a0-%a1,(%sp)
    move.l  28(%sp),%d0
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

| ================= E1: 0x4008498c ===============================================================
e1_probe:
    lea     -24(%sp),%sp
    movem.l %d0-%d3/%a0-%a1,(%sp)
    moveq   #1,%d0
    movea.l %a2,%a0
    bsr.w   rec_err
    movem.l (%sp),%d0-%d3/%a0-%a1
    lea     24(%sp),%sp
    moveq   #-2,%d0
    clr.l   270(%a2)
    jmp     0x40084e70

| ================= E2: 0x400849de ===============================================================
e2_probe:
    lea     -24(%sp),%sp
    movem.l %d0-%d3/%a0-%a1,(%sp)
    moveq   #2,%d0
    movea.l %a2,%a0
    bsr.w   rec_err
    movem.l (%sp),%d0-%d3/%a0-%a1
    lea     24(%sp),%sp
    moveq   #-2,%d0
    clr.l   522(%a2)
    move.l  %d0,-(%sp)
    move.l  530(%a2),-(%sp)
    jmp     0x400849ea

| ================= E3: 0x40084a80 ===============================================================
e3_probe:
    lea     -24(%sp),%sp
    movem.l %d0-%d3/%a0-%a1,(%sp)
    moveq   #3,%d0
    movea.l -470(%a6),%a0
    bsr.w   rec_err
    movem.l (%sp),%d0-%d3/%a0-%a1
    lea     24(%sp),%sp
    moveq   #-2,%d2
    movea.l -470(%a6),%a0
    clr.l   262(%a0)
    jmp     0x40084a8a

| ================= E4: 0x40084b20 ===============================================================
e4_probe:
    lea     -24(%sp),%sp
    movem.l %d0-%d3/%a0-%a1,(%sp)
    moveq   #4,%d0
    movea.l -482(%a6),%a0
    bsr.w   rec_err
    movem.l (%sp),%d0-%d3/%a0-%a1
    lea     24(%sp),%sp
    moveq   #-2,%d2
    movea.l -482(%a6),%a0
    clr.l   526(%a0)
    jmp     0x40084b2a
"""

# (va, expected_bytes, symbol). The hole size comes FROM expected_bytes -- never hand-counted.
HOOKS = [
    (0x40022b50, "4aaf00046c18",             "b_probe"),
    (0x4008498c, "70fe42aa010e600004dc",     "e1_probe"),
    (0x400849de, "70fe42aa020a2f002f2a0212", "e2_probe"),
    (0x40084a80, "74fe206efe2a42a80106",     "e3_probe"),
    (0x40084b20, "74fe206efe1e42a8020e",     "e4_probe"),
]


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC}")
    img = bytearray(SRC.read_bytes())
    p = "out/_lerr6"
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

    VALIDATED_CAVES = [(0x400d6a00, 0x400d6b00),   # P33D/P36 ran from here
                       (0x400d7100, 0x400d7400)]   # P37/P38 ran from here
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
        print(f"  hook 0x{va:08x} -> {name:9} @0x{sym[name]:08x}  (hole {hole:2} B, {(hole - 6) // 2} nop)")
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
    print(f"  probe block spans 0x{poff:05x}..0x{poff + 0x1c0:05x}; SET-B[{bidx}] spans "
          f"0x{bidx * 0x448:05x}..0x{(bidx + 1) * 0x448:05x}  ->  DO NOT USE UI SLOT {129 + bidx}")
    print(f"{OUT}: {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
