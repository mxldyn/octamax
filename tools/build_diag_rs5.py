#!/usr/bin/env python3
"""build_diag_rs5.py -- RELOAD-SILENCE, watchpoint-free. Replaces rs4 (P69), which BRICKED project
loading ("project corrupt").

rs4 armed the MCF5407 watchpoint on STATE-B[31]@16. That field belongs to the sample STREAMING engine
and is written continuously, so the level-sensitive debug interrupt fired in a storm during the load,
starved the CPU and made the CF reads fail -> the OS declared the project corrupt. LESSON: the debug
module is for COLD fields (the Bug A track-slot byte); never point it at an audio/streaming field.

Same question, answered with plain snapshots instead -- every hook here has already run on hardware in
an earlier probe (rs1's resolver hook, rs3's sampleview hook and save-time mirror):

  tag 2  sampleview called with slot >= 128 (value = slot)
         present  -> the bulk load loop DOES prep the restored high slot; the priming is lost later
         absent   -> the loop never preps it (the loop is where the fix belongs)
  tag 7  STATE-B[31]@16 immediately after the bulk STATIC load loop finishes (0 = never primed)
  tag 3  voice resolver entry for a high slot at PLAY time (value = slot, max 4)
  tag 6  that slot's own @16 as the resolver sees it (0 = cannot bind = SILENT)
  tag 8  STATE-B[31]@16 at SAVE time

Reading it: tag7 non-zero + tag6 zero  => primed at load, CLEARED before play (hunt the clearer next).
            tag7 zero  + tag2 absent   => the loop skips restored high slots (fix the loop).
            tag7 zero  + tag2 present  => sampleview ran but did not prime (fix inside that path).

All state lives in the code cave; the PROBE block sits inside SET-B, which the sidecar rewrites on
every load, so probe state must never live there. Mirrored into the PROBE block at save time.

PROCEDURE: power-cycle -> play the trig on UI slot 160 (silent) -> open the AED, let the waveform draw
-> play again (sounds) -> SAVE -> mount the CF. Avoid UI slots 252/253.
    python3 tools/read_probe.py <project.256> --build build_diag_rs5
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd
from hookcheck import check_holes

SRC = pathlib.Path("out/mainos_persist256.bin")
OUT = pathlib.Path("out/mainos_diag_rs5.bin")
CODE, PROBE = 0x400d7100, 0x40ab65e0
CODE_END = 0x400d7300
MAGIC = 0x10ade111
ST_B, ST_STRIDE = bd.ST_B, bd.ST_STRIDE
WATCH = ST_B + 31 * ST_STRIDE + 16               # STATE-B[31]@16 -> UI slot 160
SAFE = 0x400d7300        # [0]=cnt  [4]=(unused)  [8]=resolver budget  [12..]=entries (8B each)
SAFE_CAP = 28
SC_SAVE = 0x400d6600     # sidecar_save entry (6B: three pushes)
LOOP_EXIT = 0x40090902   # first instruction after the bulk STATIC load loop (6B: jsr 0x40096a5c)

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

| ================= tag 2: sampleview 0x40093980 entry, high slots only (8B hole) =================
sv_entry:
    lea     -20(%sp),%sp
    movem.l %d0-%d2/%a0-%a1,(%sp)
    move.l  24(%sp),%d1                  | slot (entry sp@(4), +20)
    cmpi.l  #128,%d1
    blt.b   1f
    moveq   #2,%d0
    bsr.w   rec
1:  movem.l (%sp),%d0-%d2/%a0-%a1
    lea     20(%sp),%sp
    linkw   %fp,#-380                    | replicate displaced entry
    movem.l %d2-%d7/%a2-%a4,(%sp)
    jmp     0x40093988

| ================= tag 7: right after the bulk STATIC load loop (6B hole: jsr 0x40096a5c) ==========
| The displaced instruction is a jsr, so the stub CALLS it itself and then continues past it.
loop_done:
    lea     -20(%sp),%sp
    movem.l %d0-%d2/%a0-%a1,(%sp)
    moveq   #7,%d0
    move.l  0x{WATCH:x},%d1              | STATE-B[31]@16 as the load loop leaves it
    bsr.w   rec
    movem.l (%sp),%d0-%d2/%a0-%a1
    lea     20(%sp),%sp
    jsr     0x40096a5c                   | replicate the displaced call
    jmp     0x{LOOP_EXIT + 6:x}

| ================= tags 3/6: voice-bind resolver 0x4000f450 entry (8B hole) =================
rs_entry:
    lea     -20(%sp),%sp
    movem.l %d0-%d2/%a0-%a1,(%sp)
    move.l  28(%sp),%d1                  | slot (entry sp@(8), +20)
    cmpi.l  #128,%d1
    blt.b   2f
    lea     0x{SAFE:x},%a0
    move.l  8(%a0),%d0                   | resolver budget (max 4 calls)
    cmpi.l  #4,%d0
    bge.b   2f
    addq.l  #1,8(%a0)
    moveq   #3,%d0
    bsr.w   rec                          | tag3 = slot
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
    move.l  16(%a0),%d1                  | that slot's own @16 at play time
    moveq   #6,%d0
    bsr.w   rec                          | tag6 = @16 (0 -> voice cannot bind = SILENT)
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
    move.l  0x{WATCH:x},%d1              | @16 at save time
    bsr.w   rec
    lea     0x{PROBE:x},%a0
    move.l  #0x{MAGIC:x},%d0
    move.l  %d0,(%a0)
    move.l  0x{SAFE:x},%d0
    move.l  %d0,0x10(%a0)                | cnt -> PROBE+0x10
    lea     0x1a0(%a0),%a0
    lea     0x{SAFE + 12:x},%a1
    moveq   #{SAFE_CAP * 2},%d1          | entries x 8B, as longs
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

HOOKS = [
    (0x40093980, "4e56fe8448d71cfc", "sv_entry"),
    (LOOP_EXIT, "4eb940096a5c", "loop_done"),
    (0x4000f450, "4fefffc448d77cfc", "rs_entry"),
    (SC_SAVE, "2f002f012f02", "sv_copy"),
]


def main():
    img = bytearray(SRC.read_bytes())
    p = "out/_rs5"
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
    assert CODE + len(blob) <= CODE_END, f"blob {len(blob)} B overruns into the SAFE log at 0x{CODE_END:08x}"
    assert not any(img[bd.off(CODE):bd.off(CODE) + len(blob)]), "cave not empty"
    assert not any(img[bd.off(SAFE):bd.off(SAFE) + 12 + 8 * SAFE_CAP]), "SAFE log area not empty"
    assert b"\x2c\x8d" not in blob and b"\x2c\x87" not in blob, "no wdebug operands may appear in rs5"
    img[bd.off(CODE):bd.off(CODE) + len(blob)] = blob
    base = bytes(SRC.read_bytes())
    check_holes(base, [(va, len(exp) // 2) for va, exp, _ in HOOKS])
    for va, exp, name in HOOKS:
        o, hole = bd.off(va), len(exp) // 2
        assert bytes(img[o:o + hole]).hex() == exp, f"0x{va:08x}: {bytes(img[o:o+hole]).hex()} != {exp}"
        img[o:o + 6] = b"\x4e\xf9" + sym[name].to_bytes(4, "big")
        print(f"  hook 0x{va:08x} -> {name} @0x{sym[name]:08x}")
    OUT.write_bytes(bytes(img))
    print(f"blob {len(blob)} B; snapshots of STATE-B[31]@16 = 0x{WATCH:08x} (UI slot 160); "
          f"NO debug module; log @0x{SAFE:08x} (code cave)")
    print("  -> DO NOT USE UI SLOTS 252, 253")
    print(f"{OUT}: {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
