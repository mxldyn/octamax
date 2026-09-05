#!/usr/bin/env python3
"""build_diag_rs7.py -- WHICH of the voice-bind conditions fails for a restored high slot?

rs6 (P72) settled the earlier questions and killed my working theory:
  * prime_hi DOES run on the boot path, but SET-B[31] is still EMPTY at that moment (tag1 = 0), so the
    wave-24 sweep has nothing to arm -- SET-B is filled later still.
  * the bulk STATIC load loop later DOES call sampleview for both high slots (caller 0x400908ac).
  * and by the time the resolver looked at UI slot 160 its @16 was 0x639750, i.e. NOT zero.
So "@16 == 0" is NOT why the slot is mute. The resolver 0x4000f450 has THREE conditions:

    0x4000f4e4  tst.l  STATE@16   ; <= 0        -> BAIL
    0x4000f4ea  move.l STATE@8    ; != 0        -> BAIL
    0x4000f502  STATE@20  vs  STRIDE4[idx]      ; different -> BAIL, equal -> BIND (0x4000f526)

@16 is fine, so the slot is dying on @8 != 0 or on the generation token STATE@20 not matching
STRIDE4[idx] -- the classic symptom of one path writing the token for the A table while the resolver
reads it through the migrated helper from the B table. (No un-migrated absolute reference to S41_A /
S42_A survives in the image, so if that is it, the write goes through a COMPUTED pointer, exactly like
Bug A did.)

This build dumps all three conditions at resolver entry, and does it for a WORKING low slot too, so we
can read what "good" looks like side by side:

  high slot (idx >= 150, max 2 calls)   tag 3=slot  4=@8  5=@16  6=@20  7=S41-B[idx]  8=S42-B[idx]
  low  slot (idx <  128, max 1 call)    tag 10=slot 11=@8 12=@16 13=@20 14=S41-A[idx] 15=S42-A[idx]
  plus tag 2/9 = each high-slot sampleview call and its caller, for ordering.

The high-slot filter is idx >= 150 so the budget is not eaten by slot 134 the way it was in P72.
Snapshots only, no debug module (see [[octatrack-hw-probe-safety]]).

PROCEDURE: power-cycle -> play the trig on UI slot 160 FIRST (silent -- this is the measurement) ->
then open the AED and let the waveform draw -> play again (sounds) -> SAVE -> mount the CF.
    python3 tools/read_probe.py <project.256> --build build_diag_rs7
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd
from hookcheck import check_holes

SRC = pathlib.Path("out/mainos_persist256.bin")
OUT = pathlib.Path("out/mainos_diag_rs7.bin")
CODE, PROBE = 0x400d7100, 0x40ab65e0
CODE_END = 0x400d7300
MAGIC = 0x10ade111
ST_A, ST_B = bd.ST_A, bd.ST_B
S41_A, S41_B, S42_A, S42_B = bd.S41_A, bd.S41_B, bd.S42_A, bd.S42_B
WATCH = ST_B + 31 * 44 + 16
SAFE = 0x400d7300        # [0]=cnt [4]=low budget [8]=high budget [12..]=entries
SAFE_CAP = 28
SC_SAVE = 0x400d6600
HI_MIN = 150             # only log the slots under test, so slot 134 cannot eat the budget

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

| ---- dump: record the three bind conditions. d3 = base tag, d4 = slot, a2 = STATE ptr,
|      a3 = &S41[idx], and d5 = S42[idx] (read by the caller, since rec clobbers a0/a1). ----
dump:
    move.l  %d3,%d0
    move.l  %d4,%d1
    bsr.w   rec                          | +0 slot
    addq.l  #1,%d3
    move.l  %d3,%d0
    move.l  8(%a2),%d1
    bsr.w   rec                          | +1 STATE@8   (must be 0)
    addq.l  #1,%d3
    move.l  %d3,%d0
    move.l  16(%a2),%d1
    bsr.w   rec                          | +2 STATE@16  (must be > 0)
    addq.l  #1,%d3
    move.l  %d3,%d0
    move.l  20(%a2),%d1
    bsr.w   rec                          | +3 STATE@20  (must equal STRIDE4[idx])
    addq.l  #1,%d3
    move.l  %d3,%d0
    move.l  (%a3),%d1
    bsr.w   rec                          | +4 S41[idx]
    addq.l  #1,%d3
    move.l  %d3,%d0
    move.l  %d5,%d1
    bsr.w   rec                          | +5 S42[idx]
    rts

| ================= resolver 0x4000f450 entry (8B hole) =================
rs_entry:
    lea     -48(%sp),%sp
    movem.l %d0-%d7/%a0-%a3,(%sp)
    move.l  56(%sp),%d4                  | slot (entry sp@(8), +48)
    lea     0x{SAFE:x},%a0
    cmpi.l  #128,%d4
    blt.w   rs_low
| ---- high slot: only the ones under test, at most 2 ----
    cmpi.l  #{HI_MIN},%d4
    blt.w   rs_out
    move.l  8(%a0),%d0
    cmpi.l  #2,%d0
    bge.w   rs_out
    addq.l  #1,8(%a0)
    move.l  %d4,%d1
    subi.l  #128,%d1                     | idxB
    move.l  %d1,%d0                      | d1*44 = d1*32 + d1*8 + d1*4
    lsl.l   #5,%d0
    move.l  %d1,%d2
    lsl.l   #3,%d2
    add.l   %d2,%d0
    move.l  %d1,%d2
    lsl.l   #2,%d2
    add.l   %d2,%d0
    lea     0x{ST_B:x},%a2
    adda.l  %d0,%a2                      | STATE-B[idxB]
    move.l  %d1,%d2
    lsl.l   #2,%d2                       | idxB*4
    lea     0x{S41_B:x},%a3
    adda.l  %d2,%a3                      | &S41-B[idxB]
    lea     0x{S42_B:x},%a1
    adda.l  %d2,%a1
    move.l  (%a1),%d5                    | S42-B[idxB]
    moveq   #3,%d3
    bsr.w   dump
    bra.w   rs_out
| ---- low slot: one working reference sample ----
rs_low:
    move.l  4(%a0),%d0
    cmpi.l  #1,%d0
    bge.w   rs_out
    addq.l  #1,4(%a0)
    move.l  %d4,%d1
    move.l  %d1,%d0
    lsl.l   #5,%d0
    move.l  %d1,%d2
    lsl.l   #3,%d2
    add.l   %d2,%d0
    move.l  %d1,%d2
    lsl.l   #2,%d2
    add.l   %d2,%d0
    lea     0x{ST_A:x},%a2
    adda.l  %d0,%a2
    move.l  %d1,%d2
    lsl.l   #2,%d2
    lea     0x{S41_A:x},%a3
    adda.l  %d2,%a3
    lea     0x{S42_A:x},%a1
    adda.l  %d2,%a1
    move.l  (%a1),%d5
    moveq   #10,%d3
    bsr.w   dump
rs_out:
    movem.l (%sp),%d0-%d7/%a0-%a3
    lea     48(%sp),%sp
    lea     -60(%sp),%sp                 | replicate displaced entry
    movem.l %d2-%d7/%a2-%fp,(%sp)
    jmp     0x4000f458

| ================= tags 2/9: sampleview 0x40093980 entry, high slots + caller (8B hole) ============
sv_entry:
    lea     -20(%sp),%sp
    movem.l %d0-%d2/%a0-%a1,(%sp)
    move.l  24(%sp),%d1                  | slot
    cmpi.l  #{HI_MIN},%d1
    blt.b   1f
    moveq   #2,%d0
    bsr.w   rec
    move.l  20(%sp),%d1                  | caller return address
    moveq   #9,%d0
    bsr.w   rec
1:  movem.l (%sp),%d0-%d2/%a0-%a1
    lea     20(%sp),%sp
    linkw   %fp,#-380                    | replicate displaced entry
    movem.l %d2-%d7/%a2-%a4,(%sp)
    jmp     0x40093988

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
    (0x4000f450, "4fefffc448d77cfc", "rs_entry"),
    (0x40093980, "4e56fe8448d71cfc", "sv_entry"),
    (SC_SAVE, "2f002f012f02", "sv_copy"),
]


def main():
    img = bytearray(SRC.read_bytes())
    p = "out/_rs7"
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
    assert CODE + len(blob) <= CODE_END, f"blob {len(blob)} B overruns the SAFE log"
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
    print(f"blob {len(blob)} B; dumps all three voice-bind conditions for a high slot and a low one")
    print("  -> DO NOT USE UI SLOTS 252, 253")
    print(f"{OUT}: {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
