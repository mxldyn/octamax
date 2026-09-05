#!/usr/bin/env python3
"""build_diag_loaderr7.py -- MEASURING build v6 (fixes nothing). WIDE instrumentation: every open
question in one flash, so we stop trading a flash cycle per hypothesis.

P38 taught the lesson this build applies: probing GUARDS is fragile (G1/G2 sat on two of four -2 exits
and recorded nothing, proving only a negative). Probe the SITES and the DECISION POINTS instead.

Probes (all pure observers; each replays the exact instructions it replaced):
  B  0x40022b50 (6)  popup emitter        -> [result][callerPC][a2]
  E1 0x4008498c (10) -2 exit #1, rec=a2   -> [site][rec][32 raw bytes of rec]
  E2 0x400849de (12) -2 exit #2, rec=a2   -> same
  E3 0x40084a80 (10) -2 exit #3, rec=-470(fp)
  E4 0x40084b20 (10) -2 exit #4, rec=-482(fp)
  L  0x400908ac (6)  STATIC bulk load-loop outcome, ONLY slot >= 128
                     -> [slot][result][pathptr][16 bytes of the path]   + cntLall counts every pass
  C  0x400993d8 (6)  slice fn decision point, ONLY type==0 && slot >= 128
                     -> [type][slot][STATE@8][STATE@20]
  A  0x4006db38 (6)  AED "has content?" predicate, ONLY slot >= 128 -> [slot][STATE@8][type]

Why C and A matter: at 0x400993d8 the slice function proceeds only if STATE@8 == 0, or if @8 == 2 AND
the third argument is non-zero. P37 showed the call comes from the wrapper at 0x40099680, which passes
**flag = 0** -- so a high slot whose @8 is anything but 0 BAILS to 0x4009965e and draws no slices.
`@8` is the occupancy enum: 1 == FREE (allocator 0x400240a2), 0 == HAS CONTENT (AED 0x4006db38).
C reads it at the exact instruction that decides, and A reads what the AED concludes.

L is the highest-yield probe: for every slot the bulk loader attempts it records the slot, the load
result and the path, which shows at once whether high slots are attempted, with what path, and what
they return. Its own log strings are 0x400b7933 "Couldn't load STATIC[%d] with '%s' (%s)" and
0x400b8af1 "Successfully loaded STATIC[%d] with '%s'".

PROBE 0x40ab65e0 = project.256 offset 0x21000 (1008 B, fits inside ONE high slot's record):
    +0x000 magic  +0x004 cntB  +0x008 cntE  +0x00c cntL  +0x010 cntC  +0x014 cntA  +0x018 cntLall
    +0x020 B[8]  [result][callerPC][a2]                     12 B
    +0x080 E[8]  [site][rec][32 raw bytes]                  40 B
    +0x1c0 L[12] [slot][result][pathptr][str16]             28 B
    +0x310 C[8]  [type][slot][state8][state20]              16 B
    +0x390 A[8]  [slot][state8][type]                       12 B

DELETE <project>/project.256 before the run. The probe block overlaps ONE high slot -- printed below.

    python3 tools/build_diag_loaderr7.py    # -> out/mainos_diag_loaderr7.bin
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd

SRC = pathlib.Path("out/mainos_persist256.bin")
BASE_VA = 0x40000400
OUT = pathlib.Path("out/mainos_diag_loaderr7.bin")
CODE, PROBE = 0x400d7100, 0x40ab65e0
MAGIC = 0x10ade111
IDX_G, TYPE_G = 0x46c8d19c, 0x46c8d1a0      # AED "current slot" / "current machine type" globals

ASM = f"""    .cpu 5407
    .text
| ---- allocate a ring entry. in d1=counter offset, d2=array offset, d3=entry size; ring depth in d0
|      is fixed per array via the caller's cap. out a1 (0 = full). preserves d0. -------------------
| cap is passed in the high half of d1? no -- keep it simple: a separate cap register is not needed
| because every ring here is 8 deep except L which is 12; rec_alloc takes the cap in %d0 and returns
| the entry in %a1, so callers must not rely on d0 afterwards.
rec_alloc:                                  | in d0=cap, d1=cnt off, d2=arr off, d3=size -> a1
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

| ---- copy d2+1 bytes from a0 to a1 --------------------------------------------------------------
rawcopy:
    move.b  (%a0)+,(%a1)+
    subq.l  #1,%d2
    bpl.b   rawcopy
    rts

| ---- record one -2 error site. in d0 = site id, a0 = record pointer. ----------------------------
rec_err:
    move.l  %a0,-(%sp)
    move.l  %d0,-(%sp)
    moveq   #8,%d0
    moveq   #8,%d1
    move.l  #0x80,%d2
    moveq   #40,%d3
    bsr.w   rec_alloc
    move.l  (%sp)+,%d0
    movea.l (%sp)+,%a0
    move.l  %a1,%d1
    tst.l   %d1
    beq.b   re_out
    move.l  %d0,(%a1)
    move.l  %a0,4(%a1)
    move.l  %a0,%d0
    tst.l   %d0
    beq.b   re_out
    lea     8(%a1),%a1
    moveq   #31,%d2
    bsr.w   rawcopy
re_out:
    rts

| ================= B: 0x40022b50 -- popup emitter ===============================================
b_probe:
    lea     -24(%sp),%sp
    movem.l %d0-%d3/%a0-%a1,(%sp)
    move.l  28(%sp),%d0
    tst.l   %d0
    bge.b   1f
    move.l  %d0,-(%sp)
    moveq   #8,%d0
    moveq   #4,%d1
    moveq   #0x20,%d2
    moveq   #12,%d3
    bsr.w   rec_alloc
    move.l  (%sp)+,%d0
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

| ================= E1..E4: the four -2 exits ====================================================
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

| ==== L: 0x400908ac -- bulk load-loop outcome. d3=slot, d0=result, a2=SETTINGS (path at +0). =====
|      saved frame: d0@0 d1@4 d2@8 d3@12 a0@16 a1@20
l_probe:
    lea     -24(%sp),%sp
    movem.l %d0-%d3/%a0-%a1,(%sp)
    lea     0x{PROBE:x},%a0             | every pass counts, filtered or not
    movea.l #0x{MAGIC:x},%a1
    move.l  %a1,(%a0)
    addq.l  #1,24(%a0)
    move.l  12(%sp),%d0                 | slot (saved d3)
    cmpi.l  #128,%d0
    blo.b   1f
    moveq   #12,%d0
    moveq   #12,%d1
    move.l  #0x1c0,%d2
    moveq   #28,%d3
    bsr.w   rec_alloc
    move.l  %a1,%d0
    tst.l   %d0
    beq.b   1f
    move.l  12(%sp),%d0
    move.l  %d0,(%a1)                   | slot
    move.l  (%sp),%d0
    move.l  %d0,4(%a1)                  | result
    move.l  %a2,8(%a1)                  | path pointer -> names the table and slot
    movea.l %a2,%a0
    lea     12(%a1),%a1
    moveq   #15,%d2
    bsr.w   rawcopy
1:  movem.l (%sp),%d0-%d3/%a0-%a1
    lea     24(%sp),%sp
    move.l  %d0,%d2
    addq.l  #8,%sp
    bge.b   2f
    jmp     0x400908b2
2:  jmp     0x400908d8

| ==== C: 0x400993d8 -- slice fn decision point. a4=type, d7=slot, a0=STATE. =====================
c_probe:
    lea     -24(%sp),%sp
    movem.l %d0-%d3/%a0-%a1,(%sp)
    move.l  %a4,%d0
    tst.l   %d0
    bne.b   1f                          | only STATIC (type == 0)
    cmpi.l  #128,%d7
    blo.b   1f
    moveq   #8,%d0
    moveq   #16,%d1
    move.l  #0x310,%d2
    moveq   #16,%d3
    bsr.w   rec_alloc
    move.l  %a1,%d0
    tst.l   %d0
    beq.b   1f
    move.l  %a4,(%a1)                   | type
    move.l  %d7,4(%a1)                  | slot
    movea.l 16(%sp),%a0                 | the STATE pointer (saved a0)
    move.l  8(%a0),%d0
    move.l  %d0,8(%a1)                  | STATE@8  -- 0 proceeds, anything else bails
    move.l  20(%a0),%d0
    move.l  %d0,12(%a1)                 | STATE@20 -- the slice-table pointer
1:  movem.l (%sp),%d0-%d3/%a0-%a1
    lea     24(%sp),%sp
    move.l  8(%a0),%d0
    beq.b   2f
    jmp     0x400993de
2:  jmp     0x400993f2

| ==== A: 0x4006db38 -- AED "has content?" predicate. a0=STATE; slot/type from globals. ==========
a_probe:
    lea     -24(%sp),%sp
    movem.l %d0-%d3/%a0-%a1,(%sp)
    move.l  0x{IDX_G:x},%d0
    cmpi.l  #128,%d0
    blo.b   1f
    moveq   #8,%d0
    moveq   #20,%d1
    move.l  #0x390,%d2
    moveq   #12,%d3
    bsr.w   rec_alloc
    move.l  %a1,%d0
    tst.l   %d0
    beq.b   1f
    move.l  0x{IDX_G:x},%d0
    move.l  %d0,(%a1)                   | slot
    movea.l 16(%sp),%a0
    move.l  8(%a0),%d0
    move.l  %d0,4(%a1)                  | STATE@8
    move.l  0x{TYPE_G:x},%d0
    move.l  %d0,8(%a1)                  | type
1:  movem.l (%sp),%d0-%d3/%a0-%a1
    lea     24(%sp),%sp
    move.l  8(%a0),%d0
    addq.l  #8,%sp
    jmp     0x4006db3e
"""

HOOKS = [
    (0x40022b50, "4aaf00046c18",             "b_probe"),
    (0x4008498c, "70fe42aa010e600004dc",     "e1_probe"),
    (0x400849de, "70fe42aa020a2f002f2a0212", "e2_probe"),
    (0x40084a80, "74fe206efe2a42a80106",     "e3_probe"),
    (0x40084b20, "74fe206efe1e42a8020e",     "e4_probe"),
    (0x400908ac, "2400508f6c26",             "l_probe"),
    (0x400993d8, "202800086714",             "c_probe"),
    (0x4006db38, "20280008508f",             "a_probe"),
]


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC}")
    img = bytearray(SRC.read_bytes())
    p = "out/_lerr7"
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
        img[o + 6:o + hole] = b"\x4e\x71" * ((hole - 6) // 2)
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
    hi_idx = (poff + 0x3f0 - 1) // 0x448
    slots = list(range(129 + bidx, 129 + hi_idx + 1))
    print(f"  probe block spans 0x{poff:05x}..0x{poff + 0x3f0:05x} = SET-B[{bidx}..{hi_idx}]  ->  "
          f"DO NOT USE UI SLOT{'S' if len(slots) > 1 else ''} {', '.join(map(str, slots))}")
    print(f"{OUT}: {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
