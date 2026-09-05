#!/usr/bin/env python3
"""build_diag_rs9.py -- the AED cosmetic bug: why does its title read "STATIC 001"?

Audio is fixed (wave 25, HW-confirmed): a high slot sounds on the first trig after a power-cycle and
after a RELOAD. What remains is display-only -- the AED still shows "STATIC 001" and slot 1's waveform.

That title comes from the AED's OWN current-slot global 0x46c8d19c (formatter 0x4006df74, string
"STATIC %03d%s%.10s"), set by 0x4006de34(type, slot). Two call sites feed it from the per-track slot
byte in the bank buffer, e.g. 0x40083c64..0x40083ca6:

    a2 = *(0x46c82456)                       ; bank base
    d0 = mvzb *(0x100b14cf)                  ; pattern     -> * 6322
    d1 = mvzb *(0x100b14cc)                  ; track
    d1 = mvsb *(bank + pattern*6322 + track + 0x8eda2)     ; machine TYPE for that track
    a2 = bank + pattern*6322 + track*5 + type + 0x8f04a
    d0 = mvzb (a2)                           ; the slot byte -- zero-extended, so >=128 is fine

The read itself handles high values correctly, so either it is reading a DIFFERENT byte than the one
the assign wrote, or that byte genuinely holds 0. This build records the exact offset (relative to the
bank base, which moves) and the value at both ends:

  tag 50/51  AED read      offset into the bank buffer, and the byte it got
  tag 52/53  assign write  offset, and the value being written
  tag 54     the pattern and track globals at the AED read, packed (pattern << 8) | track

Matching offsets with a 0 byte means the load never restored that copy; different offsets mean the AED
looks at another pattern/type slot than the assign wrote. Snapshots only, no debug module.

PROCEDURE: power-cycle -> open the AED on the high-slot track (shows STATIC 001) -> select the high
slot in the slot list -> open the AED again (now correct) -> SAVE -> mount the CF.
    python3 tools/read_probe.py <project.256> --build build_diag_rs9
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd
from hookcheck import check_holes

SRC = pathlib.Path("out/mainos_persist256.bin")
OUT = pathlib.Path("out/mainos_diag_rs9.bin")
CODE, PROBE = 0x400d7100, 0x40ab65e0
CODE_END = 0x400d7300
MAGIC = 0x10ade111
BANKPTR = 0x46c82456
G_PAT, G_TRK = 0x100b14cf, 0x100b14cc
SAFE = 0x400d7a00        # free cave; wave 25 owns 0x400d7800
SAFE_CAP = 32
SC_SAVE = 0x400d6600
AED_READ = 0x40083c9a    # addal #0x8f04a,%a2  (6B) -- a2 becomes the slot-byte pointer
ASSIGN_WR = 0x400795ba   # addal #0x8f04a,%a0  (6B) -- a0 becomes the slot-byte pointer, d1 = value

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

| ================= tags 50/51/54: the AED's read of the per-track slot byte =================
| Replicates `addal #0x8f04a,%a2` first, so a2 is the final pointer, then records where it points
| (relative to the moving bank base) and what it holds.
aed_read:
    adda.l  #0x8f04a,%a2                 | replicate the displaced add
    lea     -20(%sp),%sp
    movem.l %d0-%d2/%a0-%a1,(%sp)
    lea     0x{SAFE:x},%a0
    move.l  8(%a0),%d0                   | budget: 6 reads
    cmpi.l  #6,%d0
    bge.b   1f
    addq.l  #1,8(%a0)
    movea.l #0x{BANKPTR:x},%a1
    move.l  %a2,%d1
    sub.l   (%a1),%d1                    | offset = ptr - bank base
    moveq   #50,%d0
    bsr.w   rec
    moveq   #0,%d1
    move.b  (%a2),%d1                    | the slot byte the AED will show (+1)
    moveq   #51,%d0
    bsr.w   rec
    moveq   #0,%d1
    move.b  0x{G_PAT:x},%d1
    lsl.l   #8,%d1
    moveq   #0,%d0
    move.b  0x{G_TRK:x},%d0
    or.l    %d0,%d1                      | (pattern << 8) | track
    moveq   #54,%d0
    bsr.w   rec
1:  movem.l (%sp),%d0-%d2/%a0-%a1
    lea     20(%sp),%sp
    jmp     0x{AED_READ + 6:x}

| ================= tags 52/53: the assign's write of the same byte =================
| d1 holds the value about to be stored at (a0).
assign_wr:
    adda.l  #0x8f04a,%a0                 | replicate the displaced add
    lea     -24(%sp),%sp
    movem.l %d0-%d3/%a0-%a1,(%sp)        | 6 regs = 24 B (d3 survives rec, which clobbers d2/a0/a1)
    move.l  %d1,%d3                      | d3 = the value about to be stored
    movea.l #0x{BANKPTR:x},%a1
    move.l  %a0,%d1                      | a0 is still the final pointer here
    sub.l   (%a1),%d1                    | offset = ptr - bank base
    lea     0x{SAFE:x},%a0
    move.l  4(%a0),%d0                   | budget: 6 writes
    cmpi.l  #6,%d0
    bge.b   2f
    addq.l  #1,4(%a0)
    moveq   #52,%d0
    bsr.w   rec
    moveq   #0,%d1
    move.b  %d3,%d1
    moveq   #53,%d0
    bsr.w   rec
2:  movem.l (%sp),%d0-%d3/%a0-%a1
    lea     24(%sp),%sp
    jmp     0x{ASSIGN_WR + 6:x}

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
    (AED_READ, "d5fc0008f04a", "aed_read"),
    (ASSIGN_WR, "d1fc0008f04a", "assign_wr"),
    (SC_SAVE, "2f002f012f02", "sv_copy"),
]


def main():
    img = bytearray(SRC.read_bytes())
    p = "out/_rs9"
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
    print(f"blob {len(blob)} B; compares the AED's slot-byte read with the assign's write (offset + value)")
    print("  -> DO NOT USE UI SLOTS 252, 253")
    print(f"{OUT}: {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
