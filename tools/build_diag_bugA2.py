#!/usr/bin/env python3
"""build_diag_bugA2.py -- BUG A bisect probe #2. Watches the REAL per-part track-slot field
(runtime *(0x46c82456)+0x8F1BD, proven by the flash-free bank-file diff: the assign wrote 0x9F there
byte-clean, and RELOAD reverts it). P48 ruled out writer A (cntWA=0) and showed trackparam is not the
playback read path. This build reads the field at ordered milestones to bracket the reload corruptor:

  AS  hook 0x400795ba (ui_apply assign `addal #0x8F04A,%a0`): records [off=a0-*(0x46c82456)][value d1]
      -- the EXACT field offset + value the assign wrote (robust to which track; cross-checks 0x8F1BD).
  M1  hook 0x400908ac (bulk STATIC load-loop, runs DURING project load): records
      [field byte @ *(0x46c82456)+0x8F1BD][bankbase]. Baseline "is it still high during load?".
  M2  hook 0x4005a6ac (track-name display formatter, runs when the track UI draws AFTER load): records
      [hardcoded field byte][the byte THIS draw reads]. "What the UI sees after the corruptor ran."

Read: M1 high (0x9F) + M2 low  => corruptor is between bulk-load and UI-draw. M1 already low => earlier.
The reverted VALUE (127 => clamp / 0 => clear / other => remap) narrows the corruptor class.

PROCEDURE: assign UI slot 160 to the SAME track as the last no-reload test (its field is 0x8F1BD),
SAVE, RELOAD, view/play that track, SAVE. Delete project.256 first. Do NOT use UI slots 252/253.
    python3 tools/read_probe.py <project.256> --build build_diag_bugA2
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd
from hookcheck import check_holes

SRC = pathlib.Path("out/mainos_persist256.bin")
BASE_VA = 0x40000400
OUT = pathlib.Path("out/mainos_diag_bugA2.bin")
CODE, PROBE = 0x400d7100, 0x40ab65e0
MAGIC = 0x10ade111
BANKPTR = 0x46c82456
FIELD_OFF = 0x8f1bd

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

| ==== AS: ui_apply assign. Displaced `addal #0x8F04A,%a0` -> a0 = field the assign writes; d1 = value.
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
    move.l  28(%sp),%d0                 | dest addr
    movea.l #0x{BANKPTR:x},%a0
    sub.l   (%a0),%d0                   | off = dest - *(bankptr)
    move.l  %d0,(%a1)
    move.l  24(%sp),%d0                 | value
    move.l  %d0,4(%a1)
1:  movem.l (%sp),%d0-%d3/%a0-%a1
    lea     24(%sp),%sp
    addq.l  #8,%sp
    jmp     0x400795c0

| ==== M1: bulk STATIC load-loop 0x400908ac. Displaced `movel d0,d2 ; addql #8,sp ; bge 0x400908d8`.
m1_probe:
    lea     -24(%sp),%sp
    movem.l %d0-%d3/%a0-%a1,(%sp)
    moveq   #8,%d0
    moveq   #8,%d1
    move.l  #0xa0,%d2
    moveq   #12,%d3
    bsr.w   rec_alloc
    move.l  %a1,%d0
    tst.l   %d0
    beq.b   1f
    movea.l #0x{BANKPTR:x},%a0
    move.l  (%a0),%d0                   | bankbase
    move.l  %d0,4(%a1)
    movea.l %d0,%a0
    adda.l  #0x{FIELD_OFF:x},%a0
    moveq   #0,%d1
    move.b  (%a0),%d1                   | field byte during load
    move.l  %d1,(%a1)
1:  movem.l (%sp),%d0-%d3/%a0-%a1
    lea     24(%sp),%sp
    move.l  %d0,%d2
    addq.l  #8,%sp
    bge.b   2f
    jmp     0x400908b2
2:  jmp     0x400908d8

| ==== M2: track-name display formatter 0x4005a6ac. Displaced `addal #0x8F04A,%a0` (a0 = displayed field).
m2_probe:
    adda.l  #0x8f04a,%a0
    move.l  %a0,-(%sp)
    lea     -24(%sp),%sp
    movem.l %d0-%d3/%a0-%a1,(%sp)
    moveq   #8,%d0
    moveq   #12,%d1
    move.l  #0x120,%d2
    moveq   #12,%d3
    bsr.w   rec_alloc
    move.l  %a1,%d0
    tst.l   %d0
    beq.b   2f
    movea.l #0x{BANKPTR:x},%a0
    move.l  (%a0),%d0
    movea.l %d0,%a0
    adda.l  #0x{FIELD_OFF:x},%a0
    moveq   #0,%d1
    move.b  (%a0),%d1                   | hardcoded field byte
    move.l  %d1,(%a1)
    movea.l 24(%sp),%a0                 | displayed field addr
    moveq   #0,%d1
    move.b  (%a0),%d1
    move.l  %d1,4(%a1)                  | byte this draw reads
2:  movem.l (%sp),%d0-%d3/%a0-%a1
    lea     24(%sp),%sp
    addq.l  #4,%sp
    jmp     0x4005a6b2
"""

LAYOUT = {
    "AS": {"counter": 0x04, "array": 0x40, "entry": 12, "cap": 8,
           "fields": [("off", 0, "hex"), ("value", 4, "s32")]},
    "M1": {"counter": 0x08, "array": 0xa0, "entry": 12, "cap": 8,
           "fields": [("field_during_load", 0, "s32"), ("bankbase", 4, "hex")]},
    "M2": {"counter": 0x0c, "array": 0x120, "entry": 12, "cap": 8,
           "fields": [("field_hardcoded", 0, "s32"), ("field_UI_reads", 4, "s32")]},
}

HOOKS = [
    (0x400795ba, "d1fc0008f04a", "as_probe"),
    (0x400908ac, "2400508f6c26", "m1_probe"),
    (0x4005a6ac, "d1fc0008f04a", "m2_probe"),
]


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC}")
    img = bytearray(SRC.read_bytes())
    p = "out/_bugA2"
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
        sys.exit(f"REFUSING: cave [0x{CODE:08x},0x{CODE+len(blob):08x}) not validated.")
    assert not any(img[bd.off(CODE):bd.off(CODE) + len(blob)]), "cave not empty"
    img[bd.off(CODE):bd.off(CODE) + len(blob)] = blob
    base = bytes(SRC.read_bytes())
    check_holes(base, [(va, len(exp) // 2) for va, exp, _ in HOOKS])
    for va, exp, name in HOOKS:
        o, hole = bd.off(va), len(exp) // 2
        got = bytes(img[o:o + hole]).hex()
        assert got == exp, f"{name}: expected {exp} at 0x{va:x}, got {got}"
        img[o:o + 6] = b"\x4e\xf9" + sym[name].to_bytes(4, "big")
        img[o + 6:o + hole] = b"\x4e\x71" * ((hole - 6) // 2)
        print(f"  hook 0x{va:08x} -> {name:9} @0x{sym[name]:08x}  (hole {hole} B)")
    allowed = set(range(bd.off(CODE), bd.off(CODE) + len(blob)))
    for va, exp, _ in HOOKS:
        allowed |= set(range(bd.off(va), bd.off(va) + len(exp) // 2))
    stray = [i for i in range(len(base)) if img[i] != base[i] and i not in allowed]
    if stray:
        sys.exit(f"REFUSING: {len(stray)} stray byte(s), first 0x{BASE_VA+stray[0]:08x}.")
    OUT.write_bytes(bytes(img))
    poff = PROBE - bd.SET_B
    print(f"blob {len(blob)} B; PROBE 0x{PROBE:08x} = project.256 offset 0x{poff:05x}; field=*(0x{BANKPTR:x})+0x{FIELD_OFF:x}")
    print("  -> DO NOT USE UI SLOTS 252, 253")
    print(f"{OUT}: {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
