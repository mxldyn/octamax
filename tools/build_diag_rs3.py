#!/usr/bin/env python3
"""build_diag_rs3.py -- SNAPSHOT TIMELINE of SET-B[31] (UI slot 160) across a whole project load.

Why snapshots instead of the rs2 watchpoint: the rs1/rs2 counters lived in the PROBE block, which sits
INSIDE SET-B (slots 123/124) -- and the sidecar RESTORES SET-B from project.256 on every load, so the
live counters were overwritten by the previous session's file values. Every count read so far is
suspect. rs3 keeps ALL state in the code cave (SAFE), which nothing restores, and mirrors it into the
PROBE block only at save time.

Instead of catching writes, it photographs SET-B[31].path[0..3] at four points, so the exact step that
loses the slot is visible in one flash, on BOTH the boot auto-load and a manual RELOAD:

  tag 1  loader 0x4009000c ENTRY          value = SET-B[31].path (before any parse)
  tag 2  parser STATIC dest store, idx>=128 (0x400869fc)   value = computed dest ptr (0 = gate rejected)
  tag 3  loader RETURN at its caller (0x40085376)          value = SET-B[31].path (after parse+sidecar)
  tag 4  bulk STATIC loader ENTRY (0x4009083c)             value = SET-B[31].path (before the load loop)
  tag 5  sampleview called with slot>=128 (0x40093980)     value = slot

Reading it: '../A' (0x2e2e2f41) = populated, 0 = empty. tag2 absent at boot means the parser never even
processed the high [SAMPLE] record; tag3 empty after tag2 non-zero means the write landed and was lost
before the loader returned; tag4 empty after tag3 populated means the loss is between load and bulk-load.

PROCEDURE (one flash, two observations):
  1) power-cycle; let the project auto-load; note whether slot 160 has its sample
  2) RELOAD the project; note the same
  3) SAVE, mount the CF
    python3 tools/read_probe.py <project.256> --build build_diag_rs3
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd
from hookcheck import check_holes

SRC = pathlib.Path("out/mainos_persist256.bin")
OUT = pathlib.Path("out/mainos_diag_rs3.bin")
CODE, PROBE = 0x400d7100, 0x40ab65e0
CODE_END = 0x400d7300
MAGIC = 0x10ade111
WATCH = 0x40a9da98           # SET-B[31].path[0..3]  (UI slot 160)
SAFE = 0x400d7300            # [0]=cnt, [4..0xfc]=31 entries x 8B; code cave, never restored
SAFE_CAP = 31
SC_SAVE = 0x400d6600         # sidecar_save entry (6B: three pushes)

ASM = f"""    .cpu 5407
    .text
| ---- rec: append (d0=tag, d1=value) to the SAFE log. Clobbers d2/a0/a1 only. ----
rec:
    lea     0x{SAFE:x},%a0
    move.l  (%a0),%d2
    cmpi.l  #{SAFE_CAP},%d2
    bge.b   rec_out
    addq.l  #1,(%a0)
    lsl.l   #3,%d2
    lea     4(%a0),%a1
    adda.l  %d2,%a1
    move.l  %d0,(%a1)
    move.l  %d1,4(%a1)
rec_out:
    rts

| ================= tag 1: project loader 0x4009000c ENTRY (8B hole) =================
ld_entry:
    lea     -20(%sp),%sp
    movem.l %d0-%d2/%a0-%a1,(%sp)
    moveq   #1,%d0
    move.l  0x{WATCH:x},%d1
    bsr.w   rec
    movem.l (%sp),%d0-%d2/%a0-%a1
    lea     20(%sp),%sp
    linkw   %fp,#-576                    | replicate displaced entry
    movem.l %d2-%d6/%a2-%a4,(%sp)
    jmp     0x40090014

| ================= tag 2: parser STATIC dest store 0x400869fc (6B hole) =================
| d0 = computed dest (0 when a gate rejected it); *(0x400d1668) = slot idx.
p_dest:
    lea     -20(%sp),%sp
    movem.l %d0-%d2/%a0-%a1,(%sp)
    move.l  0x400d1668,%d2               | idx
    cmpi.l  #128,%d2
    blt.b   1f
    move.l  %d0,%d1                      | value = dest ptr
    moveq   #2,%d0
    bsr.w   rec
1:  movem.l (%sp),%d0-%d2/%a0-%a1
    lea     20(%sp),%sp
    move.l  %d0,0x460fab50               | replicate displaced store
    jmp     0x40086a02

| ================= tag 3: loader RETURN, at its caller 0x40085376 (6B hole) =================
| d0 = loader return value -- must survive, and the replicated `tstl d0` must set CC last.
ld_ret:
    lea     -20(%sp),%sp
    movem.l %d0-%d2/%a0-%a1,(%sp)
    moveq   #3,%d0
    move.l  0x{WATCH:x},%d1
    bsr.w   rec
    movem.l (%sp),%d0-%d2/%a0-%a1
    lea     20(%sp),%sp
    lea     20(%sp),%sp                  | replicate: lea sp@(20),sp
    tst.l   %d0                          | replicate: tstl d0 (sets CC for the caller's bge)
    jmp     0x4008537c

| ================= tag 4: bulk STATIC loader 0x4009083c ENTRY (6B hole) =================
| Hole splits the moveml, so replicate BOTH the lea and the full moveml, then jmp past the orphan.
bl_entry:
    lea     -20(%sp),%sp
    movem.l %d0-%d2/%a0-%a1,(%sp)
    moveq   #4,%d0
    move.l  0x{WATCH:x},%d1
    bsr.w   rec
    movem.l (%sp),%d0-%d2/%a0-%a1
    lea     20(%sp),%sp
    lea     -44(%sp),%sp                 | replicate displaced entry
    movem.l %d2-%d7/%a2-%fp,(%sp)
    jmp     0x40090844

| ================= tag 5: sampleview 0x40093980 with slot>=128 (8B hole) =================
sv_entry:
    lea     -20(%sp),%sp
    movem.l %d0-%d2/%a0-%a1,(%sp)
    move.l  24(%sp),%d2                  | slot (entry sp@(4), +20)
    cmpi.l  #128,%d2
    blt.b   2f
    move.l  %d2,%d1
    moveq   #5,%d0
    bsr.w   rec
2:  movem.l (%sp),%d0-%d2/%a0-%a1
    lea     20(%sp),%sp
    linkw   %fp,#-380                    | replicate displaced entry
    movem.l %d2-%d7/%a2-%a4,(%sp)
    jmp     0x40093988

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
    lea     0x{SAFE + 4:x},%a1
    moveq   #62,%d1                      | 31 entries x 8B = 62 longs
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
    (0x4009000c, "4e56fdc048d71c7c", "ld_entry"),
    (0x400869fc, "23c0460fab50", "p_dest"),
    (0x40085376, "4fef00144a80", "ld_ret"),
    (0x4009083c, "4fefffd448d7", "bl_entry"),
    (0x40093980, "4e56fe8448d71cfc", "sv_entry"),
    (SC_SAVE, "2f002f012f02", "sv_copy"),
]


def main():
    img = bytearray(SRC.read_bytes())
    p = "out/_rs3"
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
    assert not any(img[bd.off(SAFE):bd.off(SAFE) + 4 + 8 * SAFE_CAP]), "SAFE log area not empty"
    img[bd.off(CODE):bd.off(CODE) + len(blob)] = blob
    base = bytes(SRC.read_bytes())
    check_holes(base, [(va, len(exp) // 2) for va, exp, _ in HOOKS])
    for va, exp, name in HOOKS:
        o, hole = bd.off(va), len(exp) // 2
        assert bytes(img[o:o + hole]).hex() == exp, f"0x{va:08x}: {bytes(img[o:o+hole]).hex()} != {exp}"
        img[o:o + 6] = b"\x4e\xf9" + sym[name].to_bytes(4, "big")
        print(f"  hook 0x{va:08x} -> {name} @0x{sym[name]:08x}")
    OUT.write_bytes(bytes(img))
    print(f"blob {len(blob)} B; SET-B[31] snapshot timeline; log @0x{SAFE:08x} (code cave, restore-proof)")
    print("  -> DO NOT USE UI SLOTS 252, 253")
    print(f"{OUT}: {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
