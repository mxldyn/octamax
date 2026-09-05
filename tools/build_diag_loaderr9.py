#!/usr/bin/env python3
"""build_diag_loaderr9.py -- MEASURING build v8 (fixes nothing). WIDE instrumentation: every open
question in one flash, so we stop trading a flash cycle per hypothesis.

P38 taught the lesson this build applies: probing GUARDS is fragile (G1/G2 sat on two of four -2 exits
and recorded nothing, proving only a negative). Probe the SITES and the DECISION POINTS instead.

Probes (all pure observers; each replays the exact instructions it replaced):
  B  0x40022b50 (6)  popup emitter        -> [result][callerPC][a2]
  X  0x40013db0 (6)  strlen, ONLY when the caller PC is inside the loader [0x40084800,0x40084c00)
                     -> [callerPC][strptr][16 bytes of the string]
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
    +0x000 magic  +0x004 cntB  +0x008 cntX  +0x00c cntL  +0x010 cntC  +0x014 cntA  +0x018 cntLall
    +0x004 cntB  +0x00c cntL  +0x010 cntS1  +0x014 cntE  +0x018 cntLall  +0x01c cntP
    +0x020 B[8]   [result][callerPC][a2]                    12 B
    +0x080 L[12]  [slot][result][pathptr][str16]            28 B
    +0x1d0 P[8]   [slot][type][handle]                      12 B   -- .ot parser invoked?
    +0x230 S1[8]  [SETTINGS ptr]                             8 B   -- slice loop completed?
    +0x270 E[8]   [result][SETTINGS ptr]                     8 B   -- parser exit result

DELETE <project>/project.256 before the run. The probe block overlaps ONE high slot -- printed below.

    python3 tools/build_diag_loaderr9.py    # -> out/mainos_diag_loaderr9.bin
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd
from hookcheck import check_holes

SRC = pathlib.Path("out/mainos_persist256.bin")
BASE_VA = 0x40000400
OUT = pathlib.Path("out/mainos_diag_loaderr9.bin")
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

| ==== P: 0x40089940 = the .ot sidecar parser, FUN(handle, type, slot). ONLY slot >= 128.
|      Entry args: sp@(4)=handle sp@(8)=type sp@(12)=slot. Answers "was it invoked for this slot".
p_probe:
    lea     -24(%sp),%sp
    movem.l %d0-%d3/%a0-%a1,(%sp)
    move.l  36(%sp),%d0                 | slot
    cmpi.l  #128,%d0
    blo.b   1f
    moveq   #8,%d0
    moveq   #28,%d1
    move.l  #0x1d0,%d2
    moveq   #12,%d3
    bsr.w   rec_alloc
    move.l  %a1,%d0
    tst.l   %d0
    beq.b   1f
    move.l  36(%sp),%d0
    move.l  %d0,(%a1)                   | slot
    move.l  32(%sp),%d0
    move.l  %d0,4(%a1)                  | type
    move.l  28(%sp),%d0
    move.l  %d0,8(%a1)                  | file handle
1:  movem.l (%sp),%d0-%d3/%a0-%a1
    lea     24(%sp),%sp
    lea     -20(%sp),%sp
    movem.l %d2-%d4/%a2-%a3,(%sp)
    jmp     0x40089948

| ==== S1: 0x40089d16 -- reached ONLY after the 64 x 12 B slice loop completes. d3 = SETTINGS ptr,
|      which names the slot. Answers "did the slice loop run to the end for this slot".
s1_probe:
    lea     -24(%sp),%sp
    movem.l %d0-%d3/%a0-%a1,(%sp)
    move.l  12(%sp),%d0                 | saved d3 = SETTINGS pointer
    cmpi.l  #0x40a955e0,%d0
    blo.b   1f
    moveq   #8,%d0
    moveq   #16,%d1
    move.l  #0x230,%d2
    moveq   #8,%d3
    bsr.w   rec_alloc
    move.l  %a1,%d0
    tst.l   %d0
    beq.b   1f
    move.l  12(%sp),%d0
    move.l  %d0,(%a1)                   | SETTINGS pointer -> the slot
1:  movem.l (%sp),%d0-%d3/%a0-%a1
    lea     24(%sp),%sp
    movea.l %d3,%a2
    lea     1092(%a2),%a2
    jmp     0x40089d1c

| ==== E: 0x40089d7a -- the parser's single exit. d0 = result (1 ok / 0 fail), d3 still = SETTINGS.
|      Answers "with what result did it leave". d0 MUST survive: it is the return value.
e_probe:
    lea     -24(%sp),%sp
    movem.l %d0-%d3/%a0-%a1,(%sp)
    move.l  12(%sp),%d0                 | saved d3
    cmpi.l  #0x40a955e0,%d0
    blo.b   1f
    moveq   #8,%d0
    moveq   #20,%d1
    move.l  #0x270,%d2
    moveq   #8,%d3
    bsr.w   rec_alloc
    move.l  %a1,%d0
    tst.l   %d0
    beq.b   1f
    move.l  (%sp),%d0                   | saved d0 = the result
    move.l  %d0,(%a1)
    move.l  12(%sp),%d0
    move.l  %d0,4(%a1)                  | SETTINGS pointer -> the slot
1:  movem.l (%sp),%d0-%d3/%a0-%a1
    lea     24(%sp),%sp
    movem.l (%sp),%d2-%d4/%a2-%a3
    lea     20(%sp),%sp
    jmp     0x40089d82

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
    move.l  #0x80,%d2
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

"""

HOOKS = [
    (0x40022b50, "4aaf00046c18",             "b_probe"),
    (0x40089940, "4fefffec48d70c1c",         "p_probe"),
    (0x40089d16, "244345ea0444",             "s1_probe"),
    (0x40089d7a, "4cd70c1c4fef0014",         "e_probe"),
    (0x400908ac, "2400508f6c26",             "l_probe"),
]


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC}")
    img = bytearray(SRC.read_bytes())
    p = "out/_lerr9"
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
    # HARD GATE: a hook hole must be entered ONLY at its first address. P39 shipped four holes whose
    # second instruction was a separate branch target and threw VEC:04 at 0x4008498e on hardware.
    check_holes(base, [(va, len(exp) // 2) for va, exp, _ in HOOKS])
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
    hi_idx = (poff + 0x2b0 - 1) // 0x448
    slots = list(range(129 + bidx, 129 + hi_idx + 1))
    print(f"  probe block spans 0x{poff:05x}..0x{poff + 0x2b0:05x} = SET-B[{bidx}..{hi_idx}]  ->  "
          f"DO NOT USE UI SLOT{'S' if len(slots) > 1 else ''} {', '.join(map(str, slots))}")
    print(f"{OUT}: {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
