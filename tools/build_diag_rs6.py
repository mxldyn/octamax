#!/usr/bin/env python3
"""build_diag_rs6.py -- why did wave 24 not unmute the high slot?

Wave 24 added prime_hi (a sweep over SET-B calling sampleview for every populated high slot whose
STATE @16 is still 0) at the epilogue of BOTH project loaders. On hardware nothing changed: the slot
still needs the AED. Exactly three things can be true, and this build separates them:

  A. prime_hi never runs on the boot path   -> tag 1 absent  (the boot loader is not 0x4008ff58)
  B. it runs but skips the slot             -> tag 1 present, no tag 2 from a sidecar caller
                                               (SET-B still empty at that moment, or @16 already != 0)
  C. it runs and calls sampleview, which does not arm the slot -> tag 2 present, tag 6/8 still 0

Every sampleview call for a high slot is logged with its CALLER's return address, which says which
path made it: 0x400d6xxx = prime_hi (the sidecar blob), 0x400908ac = the bulk STATIC load loop,
0x40084c20 = the parser case, anything else = the AED/UI. Comparing the AED's successful call with the
load-time one is the whole point.

  tag 1  prime_hi entry            value = SET-B[31].path[0..3]  ('../A' = populated, 0 = empty)
  tag 2  sampleview, slot >= 128   value = slot
  tag 9  the same call             value = caller return address
  tag 3  resolver, slot >= 128     value = slot          (max 4)
  tag 6  the same call             value = that slot's @16 at play time (0 = SILENT)
  tag 8  sidecar_save              value = STATE-B[31]@16 at save time

No debug module -- snapshots only (see [[octatrack-hw-probe-safety]]: P69's watchpoint on this very
field truncated a bank file and corrupted the project). Log lives in the code cave; mirrored into the
PROBE block at save.

PROCEDURE: power-cycle -> play the trig on UI slot 160 (silent) -> open the AED, let the waveform draw
-> play again (sounds) -> SAVE -> mount the CF. Avoid UI slots 252/253.
    python3 tools/read_probe.py <project.256> --build build_diag_rs6
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd
from hookcheck import check_holes

SRC = pathlib.Path("out/mainos_persist256.bin")
OUT = pathlib.Path("out/mainos_diag_rs6.bin")
CODE, PROBE = 0x400d7100, 0x40ab65e0
CODE_END = 0x400d7300
MAGIC = 0x10ade111
ST_B, ST_STRIDE, SET_B = bd.ST_B, bd.ST_STRIDE, bd.SET_B
WATCH = ST_B + 31 * ST_STRIDE + 16          # STATE-B[31]@16  (UI slot 160)
SETB31 = SET_B + 31 * 0x448                 # SETTINGS-B[31].path
SAFE = 0x400d7300
SAFE_CAP = 28
SC_SAVE = 0x400d6600


def stub_va(img, hook_va):
    """VA the build installed at a jmp hook (so the diag never hardcodes a moving stub address)."""
    o = bd.off(hook_va)
    assert bytes(img[o:o + 2]) == b"\x4e\xf9", f"0x{hook_va:08x} is not a jmp stub"
    return int.from_bytes(img[o + 2:o + 6], "big")


def build_asm(prime_hi):
    return f"""    .cpu 5407
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

| ================= tag 1: prime_hi entry (6B hole: lea sp@(-32),sp ; first half of the moveml) =====
| Records whether the wave-24 sweep runs at all, and whether SET-B[31] is populated when it does.
ph_entry:
    lea     -20(%sp),%sp
    movem.l %d0-%d2/%a0-%a1,(%sp)
    moveq   #1,%d0
    move.l  0x{SETB31:x},%d1             | SET-B[31].path[0..3]
    bsr.w   rec
    movem.l (%sp),%d0-%d2/%a0-%a1
    lea     20(%sp),%sp
    lea     -32(%sp),%sp                 | replicate the displaced prologue
    movem.l %d0-%d3/%a0-%a3,(%sp)
    jmp     0x{prime_hi + 8:x}

| ================= tags 2/9: sampleview 0x40093980 entry, high slots + WHO called (8B hole) ========
sv_entry:
    lea     -20(%sp),%sp
    movem.l %d0-%d2/%a0-%a1,(%sp)
    move.l  24(%sp),%d1                  | slot (entry sp@(4), +20)
    cmpi.l  #128,%d1
    blt.b   1f
    moveq   #2,%d0
    bsr.w   rec
    move.l  20(%sp),%d1                  | caller return address (entry sp@(0), +20)
    moveq   #9,%d0
    bsr.w   rec
1:  movem.l (%sp),%d0-%d2/%a0-%a1
    lea     20(%sp),%sp
    linkw   %fp,#-380                    | replicate displaced entry
    movem.l %d2-%d7/%a2-%a4,(%sp)
    jmp     0x40093988

| ================= tags 3/6: voice-bind resolver 0x4000f450 entry (8B hole) =================
rs_entry:
    lea     -20(%sp),%sp
    movem.l %d0-%d2/%a0-%a1,(%sp)
    move.l  28(%sp),%d1                  | slot (entry sp@(8), +20)
    cmpi.l  #128,%d1
    blt.b   2f
    lea     0x{SAFE:x},%a0
    move.l  8(%a0),%d0                   | budget: at most 4 resolver calls
    cmpi.l  #4,%d0
    bge.b   2f
    addq.l  #1,8(%a0)
    moveq   #3,%d0
    bsr.w   rec
    move.l  28(%sp),%d1
    subi.l  #128,%d1
    move.l  %d1,%d0                      | d1*44 = d1*32 + d1*8 + d1*4
    lsl.l   #5,%d0
    move.l  %d1,%d2
    lsl.l   #3,%d2
    add.l   %d2,%d0
    move.l  %d1,%d2
    lsl.l   #2,%d2
    add.l   %d2,%d0
    lea     0x{ST_B:x},%a0
    adda.l  %d0,%a0
    move.l  16(%a0),%d1
    moveq   #6,%d0
    bsr.w   rec
2:  movem.l (%sp),%d0-%d2/%a0-%a1
    lea     20(%sp),%sp
    lea     -60(%sp),%sp                 | replicate displaced entry
    movem.l %d2-%d7/%a2-%fp,(%sp)
    jmp     0x4000f458

| ================= tag 8 + mirror: sidecar_save entry (6B hole) =================
sv_copy:
    lea     -20(%sp),%sp
    movem.l %d0-%d2/%a0-%a1,(%sp)
    moveq   #8,%d0
    move.l  0x{WATCH:x},%d1
    bsr.w   rec
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
    movem.l (%sp),%d0-%d2/%a0-%a1
    lea     20(%sp),%sp
    move.l  %d0,-(%sp)                   | replicate displaced pushes
    move.l  %d1,-(%sp)
    move.l  %d2,-(%sp)
    jmp     0x{SC_SAVE + 6:x}
"""


LAYOUT = {
    "EV": {"counter": 0x10, "array": 0x1a0, "entry": 8, "cap": SAFE_CAP,
           "fields": [("tag", 0, "u32"), ("value", 4, "hex")]},
}


def main():
    img = bytearray(SRC.read_bytes())
    # bootload_done starts with `bsr.w prime_hi`: decode its 16-bit displacement rather than guessing.
    bd_va = stub_va(img, 0x40090002)
    o = bd.off(bd_va)
    assert bytes(img[o:o + 2]) == b"\x61\x00", "bootload_done does not start with bsr.w"
    disp = int.from_bytes(img[o + 2:o + 4], "big", signed=True)
    prime_hi = bd_va + 2 + disp
    print(f"  resolved prime_hi @0x{prime_hi:08x} (from bootload_done 0x{bd_va:08x} bsr.w {disp})")
    assert bytes(img[bd.off(prime_hi):bd.off(prime_hi) + 8]).hex() == "4fefffe048d70f0f", \
        "prime_hi prologue is not the expected lea+movem"

    hooks = [
        (prime_hi, "4fefffe048d7", "ph_entry"),
        (0x40093980, "4e56fe8448d71cfc", "sv_entry"),
        (0x4000f450, "4fefffc448d77cfc", "rs_entry"),
        (SC_SAVE, "2f002f012f02", "sv_copy"),
    ]

    p = "out/_rs6"
    pathlib.Path(p + ".s").write_text(build_asm(prime_hi))
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
    assert CODE + len(blob) <= CODE_END, f"blob {len(blob)} B overruns the SAFE log"
    assert not any(img[bd.off(CODE):bd.off(CODE) + len(blob)]), "cave not empty"
    assert not any(img[bd.off(SAFE):bd.off(SAFE) + 12 + 8 * SAFE_CAP]), "SAFE log area not empty"
    assert b"\x2c\x8d" not in blob and b"\x2c\x87" not in blob, "no debug-module operands allowed"
    img[bd.off(CODE):bd.off(CODE) + len(blob)] = blob
    base = bytes(SRC.read_bytes())
    # hookcheck only knows the stock layout; the sidecar stub is ours, so check the OS holes only
    check_holes(base, [(va, len(exp) // 2) for va, exp, _ in hooks if va < 0x400d0000])
    for va, exp, name in hooks:
        o, hole = bd.off(va), len(exp) // 2
        assert bytes(img[o:o + hole]).hex() == exp, f"0x{va:08x}: {bytes(img[o:o+hole]).hex()} != {exp}"
        img[o:o + 6] = b"\x4e\xf9" + sym[name].to_bytes(4, "big")
        print(f"  hook 0x{va:08x} -> {name} @0x{sym[name]:08x}")
    OUT.write_bytes(bytes(img))
    print(f"blob {len(blob)} B; instruments the wave-24 sweep + every high-slot sampleview caller")
    print("  -> DO NOT USE UI SLOTS 252, 253")
    print(f"{OUT}: {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
