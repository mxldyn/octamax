#!/usr/bin/env python3
"""build_diag_rs1.py -- RELOAD-SILENCE diag: who preps high slots on reload, and what does the
voice-bind resolver actually see at play time?

Two record-only entry hooks (no behavior change):
  * sampleview FUN_40093980 entry: for slot>=128 record [caller_ret][slot][arg2] (cap 12, then count
    only). caller_ret identifies the path: 0x400d675a = sidecar PRIME (wave 21), 0x400908ac = bulk
    STATIC loop, 0x40084c20 = parser FLEX case, other = AED/UI. Low-slot calls only counted (SVLO).
  * voice-bind resolver FUN_4000f450 entry: for slot>=128 record [slot][STATE@8][STATE@16][STATE@20]
    [STRIDE4-B[idx]] (cap 8). These are exactly the fields the bind test uses (@16>0 && @8==0 &&
    @20==STRIDE4) -- shows WHY a play is silent at the moment the user presses play.

Distinguishes the fork: ring shows NO bulk-loop sampleview(160) on reload -> SET-B was empty when the
loop passed (ordering) -> fix = restore-before-bulk-load. Ring SHOWS it -> prep ran and something
cleared STATE after -> hunt the clearer with the resolver snapshot as evidence.

PROCEDURE: flash, load the project with slot 160 on a track, press PLAY once (silent), SAVE, mount CF.
Avoid UI slots 252/253.
    python3 tools/read_probe.py <project.256> --build build_diag_rs1
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd
from hookcheck import check_holes

SRC = pathlib.Path("out/mainos_persist256.bin")
OUT = pathlib.Path("out/mainos_diag_rs1.bin")
CODE, PROBE = 0x400d7100, 0x40ab65e0
MAGIC = 0x10ade111
STATE_B, S42_B = 0x40ab79e0, 0x40ab91e0

ASM = f"""    .cpu 5407
    .text
| ============ sampleview entry hook (0x40093980; 8B hole: linkw fp,#-380 ; moveml) ============
| Entry frame untouched: sp@(0)=ret sp@(4)=slot sp@(8)=arg2. After the 16B movem save: +16 each.
sv_probe:
    lea     -20(%sp),%sp
    movem.l %d0-%d2/%a0-%a1,(%sp)
    lea     0x{PROBE:x},%a0
    move.l  #0x{MAGIC:x},%d0
    move.l  %d0,(%a0)
    move.l  24(%sp),%d1              | slot
    cmpi.l  #128,%d1
    bge.b   1f
    addq.l  #1,4(%a0)                | SVLO count (proves the loop ran at all)
    bra.b   2f
1:  move.l  8(%a0),%d0               | cntSV
    addq.l  #1,8(%a0)
    cmpi.l  #12,%d0
    bge.b   2f
    move.l  %d0,%d2                  | d0*12 = d0*8 + d0*4 (no mulu.l #imm on ColdFire)
    lsl.l   #3,%d0
    lsl.l   #2,%d2
    add.l   %d2,%d0
    lea     0x40(%a0),%a1
    adda.l  %d0,%a1
    move.l  20(%sp),%d0              | caller ret
    move.l  %d0,(%a1)
    move.l  %d1,4(%a1)               | slot
    move.l  28(%sp),%d0              | arg2
    move.l  %d0,8(%a1)
2:  movem.l (%sp),%d0-%d2/%a0-%a1
    lea     20(%sp),%sp
    linkw   %fp,#-380                | replicate displaced entry
    movem.l %d2-%d7/%a2-%a4,(%sp)
    jmp     0x40093988

| ============ voice-bind resolver entry hook (0x4000f450; 8B hole: lea sp(-60) ; moveml) ============
| Entry frame untouched: sp@(0)=ret sp@(4)=voice sp@(8)=slot. After the 16B movem save: +16 each.
rs_probe:
    lea     -20(%sp),%sp
    movem.l %d0-%d2/%a0-%a1,(%sp)
    move.l  28(%sp),%d1              | slot
    cmpi.l  #128,%d1
    blt.b   4f
    lea     0x{PROBE:x},%a0
    move.l  #0x{MAGIC:x},%d0
    move.l  %d0,(%a0)
    move.l  12(%a0),%d0              | cntRS
    cmpi.l  #8,%d0
    bge.b   4f
    addq.l  #1,12(%a0)
    move.l  %d0,%d2                  | d0*20 = d0*16 + d0*4
    lsl.l   #4,%d0
    lsl.l   #2,%d2
    add.l   %d2,%d0
    lea     0xe0(%a0),%a1
    adda.l  %d0,%a1
    move.l  %d1,(%a1)                | slot
    subi.l  #128,%d1                 | idxB
    move.l  %d1,%d0                  | d0*44 = d0*32 + d0*8 + d0*4
    lsl.l   #5,%d0
    move.l  %d1,%d2
    lsl.l   #3,%d2
    add.l   %d2,%d0
    move.l  %d1,%d2
    lsl.l   #2,%d2
    add.l   %d2,%d0
    lea     0x{STATE_B:x},%a0
    adda.l  %d0,%a0                  | STATE-B[idxB]
    move.l  8(%a0),%d0
    move.l  %d0,4(%a1)               | @8  (must be 0)
    move.l  16(%a0),%d0
    move.l  %d0,8(%a1)               | @16 (must be >0)
    move.l  20(%a0),%d0
    move.l  %d0,12(%a1)              | @20 gen token
    lsl.l   #2,%d1
    lea     0x{S42_B:x},%a0
    adda.l  %d1,%a0
    move.l  (%a0),%d0
    move.l  %d0,16(%a1)              | STRIDE4-B[idxB] (must == @20)
4:  movem.l (%sp),%d0-%d2/%a0-%a1
    lea     20(%sp),%sp
    lea     -60(%sp),%sp             | replicate displaced entry
    movem.l %d2-%d7/%a2-%fp,(%sp)
    jmp     0x4000f458
"""

LAYOUT = {
    "SVLO": {"counter": 0x04, "array": 0x04, "entry": 4, "cap": 0, "fields": []},
    "SV": {"counter": 0x08, "array": 0x40, "entry": 12, "cap": 12,
           "fields": [("caller_ret", 0, "hex"), ("slot", 4, "u32"), ("arg2", 8, "u32")]},
    "RS": {"counter": 0x0c, "array": 0xe0, "entry": 20, "cap": 8,
           "fields": [("slot", 0, "u32"), ("st8", 4, "s32"), ("st16", 8, "s32"),
                      ("st20", 12, "s32"), ("s42", 16, "s32")]},
}

HOOKS = [
    (0x40093980, "4e56fe8448d71cfc", "sv_probe"),
    (0x4000f450, "4fefffc448d77cfc", "rs_probe"),
]


def main():
    img = bytearray(SRC.read_bytes())
    p = "out/_rs1"
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
    assert CODE + len(blob) <= 0x400d7400, f"blob {len(blob)} overruns cave"
    assert not any(img[bd.off(CODE):bd.off(CODE) + len(blob)]), "cave not empty"
    img[bd.off(CODE):bd.off(CODE) + len(blob)] = blob
    base = bytes(SRC.read_bytes())
    check_holes(base, [(va, len(exp) // 2) for va, exp, _ in HOOKS])
    for va, exp, name in HOOKS:
        o, hole = bd.off(va), len(exp) // 2
        assert bytes(img[o:o + hole]).hex() == exp
        img[o:o + 6] = b"\x4e\xf9" + sym[name].to_bytes(4, "big")
        print(f"  hook 0x{va:08x} -> {name} @0x{sym[name]:08x}")
    OUT.write_bytes(bytes(img))
    print(f"blob {len(blob)} B; sampleview + resolver entry rings; record-only")
    print("  -> DO NOT USE UI SLOTS 252, 253")
    print(f"{OUT}: {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
