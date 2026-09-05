#!/usr/bin/env python3
"""build_diag_rs4.py -- RELOAD-SILENCE: who sets, and who clears, STATE-B[31]@16 (the field that
decides whether a high slot's voice binds)?

Where wave 23 left it: after a power-cycle the high slot now APPEARS (persistence fixed), but it stays
MUTE until the AED is opened once -- while a sample loaded into a high slot in-session plays fine. The
bind test (proved in tools/emu_silentuntilaed.py) is STATE[slot]@16 > 0 && @8 == 0, and sampleview
FUN_40093980 is what writes @16 (0x40093c92). So exactly one of these is true:

  (a) the bulk STATIC load loop never calls sampleview for the restored high slot  -> no tag2
  (b) it does, and something CLEARS @16 afterwards                                 -> tag2 + a tag4/5 zero write

This build answers both in one flash. It arms the proven MCF5407 watchpoint (P63 machinery) on the
FIXED address STATE-B[31]@16 = 0x40ab7f44 (UI slot 160) at the first sampleview call of the session,
so every later write to that field is recorded with its PC. It also logs each sampleview call for a
high slot, and what the voice-bind resolver actually sees at play time.

  tag 1  watchpoint armed (first sampleview call)      value = the slot that triggered arming
  tag 2  sampleview called with slot >= 128            value = slot        <-- (a) is false if present
  tag 3  voice resolver entry, slot >= 128 (max 4)     value = slot
  tag 4  write to STATE-B[31]@16 -- stacked PC (imprecise: a few instructions past the store)
  tag 5  write to STATE-B[31]@16 -- the value now in the field (0 = someone cleared it)
  tag 6  voice resolver entry, slot >= 128 (max 4)     value = that slot's own @16 at play time

All state lives in the code cave (SAFE), which nothing restores -- the PROBE block sits inside SET-B,
which the sidecar rewrites on every load, so probe state must never live there. It is mirrored into
the PROBE block at sidecar_save time.

PROCEDURE (one flash): power-cycle -> play the trig on the high slot (silent) -> open the AED and let
the waveform draw -> play again (sounds) -> SAVE -> mount the CF. Avoid UI slots 252/253.
    python3 tools/read_probe.py <project.256> --build build_diag_rs4
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd
from hookcheck import check_holes

SRC = pathlib.Path("out/mainos_persist256.bin")
OUT = pathlib.Path("out/mainos_diag_rs4.bin")
CODE, PROBE = 0x400d7100, 0x40ab65e0
CODE_END = 0x400d7300
MAGIC = 0x10ade111
ST_B, ST_STRIDE = bd.ST_B, bd.ST_STRIDE          # 0x40ab79e0, 44
WATCH = ST_B + 31 * ST_STRIDE + 16               # STATE-B[31]@16 -> UI slot 160
VEC12 = 0x40000030
SAFE = 0x400d7300        # [0]=cnt  [4]=armed  [8]=resolver budget  [12..]=entries (8B each)
SAFE_CAP = 28
SC_SAVE = 0x400d6600     # sidecar_save entry (6B: three pushes)

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

| ================= sampleview 0x40093980 entry (8B hole) =================
| Arms the watchpoint on the FIRST call of the session (the bulk load loop reaches the low slots
| first, so it is armed well before any high slot is touched), and logs every high-slot call.
sv_entry:
    lea     -20(%sp),%sp
    movem.l %d0-%d2/%a0-%a1,(%sp)
    move.l  24(%sp),%d1                  | slot (entry sp@(4), +20)
    lea     0x{SAFE:x},%a0
    tst.l   4(%a0)                       | already armed?
    bne.b   1f
    moveq   #1,%d0
    move.l  %d0,4(%a0)
    move.l  %d1,-(%sp)                   | keep slot across the arming
    move.l  #bp_handler,%d0
    move.l  %d0,0x{VEC12:x}              | install vector-12 handler
    lea     twdis,%a1
    wdebug  (%a1)                        | TDR = 0 while loading regs
    lea     taatr,%a1
    wdebug  (%a1)                        | AATR = 0x7F00 (match any write)
    lea     tablr,%a1
    wdebug  (%a1)                        | ABLR = STATE-B[31]@16
    lea     ten,%a1
    wdebug  (%a1)                        | TDR = enable (debug interrupt)
    move.l  (%sp)+,%d1
    moveq   #1,%d0
    bsr.w   rec                          | tag1 = armed (value = the slot that armed it)
1:  move.l  24(%sp),%d1                  | slot again (rec clobbered d1? no -- reload to be safe)
    cmpi.l  #128,%d1
    blt.b   2f
    moveq   #2,%d0
    bsr.w   rec                          | tag2 = sampleview for a HIGH slot
2:  movem.l (%sp),%d0-%d2/%a0-%a1
    lea     20(%sp),%sp
    linkw   %fp,#-380                    | replicate displaced entry
    movem.l %d2-%d7/%a2-%a4,(%sp)
    jmp     0x40093988

| ================= voice-bind resolver 0x4000f450 entry (8B hole) =================
| Records what the resolver sees for a high slot at PLAY time: the slot and its own @16.
rs_entry:
    lea     -20(%sp),%sp
    movem.l %d0-%d2/%a0-%a1,(%sp)
    move.l  28(%sp),%d1                  | slot (entry sp@(8), +20)
    cmpi.l  #128,%d1
    blt.b   4f
    lea     0x{SAFE:x},%a0
    move.l  8(%a0),%d0                   | resolver budget
    cmpi.l  #4,%d0
    bge.b   4f
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
    move.l  16(%a0),%d1                  | that slot's @16 at play time
    moveq   #6,%d0
    bsr.w   rec                          | tag6 = @16 (0 -> the voice cannot bind = SILENT)
4:  movem.l (%sp),%d0-%d2/%a0-%a1
    lea     20(%sp),%sp
    lea     -60(%sp),%sp                 | replicate displaced entry
    movem.l %d2-%d7/%a2-%fp,(%sp)
    jmp     0x4000f458

| ================= vector-12 debug-interrupt handler =================
bp_handler:
    lea     -24(%sp),%sp
    movem.l %d0-%d2/%a0-%a1,(%sp)
    move.l  28(%sp),%d1                  | stacked PC (24 frame + 4)
    moveq   #4,%d0
    bsr.w   rec
    move.l  0x{WATCH:x},%d1              | the value now in the field
    moveq   #5,%d0
    bsr.w   rec
    lea     ten,%a0                      | ACK: re-write TDR (clears level BSTAT) + re-arm
    wdebug  (%a0)
    movem.l (%sp),%d0-%d2/%a0-%a1
    lea     24(%sp),%sp
    rte

| ================= SAVE: mirror SAFE -> PROBE at sidecar_save entry (6B hole) =================
sv_copy:
    lea     -16(%sp),%sp
    movem.l %d0-%d1/%a0-%a1,(%sp)
    lea     0x{PROBE:x},%a0
    move.l  #0x{MAGIC:x},%d0
    move.l  %d0,(%a0)
    move.l  0x{SAFE:x},%d0
    move.l  %d0,0x10(%a0)                | cnt -> PROBE+0x10
    lea     0x1a0(%a0),%a0
    lea     0x{SAFE + 12:x},%a1
    moveq   #{SAFE_CAP * 2},%d1          | entries x 8B, as longs
5:  move.l  (%a1)+,(%a0)+
    subq.l  #1,%d1
    bne.b   5b
    movem.l (%sp),%d0-%d1/%a0-%a1
    lea     16(%sp),%sp
    move.l  %d0,-(%sp)                   | replicate displaced pushes
    move.l  %d1,-(%sp)
    move.l  %d2,-(%sp)
    jmp     0x{SC_SAVE + 6:x}

    .balign 4
twdis:  .byte 0x2c,0x87, 0x00,0x00, 0x00,0x00, 0x00,0x00      | TDR = 0
    .balign 4
taatr:  .byte 0x2c,0x86, 0x00,0x00, 0x7f,0x00, 0x00,0x00      | AATR = 0x00007F00 (any write)
    .balign 4
ten:    .byte 0x2c,0x87, 0x80,0x00, 0x20,0x04, 0x00,0x00      | TDR = 0x80002004 (debug interrupt)
    .balign 4
tablr:  .byte 0x2c,0x8d, 0x{(WATCH >> 24) & 0xff:02x},0x{(WATCH >> 16) & 0xff:02x}, 0x{(WATCH >> 8) & 0xff:02x},0x{WATCH & 0xff:02x}, 0x00,0x00   | ABLR = STATE-B[31]@16
    .balign 4
"""

LAYOUT = {
    "EV": {"counter": 0x10, "array": 0x1a0, "entry": 8, "cap": SAFE_CAP,
           "fields": [("tag", 0, "u32"), ("value", 4, "hex")]},
}

HOOKS = [
    (0x40093980, "4e56fe8448d71cfc", "sv_entry"),
    (0x4000f450, "4fefffc448d77cfc", "rs_entry"),
    (SC_SAVE, "2f002f012f02", "sv_copy"),
]


def main():
    img = bytearray(SRC.read_bytes())
    p = "out/_rs4"
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
    img[bd.off(CODE):bd.off(CODE) + len(blob)] = blob
    base = bytes(SRC.read_bytes())
    check_holes(base, [(va, len(exp) // 2) for va, exp, _ in HOOKS])
    for va, exp, name in HOOKS:
        o, hole = bd.off(va), len(exp) // 2
        assert bytes(img[o:o + hole]).hex() == exp, f"0x{va:08x}: {bytes(img[o:o+hole]).hex()} != {exp}"
        img[o:o + 6] = b"\x4e\xf9" + sym[name].to_bytes(4, "big")
        print(f"  hook 0x{va:08x} -> {name} @0x{sym[name]:08x}")
    OUT.write_bytes(bytes(img))
    print(f"blob {len(blob)} B; watchpoint on STATE-B[31]@16 = 0x{WATCH:08x} (UI slot 160); "
          f"log @0x{SAFE:08x} (code cave)")
    print("  -> DO NOT USE UI SLOTS 252, 253")
    print(f"{OUT}: {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
