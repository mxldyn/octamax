#!/usr/bin/env python3
"""build_diag_loaderr4.py -- MEASURING build v3 (fixes nothing). Successor to build_diag_loaderr3.py.

What v2 (P36) actually measured on hardware:
  * probe B fired ONCE: result = -2, caller PC = 0x40062462 -- the return address of `jsr %a0@` at
    0x40062460, i.e. the generic message-pump case that does `a0 = a2@(2); push a2@(6); jsr a0@`.
    So the popup is driven by a message whose +2 == 0x40022b0c and whose +6 == -2.
  * probe A (finish_load 0x40022b70) never fired -> the STATIC branch of FUN_40028fec is NOT the path.
  * probe S was CONTAMINATED: the filter `slot >= 128` also matches the 8 RECORDER entries of the FLEX
    table (bound #135 all over the code). The ring filled with 128..135 twice during project load and
    had no room left for the slot under test. v3 filters `slot >= 136` -- so the HW test must use a
    STATIC slot >= 137 (UI numbering), NOT 130.

Why v3 exists: the literal 0x40022b0c is stored at exactly two places in the image, both at record+18
(0x460bd8fe by FUN_40022610, 0x460d1010 by FUN_40028fec), and there is no PC-relative reference to it
either. So the dispatched message is NOT one of those two records -- some generic code copies the
callback out of record+18 into a fresh "call fn with result" message at runtime. Static scanning cannot
name it. Probe B therefore also records %a2, which at callback entry still holds the pump's message
pointer: one long that identifies the poster outright.

Probes (all pure observers: record, then replay the instructions they replaced):
  B  0x40022b50 `tstl sp@(4)` + bge  -> [result][caller_PC][a2], only when NEGATIVE
  S  0x40099374 sampleslice entry    -> [slot][arg1][caller_PC], ONLY slot >= 136
  N1 0x400148d4 handle-validate entry-> [handle_ptr][caller_PC], ONLY when it would return -2
                                        (a0 == NULL, or (*a0)-1 >u 510 -- valid ids are 1..511)
  N2 0x4008fa68 path-classify entry   -> [caller_PC], ONLY when the path pointer is NULL (returns -2)
N1/N2 are the image's only two direct `moveq #-2 ; rts` returns; if neither fires, the -2 is computed
elsewhere and probe B's %a2 is the fallback that cannot miss.

PROBE 0x40ab65e0 sits in SETTINGS-B -> the sidecar dumps it to <project>/project.256 on SAVE.
  project.256 offset 0x21000:
    +0x00 magic 0x10ADE111  +0x04 cntB  +0x08 cntS  +0x0c cntN1  +0x10 cntN2
    +0x20 B[i]  [result][callerPC][a2]   12 B x 8
    +0x80 S[i]  [slot][arg1][callerPC]   12 B x 8
    +0xe0 N1[i] [handle][callerPC]        8 B x 8
    +0x120 N2[i][callerPC][0]             8 B x 8

DELETE <project>/project.256 before the run: sidecar_load restores it over SETTINGS-B and would bring
back the previous capture. The probe block overlaps ONE high slot's record -- the script prints which.

    python3 tools/build_diag_loaderr4.py    # -> out/mainos_diag_loaderr4.bin
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd

SRC = pathlib.Path("out/mainos_persist256.bin")
BASE_VA = 0x40000400
OUT = pathlib.Path("out/mainos_diag_loaderr4.bin")
CODE, PROBE = 0x400d7100, 0x40ab65e0
MAGIC = 0x10ade111

ASM = f"""    .cpu 5407
    .text
| ================= B: 0x40022b50 `tstl sp@(4)` / `bge 0x40022b6e` -- record negatives ===============
b_probe:
    lea     -20(%sp),%sp                | orig sp@(0)->20(%sp), sp@(4)->24(%sp)
    movem.l %d0-%d2/%a0-%a1,(%sp)
    move.l  24(%sp),%d0                 | result
    tst.l   %d0
    bge.b   1f
    lea     0x{PROBE:x},%a0
    move.l  #0x{MAGIC:x},%d1
    move.l  %d1,(%a0)
    move.l  4(%a0),%d1                  | cntB
    cmpi.l  #8,%d1
    bcc.b   1f
    addq.l  #1,4(%a0)
    move.l  %d1,%d2
    lsl.l   #1,%d2
    add.l   %d2,%d1
    lsl.l   #2,%d1                      | *12
    addi.l  #0x20,%d1
    lea     0x{PROBE:x},%a1
    adda.l  %d1,%a1
    move.l  %d0,(%a1)                   | result
    move.l  20(%sp),%d0                 | caller PC
    move.l  %d0,4(%a1)
    move.l  %a2,8(%a1)                  | pump's message pointer -- the whole point of v3
1:  movem.l (%sp),%d0-%d2/%a0-%a1
    lea     20(%sp),%sp
    tst.l   4(%sp)
    bge.b   2f
    jmp     0x40022b56
2:  jmp     0x40022b6e

| ============ S: sampleslice entry; sp@(4)=arg1, sp@(8)=slot; ONLY slot >= 136 ======================
sl_probe:
    lea     -20(%sp),%sp
    movem.l %d0-%d2/%a0-%a1,(%sp)
    move.l  28(%sp),%d0                 | slot
    cmpi.l  #136,%d0
    blo.b   2f
    lea     0x{PROBE:x},%a0
    move.l  #0x{MAGIC:x},%d1
    move.l  %d1,(%a0)
    move.l  8(%a0),%d1                  | cntS
    cmpi.l  #8,%d1
    bcc.b   2f
    addq.l  #1,8(%a0)
    move.l  %d1,%d2
    lsl.l   #1,%d2
    add.l   %d2,%d1
    lsl.l   #2,%d1                      | *12
    addi.l  #0x80,%d1
    lea     0x{PROBE:x},%a1
    adda.l  %d1,%a1
    move.l  %d0,(%a1)                   | slot
    move.l  24(%sp),%d0                 | arg1
    move.l  %d0,4(%a1)
    move.l  20(%sp),%d0                 | caller PC
    move.l  %d0,8(%a1)
2:  movem.l (%sp),%d0-%d2/%a0-%a1
    lea     20(%sp),%sp
    lea     -40(%sp),%sp
    movem.l %d2-%d7/%a2-%a5,(%sp)
    jmp     0x4009937c

| ==== N1: 0x400148d4 handle-validate; records only the paths that return -2 =========================
n1_probe:
    lea     -20(%sp),%sp
    movem.l %d0-%d2/%a0-%a1,(%sp)
    movea.l 24(%sp),%a0                 | handle ptr
    move.l  %a0,%d0
    tst.l   %d0
    beq.b   n1_rec                      | NULL -> -2
    move.l  (%a0),%d0
    subq.l  #1,%d0
    cmpi.l  #510,%d0
    bhi.b   n1_rec                      | id out of 1..511 -> -2
    bra.b   n1_out
n1_rec:
    lea     0x{PROBE:x},%a0
    move.l  #0x{MAGIC:x},%d1
    move.l  %d1,(%a0)
    move.l  12(%a0),%d1                 | cntN1
    cmpi.l  #8,%d1
    bcc.b   n1_out
    addq.l  #1,12(%a0)
    lsl.l   #3,%d1                      | *8
    addi.l  #0xe0,%d1
    lea     0x{PROBE:x},%a1
    adda.l  %d1,%a1
    move.l  24(%sp),%d0
    move.l  %d0,(%a1)                   | handle ptr
    move.l  20(%sp),%d0
    move.l  %d0,4(%a1)                  | caller PC
n1_out:
    movem.l (%sp),%d0-%d2/%a0-%a1
    lea     20(%sp),%sp
    movea.l 4(%sp),%a0
    tst.l   %a0
    beq.b   n1_null
    jmp     0x400148dc
n1_null:
    jmp     0x400148f6

| ==== N2: 0x4008fa68 path-classify; records only the NULL path (returns -2) =========================
n2_probe:
    lea     -16(%sp),%sp                | orig sp@(0)->16(%sp), sp@(4)->20(%sp)
    movem.l %d0-%d1/%a0-%a1,(%sp)
    movea.l 20(%sp),%a0
    tst.l   %a0
    bne.b   n2_out
    lea     0x{PROBE:x},%a0
    move.l  #0x{MAGIC:x},%d1
    move.l  %d1,(%a0)
    move.l  16(%a0),%d1                 | cntN2
    cmpi.l  #8,%d1
    bcc.b   n2_out
    addq.l  #1,16(%a0)
    lsl.l   #3,%d1
    addi.l  #0x120,%d1
    lea     0x{PROBE:x},%a1
    adda.l  %d1,%a1
    move.l  16(%sp),%d0
    move.l  %d0,(%a1)                   | caller PC
n2_out:
    movem.l (%sp),%d0-%d1/%a0-%a1
    lea     16(%sp),%sp
    movea.l 4(%sp),%a0
    tst.l   %a0
    bne.b   n2_ok
    jmp     0x4008fa70
n2_ok:
    jmp     0x4008fa74
"""

# (va, expected_bytes, symbol). The hole size comes FROM expected_bytes -- never hand-counted. P34/P35
# both bricked the unit because a "pad_nops=2" field meant two NOPs (4 bytes) where the 8-byte hole had
# room for one: the extra NOP clobbered the first half of the next instruction.
HOOKS = [
    (0x40022b50, "4aaf00046c18",     "b_probe"),
    (0x40099374, "4fefffd848d73cfc", "sl_probe"),
    (0x400148d4, "206f00044a88671a", "n1_probe"),
    (0x4008fa68, "206f00044a886604", "n2_probe"),
]


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC}")
    img = bytearray(SRC.read_bytes())
    p = "out/_lerr4"
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
    # image" does not prove the OS never writes there (that is what BSS looks like). P34 placed 326 B at
    # 0x400d6c00 on exactly that reasoning and bricked the unit.
    VALIDATED_CAVES = [(0x400d6a00, 0x400d6b00),   # P33D/P36 ran from here
                       (0x400d7100, 0x400d7400)]   # tail of the ALLOC_STUB cave [0x400d7000,0x400d7400)
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
    print(f"  probe block spans 0x{poff:05x}..0x{poff + 0x160:05x}; SET-B[{bidx}] spans "
          f"0x{bidx * 0x448:05x}..0x{(bidx + 1) * 0x448:05x}  ->  DO NOT USE UI SLOT {129 + bidx}")
    print(f"{OUT}: {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
