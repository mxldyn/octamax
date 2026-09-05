#!/usr/bin/env python3
"""build_diag_bugA.py -- MEASURING build for BUG A (per-track assigned slot reverts on RELOAD for
high STATIC slots). Fixes nothing.

Static analysis is exhausted: the track-slot field (*(0x46c82456)+pat*0x18b2+trk*5+type+0x8F04A) has
exactly TWO writers via its +0x8F04A base -- writer A (part-activate, store 0x40027ec2) and writer B
(ui_apply assign, store 0x400795c0) -- both byte-clean. The reload corruptor must reach the field by
another route (type-base +0x8EDA2 + 0x2A8, a running pointer, or a memset). This probe decides WHICH in
ONE flash by watching:

  WA  hook 0x40027ebc (writer A's `addal #0x8F04A,%a0`, replicated): records every write A performs
      -> [value d7][dest a0]. If on RELOAD A fires for the user's track with a LOW value, the bug is
      that the PART source it copies from lost the high slot (chase the part-commit on SAVE). If A does
      NOT fire on reload yet the field still reverts, the corruptor is a hidden non-+0x8F04A path.
  RD  hook 0x40005078 (trackparam FUN_40005030's `addal #0x8F04A,%a1`, replicated): records the field
      addr + the BYTE the DSP actually reads for the playing track -> [fieldaddr a1][value]. This is the
      ground truth of what the reverted track resolves to after reload.

Both stubs replicate the exact displaced instruction, save/restore all regs they touch, and are pure
observers. PROBE 0x40ab65e0 = project.256 offset 0x21000 (survives SAVE). Reserves UI slot 252 (253 to
be safe). DELETE <project>/project.256 before the run.

Procedure: assign a HIGH slot to a track (note which pattern/track), place a trig, hear it play, SAVE,
then RELOAD the project, play the pattern (so RD fires), SAVE again. Remount and:
    python3 tools/read_probe.py <project.256> --build build_diag_bugA

    python3 tools/build_diag_bugA.py    # -> out/mainos_diag_bugA.bin
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd
from hookcheck import check_holes

SRC = pathlib.Path("out/mainos_persist256.bin")
BASE_VA = 0x40000400
OUT = pathlib.Path("out/mainos_diag_bugA.bin")
CODE, PROBE = 0x400d7100, 0x40ab65e0
MAGIC = 0x10ade111

ASM = f"""    .cpu 5407
    .text
| ---- ring allocator: d0=cap, d1=cnt off, d2=arr off, d3=size -> a1 (0=full). clobbers d0-d2,a0,a1.
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

| ==== WA: writer A part-activate. Displaced `addal #0x8F04A,%a0` (a0 -> dest track-slot field).
|      Store follows at 0x40027ec2 (moveb %d7,%a0@); d7 = value being written. Record [value][dest].
wa_probe:
    adda.l  #0x8f04a,%a0
    move.l  %a0,-(%sp)                  | payload: dest addr
    move.l  %d7,-(%sp)                  | payload: value
    lea     -24(%sp),%sp
    movem.l %d0-%d3/%a0-%a1,(%sp)
    moveq   #16,%d0
    moveq   #4,%d1                      | cntWA
    moveq   #0x40,%d2                   | WA arr
    moveq   #12,%d3
    bsr.w   rec_alloc
    move.l  %a1,%d0
    tst.l   %d0
    beq.b   1f
    move.l  24(%sp),%d0                 | value (pushed last)
    move.l  %d0,(%a1)
    move.l  28(%sp),%d0                 | dest addr
    move.l  %d0,4(%a1)
1:  movem.l (%sp),%d0-%d3/%a0-%a1
    lea     24(%sp),%sp
    addq.l  #8,%sp
    jmp     0x40027ec2

| ==== RD: trackparam FUN_40005030. Displaced `addal #0x8F04A,%a1` (a1 -> track-slot field).
|      Read follows at 0x4000507e (moveb %a1@,%d1). Record [fieldaddr][byte value the DSP reads].
rd_probe:
    adda.l  #0x8f04a,%a1
    move.l  %a1,-(%sp)                  | payload: field addr
    lea     -24(%sp),%sp
    movem.l %d0-%d3/%a0-%a1,(%sp)
    moveq   #16,%d0
    moveq   #8,%d1                      | cntRD
    move.l  #0x100,%d2                  | RD arr
    moveq   #12,%d3
    bsr.w   rec_alloc
    move.l  %a1,%d0
    tst.l   %d0
    beq.b   2f
    move.l  24(%sp),%a0                 | field addr
    move.l  %a0,(%a1)
    moveq   #0,%d0
    move.b  (%a0),%d0                   | the byte the DSP reads
    move.l  %d0,4(%a1)
2:  movem.l (%sp),%d0-%d3/%a0-%a1
    lea     24(%sp),%sp
    addq.l  #4,%sp
    jmp     0x4000507e
"""

# decoder contract (read_probe imports this)
LAYOUT = {
    "WA": {"counter": 0x04, "array": 0x40, "entry": 12, "cap": 16,
           "fields": [("value", 0, "s32"), ("dest", 4, "hex")]},
    "RD": {"counter": 0x08, "array": 0x100, "entry": 12, "cap": 16,
           "fields": [("fieldaddr", 0, "hex"), ("value", 4, "s32")]},
}

HOOKS = [
    (0x40027ebc, "d1fc0008f04a", "wa_probe"),
    (0x40005078, "d3fc0008f04a", "rd_probe"),
]


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC}")
    img = bytearray(SRC.read_bytes())
    p = "out/_bugA"
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
    print(f"blob {len(blob)} B; PROBE 0x{PROBE:08x} = project.256 offset 0x{poff:05x} = SET-B[{poff//0x448}]")
    print("  -> DO NOT USE UI SLOTS 252, 253")
    print(f"{OUT}: {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
