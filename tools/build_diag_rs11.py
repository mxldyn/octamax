#!/usr/bin/env python3
"""build_diag_rs11.py -- WHO tells the AED to show slot 1?

Correction from hardware: this is NOT cosmetic. On the first AED open the editor loads slot 1's
waveform, so slices cannot be edited until the slot is re-selected.

rs9 measured the AED's read of the per-track slot byte (0x40083c9a) and it is CORRECT: offset
0x8f05e, value 0x9f = 159, pattern 0 / track 4. So that path hands the right slot to the setter
0x4006de34(type, slot) -- and the title still says 001. The setter has FIVE call sites, and the other
four do not read the track byte at all:

  0x4003d056  slot from a per-mode UI global (0x460d5c44 / 0x460d5c58), or track+128 for type 4
  0x40077ad4  slot = 0 (constant)
  0x40077af4  slot = track + 128, type 4 (the recorder)
  0x40083ca6  the track byte -- the one rs9 proved correct
  0x40083da6  the track byte, second copy of the same idiom

So a later call must overwrite the global with a stale value. The setter is the single point of truth,
so this build logs EVERY call to it: the caller's return address (which names the site), the type and
the slot. The sequence when the AED opens shows exactly which site wins and with what.

  tag 60  caller return address   tag 61  type arg   tag 62  slot arg

Snapshots only, no debug module.

PROCEDURE: power-cycle -> open the AED on the high-slot track (wrong waveform) -> select the high slot
in the slot list -> open the AED again (correct) -> SAVE -> mount the CF.
    python3 tools/read_probe.py <project.256> --build build_diag_rs10
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd
from hookcheck import check_holes

SRC = pathlib.Path("out/mainos_persist256.bin")
OUT = pathlib.Path("out/mainos_diag_rs11.bin")
CODE, PROBE = 0x400d7100, 0x40ab65e0
CODE_END = 0x400d7300
MAGIC = 0x10ade111
BANKPTR = 0x46c82456
G_PAT, G_TRK = 0x100b14cf, 0x100b14cc
SAFE = 0x400d7a00        # free cave; wave 25 owns 0x400d7800
SAFE_CAP = 33
SC_SAVE = 0x400d6600
SETTER = 0x4006de34      # the AED current-slot setter (6B: movel d2,-(sp) ; movel sp@(8),d2)
TITLE  = 0x4006df74      # the title formatter's read: moveal 0x46c8d19c,%a0  (6B)

ASM = f"""    .cpu 5407
    .text
| ---- rec: append (d0=tag, d1=value). Clobbers d2/a0/a1 only. ----
rec:
    lea     0x{SAFE:x},%a0
    move.l  (%a0),%d2
    cmpi.l  #{SAFE_CAP},%d2
    bge.b   rec_out
    addq.l  #1,(%a0)
    lsl.l   #3,%d2
    lea     12(%a0),%a1
    adda.l  %d2,%a1
    move.l  %d0,(%a1)
    move.l  %d1,4(%a1)
rec_out:
    rts

| ================= tags 60/61/62: every call to the AED slot setter 0x4006de34 ==================
| At entry (nothing pushed yet): sp@(0)=return address, sp@(4)=type, sp@(8)=slot.
set_probe:
    lea     -20(%sp),%sp
    movem.l %d0-%d2/%a0-%a1,(%sp)
    lea     0x{SAFE:x},%a0
    move.l  4(%a0),%d0                   | budget: 11 calls x 3 entries
    cmpi.l  #11,%d0
    bge.b   1f
    addq.l  #1,4(%a0)
    move.l  20(%sp),%d1                  | caller return address -> names the call site
    moveq   #60,%d0
    bsr.w   rec
    move.l  24(%sp),%d1                  | type
    moveq   #61,%d0
    bsr.w   rec
    move.l  28(%sp),%d1                  | slot
    moveq   #62,%d0
    bsr.w   rec
1:  movem.l (%sp),%d0-%d2/%a0-%a1
    lea     20(%sp),%sp
    move.l  %d2,-(%sp)                   | replicate the displaced prologue
    move.l  %sp@(8),%d2
    jmp     0x{SETTER + 6:x}

| ================= tag 70: the TITLE FORMATTER's read of the global =================
| Records what the title will actually print (value + 1). If a 0 lands here BEFORE the setter runs
| with 159, the screen is simply drawn before the slot is published -- an ordering bug, not a clamp.
title_probe:
    lea     -20(%sp),%sp
    movem.l %d0-%d2/%a0-%a1,(%sp)
    lea     0x{SAFE:x},%a0
    move.l  8(%a0),%d0                   | budget: 8 draws
    cmpi.l  #8,%d0
    bge.b   3f
    addq.l  #1,8(%a0)
    move.l  0x46c8d19c,%d1
    moveq   #70,%d0
    bsr.w   rec
3:  movem.l (%sp),%d0-%d2/%a0-%a1
    lea     20(%sp),%sp
    movea.l 0x46c8d19c,%a0               | replicate the displaced read
    jmp     0x{TITLE + 6:x}

| ================= mirror at sidecar_save (6B hole) =================
sv_copy:
    lea     -16(%sp),%sp
    movem.l %d0-%d1/%a0-%a1,(%sp)
    lea     0x{PROBE:x},%a0
    move.l  #0x{MAGIC:x},%d0
    move.l  %d0,(%a0)
    move.l  0x{SAFE:x},%d0
    move.l  %d0,0x10(%a0)
    lea     0x1a0(%a0),%a0
    lea     0x{SAFE + 12:x},%a1
    moveq   #{SAFE_CAP * 2},%d1
3:  move.l  (%a1)+,(%a0)+
    subq.l  #1,%d1
    bne.b   3b
    movem.l (%sp),%d0-%d1/%a0-%a1
    lea     16(%sp),%sp
    move.l  %d0,-(%sp)                   | replicate displaced pushes
    move.l  %d1,-(%sp)
    move.l  %d2,-(%sp)
    jmp     0x{SC_SAVE + 6:x}
"""

LAYOUT = {
    "EV": {"counter": 0x10, "array": 0x1a0, "entry": 8, "cap": SAFE_CAP,
           "fields": [("tag", 0, "u32"), ("value", 4, "hex")]},
}

HOOKS = [
    (SETTER, "2f02242f0008", "set_probe"),
    (TITLE, "207946c8d19c", "title_probe"),
    (SC_SAVE, "2f002f012f02", "sv_copy"),
]


def main():
    img = bytearray(SRC.read_bytes())
    p = "out/_rs11"
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
    assert CODE + len(blob) <= CODE_END, f"blob {len(blob)} B overruns the cave"
    assert not any(img[bd.off(CODE):bd.off(CODE) + len(blob)]), "cave not empty"
    assert not any(img[bd.off(SAFE):bd.off(SAFE) + 12 + 8 * SAFE_CAP]), "SAFE log area not empty"
    assert b"\x2c\x8d" not in blob and b"\x2c\x87" not in blob, "no debug-module operands allowed"
    img[bd.off(CODE):bd.off(CODE) + len(blob)] = blob
    base = bytes(SRC.read_bytes())
    check_holes(base, [(va, len(exp) // 2) for va, exp, _ in HOOKS if va < 0x400d0000])
    for va, exp, name in HOOKS:
        o, hole = bd.off(va), len(exp) // 2
        assert bytes(img[o:o + hole]).hex() == exp, f"0x{va:08x}: {bytes(img[o:o+hole]).hex()} != {exp}"
        img[o:o + 6] = b"\x4e\xf9" + sym[name].to_bytes(4, "big")
        print(f"  hook 0x{va:08x} -> {name} @0x{sym[name]:08x}")
    OUT.write_bytes(bytes(img))
    print(f"blob {len(blob)} B; logs every AED slot-setter call AND every title draw, in order")
    print("  -> DO NOT USE UI SLOTS 252, 253")
    print(f"{OUT}: {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
