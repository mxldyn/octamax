#!/usr/bin/env python3
"""build_diag_loaderr2.py -- MEASURING build v2 (fixes nothing). Replaces build_diag_loaderr.py, whose
two probes both missed:
  * it hooked finish_load 0x40022b70, but "SAMPLE LOAD ERRORS!" has TWO emit sites and the run showed
    err_count == 0 -- so either the other site fired or the error was never triggered. v2 instruments
    BOTH, right where the result value is still live (not at a function entry).
  * the slice ring had no filter, so it filled with 16 LOW slots during the project load at boot and had
    no room left for the high slot under test. v2 records a slice call ONLY when slot >= 128.

Probes (all pure observers: record, then replay the instructions they replaced):
  A  finish_load 0x40022b70 entry      -> [caller_PC][result]         (kept; its magic proves it ran)
  B  0x40022b50 `tstl sp@(4)` + bge    -> [result][caller_PC], only when NEGATIVE. CONFIRMED to be
     the live emitter: the v1 run showed the popup on screen while probe A's magic stayed unwritten,
     so finish_load 0x40022b70 is NOT the path. Its function starts at 0x40022b0c -- a sibling of
     finish_load running the same UI-refresh sequence, taking the result in arg1.
  C  0x40022be0 `tstl d2`    + bge     -> [result]  recorded only when NEGATIVE
  S  sampleslice 0x40099374 entry      -> [slot][arg1]  ONLY for slot >= 128

PROBE 0x40ab65e0 sits in SETTINGS-B -> the sidecar dumps it to <project>/project.256 on SAVE.
  project.256 offset 0x21000:
    +0x00 magic 0x10ADE111  +0x04 cntA  +0x08 cntB  +0x0c cntC  +0x10 cntS
    +0x20 A[i] [PC][result] 8B x8   +0x60 B[i] [result] 8B x8
    +0xa0 C[i] [result] 8B x8       +0xe0 S[i] [slot][arg1] 8B x16

DELETE <project>/project.256 before the run: sidecar_load restores it over SETTINGS-B and would bring
back the previous capture (the probe block's first byte is the magic, so skip-empty treats it as a
populated slot). Do not use slot 247 -- the probe overlaps its record.

    python3 tools/build_diag_loaderr2.py    # -> out/mainos_diag_loaderr2.bin
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd

SRC = pathlib.Path("out/mainos_persist256.bin")
OUT = pathlib.Path("out/mainos_diag_loaderr2.bin")
CODE, PROBE = 0x400d6c00, 0x40ab65e0
MAGIC = 0x10ade111

ASM = f"""    .cpu 5407
    .text
| ---- A: finish_load(result); entry sp@(0)=caller PC, sp@(4)=result -------------------------------
fl_probe:
    move.l  %d0,-(%sp)
    move.l  %a0,-(%sp)
    lea     0x{PROBE:x},%a0
    move.l  #0x{MAGIC:x},%d0
    move.l  %d0,(%a0)
    move.l  4(%a0),%d0
    cmpi.l  #8,%d0
    bcc.b   1f
    addq.l  #1,4(%a0)
    lsl.l   #3,%d0
    addi.l  #0x20,%d0
    add.l   %d0,%a0
    move.l  8(%sp),%d0
    move.l  %d0,(%a0)
    move.l  12(%sp),%d0
    move.l  %d0,4(%a0)
1:  move.l  (%sp)+,%a0
    move.l  (%sp)+,%d0
    move.l  %d2,-(%sp)
    move.l  8(%sp),%d2
    jmp     0x40022b76

| ---- B: 0x40022b50 tstl sp@(4) / bge 0x40022b6e ; record only negatives -------------------------
b_probe:
    move.l  %d0,-(%sp)
    move.l  %a0,-(%sp)
    move.l  12(%sp),%d0
    tst.l   %d0
    bge.b   1f
    lea     0x{PROBE:x},%a0
    move.l  #0x{MAGIC:x},%d0
    move.l  %d0,(%a0)
    move.l  8(%a0),%d0
    cmpi.l  #8,%d0
    bcc.b   1f
    addq.l  #1,8(%a0)
    lsl.l   #3,%d0
    addi.l  #0x60,%d0
    add.l   %d0,%a0
    move.l  12(%sp),%d0
    move.l  %d0,(%a0)               | result code
    move.l  8(%sp),%d0              | original sp@(0) = PC of whoever invoked this callback
    move.l  %d0,4(%a0)
1:  move.l  (%sp)+,%a0
    move.l  (%sp)+,%d0
    tst.l   4(%sp)
    bge.b   2f
    jmp     0x40022b56
2:  jmp     0x40022b6e

| ---- C: 0x40022be0 tstl d2 / bge 0x40022bfc ; record only negatives -----------------------------
c_probe:
    move.l  %d0,-(%sp)
    move.l  %a0,-(%sp)
    tst.l   %d2
    bge.b   1f
    lea     0x{PROBE:x},%a0
    move.l  #0x{MAGIC:x},%d0
    move.l  %d0,(%a0)
    move.l  12(%a0),%d0
    cmpi.l  #8,%d0
    bcc.b   1f
    addq.l  #1,12(%a0)
    lsl.l   #3,%d0
    addi.l  #0xa0,%d0
    add.l   %d0,%a0
    move.l  %d2,(%a0)
1:  move.l  (%sp)+,%a0
    move.l  (%sp)+,%d0
    tst.l   %d2
    bge.b   2f
    jsr     0x40080844
    jmp     0x40022bea
2:  jmp     0x40022bfc

| ---- S: sampleslice(arg1, slot); entry sp@(4)=arg1, sp@(8)=slot; ONLY slot >= 128 ---------------
sl_probe:
    move.l  %d0,-(%sp)
    move.l  %a0,-(%sp)
    move.l  16(%sp),%d0
    cmpi.l  #128,%d0
    blo.b   2f
    lea     0x{PROBE:x},%a0
    move.l  #0x{MAGIC:x},%d0
    move.l  %d0,(%a0)
    move.l  16(%a0),%d0
    cmpi.l  #16,%d0
    bcc.b   2f
    addq.l  #1,16(%a0)
    lsl.l   #3,%d0
    addi.l  #0xe0,%d0
    add.l   %d0,%a0
    move.l  16(%sp),%d0
    move.l  %d0,(%a0)
    move.l  12(%sp),%d0
    move.l  %d0,4(%a0)
2:  move.l  (%sp)+,%a0
    move.l  (%sp)+,%d0
    lea     -40(%sp),%sp
    movem.l %d2-%d7/%a2-%a5,(%sp)
    jmp     0x4009937c
"""

HOOKS = [                       # (va, expected_bytes, symbol, pad_nops)
    (0x40022b70, "2f02242f0008", "fl_probe", 0),
    (0x40022b50, "4aaf00046c18", "b_probe", 0),
    (0x40022be0, "4a826c184eb9", "c_probe", 0),
    (0x40099374, "4fefffd848d73cfc", "sl_probe", 2),
]


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC}")
    img = bytearray(SRC.read_bytes())
    p = "out/_lerr2"
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
    # 0x400d6c00 on exactly that reasoning and bricked the unit: exception on project load, hang on empty
    # boot. Only these extents have carried working code on hardware.
    VALIDATED_CAVES = [(0x400d6a00, 0x400d6b00),   # P33D ran from here
                       (0x400d7100, 0x400d7400)]   # tail of the ALLOC_STUB cave [0x400d7000,0x400d7400)
    if not any(lo <= CODE and CODE + len(blob) <= hi for lo, hi in VALIDATED_CAVES):
        sys.exit(f"REFUSING: [0x{CODE:08x},0x{CODE + len(blob):08x}) is not inside a validated cave "
                 f"{['0x%08x-0x%08x' % c for c in VALIDATED_CAVES]}. Shrink the blob or reuse a proven cave.")
    assert not any(img[bd.off(CODE):bd.off(CODE) + len(blob)]), "cave not empty"
    img[bd.off(CODE):bd.off(CODE) + len(blob)] = blob
    for va, exp, name, pad in HOOKS:
        o = bd.off(va)
        got = bytes(img[o:o + len(exp) // 2]).hex()
        assert got == exp, f"{name}: expected {exp} at 0x{va:x}, got {got}"
        img[o:o + 6] = b"\x4e\xf9" + sym[name].to_bytes(4, "big")
        for k in range(pad):
            img[o + 6 + k * 2:o + 8 + k * 2] = b"\x4e\x71"
        print(f"  hook 0x{va:08x} -> {name} @0x{sym[name]:08x}")
    OUT.write_bytes(bytes(img))
    print(f"blob {len(blob)} B; PROBE 0x{PROBE:08x} = project.256 offset 0x{PROBE - bd.SET_B:05x}")
    print(f"{OUT}: {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
