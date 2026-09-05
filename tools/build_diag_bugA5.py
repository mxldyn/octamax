#!/usr/bin/env python3
"""build_diag_bugA5.py -- BUG A HARDWARE WATCHPOINT via the MCF5407 ColdFire debug module.

Programs an operand-address breakpoint (write) on the track-slot field and vectors the resulting
debug interrupt (non-PC breakpoint = vector 12, offset 0x030) to a handler that records the stacked
PC + the field's byte value on EVERY write. This catches the reload clear directly (imprecise: the
stacked PC is a few instructions past the store, but names the function).

Verified against MCF5407UM (Rev C debug):
  - WDMREG/WDEBUG operand = 3 words: word0 = 0x2C80|DRc, then D[31:16], D[15:0].
  - DRc: CSR 0x00, AATR 0x06, TDR 0x07, ABHR 0x0C, ABLR 0x0D.
  - AATR 0x7F00 = compare R (R=0 write), mask size/TT/TM -> match any write.
  - TDR 0x80002004 = TRC=10 (debug interrupt) + EBL(13) + EAL(2), first-level address-low trigger.
  - Vector 12 (0x030) at VBR+0x30; VBR = *(0x400b9668) = 0x40000000 (nothing writes that var).
  - Exception frame: [SR/Format/Vector long][PC long]; handler reads PC, RTE returns.

ARM at the assign hook 0x400795ba (a0 = field addr): store field addr, install handler at 0x40000030,
program TDR=0 -> AATR -> ABLR=field -> TDR=enable. The assign's own store fires first (expect value=159),
then reload writes fire. HANDLER records [PC][field byte] into a ring (cap 16) then re-writes TDR to clear BSTAT
(level-sensitive trigger status) and re-arm -- without this the debug interrupt re-fires and hangs.

PROCEDURE: SAME track, assign UI 160, SAVE, RELOAD, (play), SAVE. Delete project.256 first. Avoid 252/253.
    python3 tools/read_probe.py <project.256> --build build_diag_bugA5
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd
from hookcheck import check_holes

SRC = pathlib.Path("out/mainos_persist256.bin")
BASE_VA = 0x40000400
OUT = pathlib.Path("out/mainos_diag_bugA5.bin")
CODE, PROBE = 0x400d7100, 0x40ab65e0
MAGIC = 0x10ade111
BANKPTR = 0x46c82456
VEC12 = 0x40000030          # VBR(0x40000000) + vector 12*4

ASM = f"""    .cpu 5407
    .text
| ---- ring allocator (d0=cap,d1=cnt off,d2=arr off,d3=size -> a1; clobbers d0-d2,a0,a1) ----
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

| ================= ARM: assign hook 0x400795ba -- ONLY record the field addr (nothing dangerous) ==
| The interactive assign must run untouched: NO debug programming, NO vector install here. Just capture
| the field addr (a0 after the replicated addal) for en_probe to use at reload. a0 and d1 (value) survive.
arm_probe:
    adda.l  #0x8f04a,%a0                 | a0 = field addr (replicate; MUST survive to 0x400795c0)
    lea     -12(%sp),%sp
    movem.l %d0/%a1-%a2,(%sp)            | save scratch (a0 and d1 preserved)
    lea     0x{PROBE:x},%a1
    move.l  #0x{MAGIC:x},(%a1)
    move.l  %a0,%d0
    movea.l #0x{BANKPTR:x},%a2
    sub.l   (%a2),%d0                    | d0 = offset = fieldaddr - *(bankptr)
    move.l  %d0,0x10(%a1)                | PROBE+0x10 = OFFSET (reload recomputes the absolute addr)
    move.l  %a0,0x40(%a1)                | AS[0].addr (absolute, reference)
    move.l  %d1,0x44(%a1)                | AS[0].value
    moveq   #1,%d0
    move.l  %d0,0x08(%a1)                | cntAS = 1
    movem.l (%sp),%d0/%a1-%a2
    lea     12(%sp),%sp
    jmp     0x400795c0

| ================= vector-12 debug-interrupt handler =================
| Frame at entry: sp@(0)=[SR/Format/Vector], sp@(4)=PC. Non-PC breakpoint is imprecise (PC is a few
| instructions past the store). Records [PC][field byte value] each write; RTE.
bp_handler:
    lea     -24(%sp),%sp
    movem.l %d0-%d3/%a0-%a1,(%sp)
    moveq   #16,%d0
    moveq   #4,%d1                       | cntBP
    move.l  #0xa0,%d2                    | BP arr
    moveq   #8,%d3
    bsr.w   rec_alloc
    move.l  %a1,%d0
    tst.l   %d0
    beq.b   bp_ret
    move.l  28(%sp),%d0                  | stacked PC (frame long1 = sp@(24)+4)
    move.l  %d0,(%a1)
    movea.l #0x{PROBE + 0x18:x},%a0
    movea.l (%a0),%a0                    | field addr
    moveq   #0,%d0
    move.b  (%a0),%d0
    move.l  %d0,4(%a1)                   | field byte value at this write
bp_ret:
    lea     ten,%a0                      | ACK: re-write TDR to clear CSR[BSTAT] (level) and re-arm,
    wdebug  (%a0)                        | else the trigger stays asserted and re-fires -> hang
    movem.l (%sp),%d0-%d3/%a0-%a1
    lea     24(%sp),%sp
    rte

| ================= EN: STATIC bulk-load 0x400908ac -- do ALL debug setup, arms ONLY at reload =========
| The bank worker 0x40091164 does NOT fire on a project RELOAD (en_armed=0 proved it). The bulk-load DOES
| fire on reload. It also fires on an in-session sample load, but en_probe only arms when an OFFSET was
| captured by a prior assign (PROBE+0x10!=0); the sample load happens BEFORE the assign, so offset=0 then
| and en_probe skips -- the interactive select stays clean. Replicates `movel d0,d2 ; addql #8,sp ; bge`.
en_probe:
    lea     -20(%sp),%sp
    movem.l %d0-%d1/%a0-%a2,(%sp)
    lea     0x{PROBE:x},%a0
    move.l  0x10(%a0),%d0                | OFFSET captured at assign
    beq.b   en_skip
    movea.l #0x{BANKPTR:x},%a1
    move.l  (%a1),%d1                    | current bankbase
    add.l   %d1,%d0                      | d0 = fieldaddr = bankbase + offset (RELOAD-time absolute)
    move.l  %d0,0x18(%a0)                | PROBE+0x18 = computed field addr (handler reads value here)
    move.l  %d1,0x1c(%a0)                | PROBE+0x1c = reload bankbase (diag)
    addq.l  #1,0x14(%a0)                 | PROBE+0x14 = en_armed counter
    move.l  #bp_handler,%d1
    move.l  %d1,0x{VEC12:x}              | install vector-12 handler
    lea     twdis,%a2
    wdebug  (%a2)                        | TDR = 0 (disable while loading regs)
    lea     taatr,%a2
    wdebug  (%a2)                        | AATR = 0x7F00
    lea     ablrcmd,%a2
    move.w  #0x2c8d,(%a2)
    move.l  %d0,2(%a2)                   | ABLR = field addr
    wdebug  (%a2)
    lea     ten,%a2
    wdebug  (%a2)                        | TDR = enable
en_skip:
    movem.l (%sp),%d0-%d1/%a0-%a2
    lea     20(%sp),%sp
    move.l  %d0,%d2                      | replicate movel d0,d2
    addq.l  #8,%sp                       | replicate addql #8,sp
    bge.b   en_go
    jmp     0x400908b2
en_go:
    jmp     0x400908d8

    .balign 4
twdis:  .byte 0x2c,0x87, 0x00,0x00, 0x00,0x00, 0x00,0x00      | TDR=0 (disable); 8B, 4-aligned (wdebug.l needs aligned operand)
    .balign 4
taatr:  .byte 0x2c,0x86, 0x00,0x00, 0x7f,0x00, 0x00,0x00      | AATR = 0x00007F00 (match any write)
    .balign 4
ten:    .byte 0x2c,0x87, 0x80,0x00, 0x20,0x04, 0x00,0x00      | TDR = 0x80002004 (TRC=debug int, EBL+EAL)
    .balign 4
ablrcmd: .byte 0x2c,0x8d, 0x00,0x00, 0x00,0x00, 0x00,0x00     | ABLR (word0), operand filled at runtime
    .balign 4
"""

LAYOUT = {
    "AS": {"counter": 0x08, "array": 0x40, "entry": 12, "cap": 8,
           "fields": [("off", 0, "hex"), ("value", 4, "s32")]},
    "BP": {"counter": 0x04, "array": 0xa0, "entry": 8, "cap": 16,
           "fields": [("PC", 0, "hex"), ("field_value", 4, "s32")]},
    "DIAG": {"counter": 0x14, "array": 0x18, "entry": 8, "cap": 1,
             "fields": [("computed_ABLR", 0, "hex"), ("reload_bankbase", 4, "hex")]},
}

HOOKS = [
    (0x400795ba, "d1fc0008f04a", "arm_probe"),
    (0x400908ac, "2400508f6c26", "en_probe"),
]


def main():
    img = bytearray(SRC.read_bytes())
    p = "out/_bugA5"
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
    print(f"blob {len(blob)} B; HW watchpoint on the track-slot field; handler @0x{sym['bp_handler']:08x}; vec12@0x{VEC12:08x}")
    print(f"  regs: AATR=0x7F00 ABLR=field TDR=0x80002004 (TRC=debug-int). VBR=0x40000000.")
    print("  -> DO NOT USE UI SLOTS 252, 253")
    print(f"{OUT}: {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
