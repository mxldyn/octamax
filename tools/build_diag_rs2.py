#!/usr/bin/env python3
"""build_diag_rs2.py -- catch the SET-B WIPER with the proven MCF5407 debug-module watchpoint.

Established (probe rs1 + full-file parser emulation): the project.work parser DOES write
SET-B[31].path ('../AUDIO/afo-melero.aif' at 0x40a9da98) on load, yet by bulk-load time SET-B is
empty (SV ring: zero high-slot sampleview calls; saved project.256/work: all-empty). Something wipes
the reserve between the parse and the bulk loop -- and it also zeroes the rs1 probe block (same
reserve), which is why early ring entries vanished.

This build arms a HW watchpoint on 0x40a9da98 (SET-B[31].path[0], FIXED VA -- no moving-buffer offset
dance this time) at the entry of the project loader 0x4009000c, BEFORE the parse. The vector-12
handler records [stacked PC][byte value] per write into a ring at SAFE=0x400d7300 -- OUTSIDE the
reserve (the code region is writable RAM; the sidecar's own pathbuf proves it), so the wiper cannot
destroy the evidence. A hook at sidecar_save's entry (0x400d6600) copies the ring into the PROBE
block right before project.256 is written, so read_probe sees it.

Watchpoint regs verified in P63 (bugA5): AATR=0x7F00 any-write, TDR=0x80002004 debug interrupt,
vector 12 @0x40000030, handler re-writes TDR to ack (level-sensitive BSTAT).

PROCEDURE: flash, load the project (slot 160 on a track), SAVE, mount CF. Avoid UI slots 252/253.
    python3 tools/read_probe.py <project.256> --build build_diag_rs2
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd
from hookcheck import check_holes

SRC = pathlib.Path("out/mainos_persist256.bin")
OUT = pathlib.Path("out/mainos_diag_rs2.bin")
CODE, PROBE = 0x400d7100, 0x40ab65e0
MAGIC = 0x10ade111
WATCH_ADDR = 0x40a9da98      # SET-B[31].path[0]  (UI slot 160)
VEC12 = 0x40000030
SAFE = 0x400d7300            # wipe-proof ring: [0]=cntBP, [4..] 16 x 8B entries (cave RAM, outside reserve)
SC_SAVE = 0x400d6600         # sidecar_save entry (6B hole: 2f00 2f01 2f02, three pushes)

ASM = f"""    .cpu 5407
    .text
| ============ EN: project-loader entry 0x4009000c (8B hole: linkw fp,#-576 ; moveml) ============
| Arms the watchpoint BEFORE the parse. Runs only on project load (sole caller = the cmd-27 case),
| so interactive select/assign flows never touch the debug module (P58-P61 lesson).
en_probe:
    lea     -12(%sp),%sp
    movem.l %d0/%a0-%a1,(%sp)
    lea     0x{PROBE:x},%a0
    move.l  #0x{MAGIC:x},%d0
    move.l  %d0,(%a0)
    addq.l  #1,0x14(%a0)                 | en counter
    move.l  #bp_handler,%d0
    move.l  %d0,0x{VEC12:x}              | install vector-12 handler
    lea     twdis,%a1
    wdebug  (%a1)                        | TDR = 0 while loading regs
    lea     taatr,%a1
    wdebug  (%a1)                        | AATR = 0x7F00 (any write)
    lea     tablr,%a1
    wdebug  (%a1)                        | ABLR = WATCH_ADDR (fixed)
    lea     ten,%a1
    wdebug  (%a1)                        | TDR = enable (debug interrupt)
    movem.l (%sp),%d0/%a0-%a1
    lea     12(%sp),%sp
    linkw   %fp,#-576                    | replicate displaced entry
    movem.l %d2-%d6/%a2-%a4,(%sp)
    jmp     0x40090014

| ============ vector-12 debug-interrupt handler ============
| Frame: sp@(0)=[SR/Fmt/Vec], sp@(4)=PC (imprecise, a few instrs past the store).
| Records into the wipe-proof SAFE ring (cave RAM outside the reserve).
bp_handler:
    lea     -24(%sp),%sp
    movem.l %d0-%d2/%a0-%a1,(%sp)        | 5 regs = 20B (frame 24 keeps 4 spare)
    lea     0x{SAFE:x},%a0
    move.l  (%a0),%d0                    | cntBP
    addq.l  #1,(%a0)
    cmpi.l  #16,%d0
    bge.b   1f
    lsl.l   #3,%d0
    lea     4(%a0),%a1
    adda.l  %d0,%a1
    move.l  28(%sp),%d0                  | stacked PC (24 frame + 4)
    move.l  %d0,(%a1)
    lea     0x{WATCH_ADDR:x},%a0
    moveq   #0,%d0
    move.b  (%a0),%d0
    move.l  %d0,4(%a1)                   | byte value after this write
1:  lea     ten,%a0                      | ACK: re-write TDR (clears level BSTAT) + re-arm
    wdebug  (%a0)
    movem.l (%sp),%d0-%d2/%a0-%a1
    lea     24(%sp),%sp
    rte

| ============ SAVE copy: sidecar_save entry 0x400d6600 (6B hole: three pushes) ============
| Copies the SAFE ring into the PROBE block right before project.256 is written.
sv_copy:
    lea     -16(%sp),%sp
    movem.l %d0-%d1/%a0-%a1,(%sp)
    lea     0x{PROBE:x},%a0
    move.l  #0x{MAGIC:x},%d0
    move.l  %d0,(%a0)
    move.l  0x{SAFE:x},%d0
    move.l  %d0,0x10(%a0)                | cntBP -> PROBE+0x10
    lea     0x1a0(%a0),%a0
    lea     0x{SAFE + 4:x},%a1
    moveq   #32,%d1                      | 16 entries x 8B = 32 longs
2:  move.l  (%a1)+,(%a0)+
    subq.l  #1,%d1
    bne.b   2b
    movem.l (%sp),%d0-%d1/%a0-%a1
    lea     16(%sp),%sp
    move.l  %d0,-(%sp)                   | replicate displaced pushes
    move.l  %d1,-(%sp)
    move.l  %d2,-(%sp)
    jmp     0x{SC_SAVE + 6:x}

    .balign 4
twdis:  .byte 0x2c,0x87, 0x00,0x00, 0x00,0x00, 0x00,0x00      | TDR = 0
    .balign 4
taatr:  .byte 0x2c,0x86, 0x00,0x00, 0x7f,0x00, 0x00,0x00      | AATR = 0x00007F00
    .balign 4
ten:    .byte 0x2c,0x87, 0x80,0x00, 0x20,0x04, 0x00,0x00      | TDR = 0x80002004
    .balign 4
tablr:  .byte 0x2c,0x8d, 0x{(WATCH_ADDR >> 24) & 0xff:02x},0x{(WATCH_ADDR >> 16) & 0xff:02x}, 0x{(WATCH_ADDR >> 8) & 0xff:02x},0x{WATCH_ADDR & 0xff:02x}, 0x00,0x00   | ABLR = WATCH_ADDR
    .balign 4
"""

LAYOUT = {
    "EN": {"counter": 0x14, "array": 0x14, "entry": 4, "cap": 0, "fields": []},
    "BP": {"counter": 0x10, "array": 0x1a0, "entry": 8, "cap": 16,
           "fields": [("PC", 0, "hex"), ("value", 4, "s32")]},
}

HOOKS = [
    (0x4009000c, "4e56fdc048d71c7c", "en_probe"),
    (SC_SAVE, "2f002f012f02", "sv_copy"),
]


def main():
    img = bytearray(SRC.read_bytes())
    p = "out/_rs2"
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
    assert CODE + len(blob) <= SAFE, f"blob {len(blob)} overruns into the SAFE ring at 0x{SAFE:08x}"
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
    print(f"blob {len(blob)} B; HW watchpoint on SET-B[31].path[0] 0x{WATCH_ADDR:08x}; handler @0x{sym['bp_handler']:08x}")
    print("  -> DO NOT USE UI SLOTS 252, 253")
    print(f"{OUT}: {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
