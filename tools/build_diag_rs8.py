#!/usr/bin/env python3
"""build_diag_rs8.py -- WHICH SLOT does the audio engine actually ask for on a trig?

The AED title reads "STATIC 001" after a reload: the track points at slot 1 in the machine/audio layer
while the slot list shows 160. A sample WITHOUT an .ot file behaves identically, so the .ot path
(which clears the generation token) is NOT the cause, and no function on the trig->voice path
(FUN_400977cc / FUN_40005178 / FUN_4000c8a4 / FUN_40097168) contains a 128 bound. That leaves one
explanation: the engine is HANDED the wrong slot number, and the token mismatch measured in P73 is a
consequence -- nothing ever set up the slot the engine never asked for.

Earlier probes only logged resolver calls for idx >= 150, so a call with slot 0 or 1 was invisible.
rs8 logs the slot of EVERY one of the first 16 resolver calls, with a marker at the bulk load loop
exit so before/after-load ordering is unambiguous, and the generation token whenever the slot is high.

  tag 40  bulk STATIC load loop finished (load boundary marker)
  tag 41  voice resolver entry   value = the slot it was asked for  <-- 0/1 here proves the mis-handoff
  tag 42  same call, high slots  value = STRIDE4-B[idx] (the token)

Snapshots only, no debug module (see [[octatrack-hw-probe-safety]]).

PROCEDURE: power-cycle -> play the trig on the high slot (silent) -> SAVE -> mount the CF.
    python3 tools/read_probe.py <project.256> --build build_diag_rs8
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd
from hookcheck import check_holes

SRC = pathlib.Path("out/mainos_persist256.bin")
OUT = pathlib.Path("out/mainos_diag_rs8.bin")
CODE, PROBE = 0x400d7100, 0x40ab65e0
CODE_END = 0x400d7300
MAGIC = 0x10ade111
S42_B = bd.S42_B
SAFE = 0x400d7800        # [0]=cnt  [4]=resolver budget  [12..]=entries; free cave after LOADLOOP_STUB
SAFE_CAP = 40
SC_SAVE = 0x400d6600
LOOP_EXIT = 0x40090902

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

| ================= tag 40: bulk STATIC load loop finished (6B hole: jsr 0x40096a5c) =================
loop_done:
    lea     -20(%sp),%sp
    movem.l %d0-%d2/%a0-%a1,(%sp)
    moveq   #40,%d0
    moveq   #0,%d1
    bsr.w   rec
    movem.l (%sp),%d0-%d2/%a0-%a1
    lea     20(%sp),%sp
    jsr     0x40096a5c                   | replicate the displaced call
    jmp     0x{LOOP_EXIT + 6:x}

| ================= tags 41/42: voice resolver 0x4000f450 entry, EVERY slot (8B hole) ===============
rs_entry:
    lea     -20(%sp),%sp
    movem.l %d0-%d2/%a0-%a1,(%sp)
    lea     0x{SAFE:x},%a0
    move.l  4(%a0),%d0                   | budget: the first 16 calls, whatever slot they name
    cmpi.l  #16,%d0
    bge.b   1f
    addq.l  #1,4(%a0)
    move.l  28(%sp),%d1                  | slot (entry sp@(8), +20)
    moveq   #41,%d0
    bsr.w   rec
    move.l  28(%sp),%d1
    cmpi.l  #128,%d1
    blt.b   1f
    subi.l  #128,%d1
    lsl.l   #2,%d1
    lea     0x{S42_B:x},%a0
    adda.l  %d1,%a0
    move.l  (%a0),%d1                    | STRIDE4-B[idxB] = the generation token
    moveq   #42,%d0
    bsr.w   rec
1:  movem.l (%sp),%d0-%d2/%a0-%a1
    lea     20(%sp),%sp
    lea     -60(%sp),%sp                 | replicate displaced entry
    movem.l %d2-%d7/%a2-%fp,(%sp)
    jmp     0x4000f458

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
           "fields": [("tag", 0, "u32"), ("value", 4, "u32")]},
}

HOOKS = [
    (LOOP_EXIT, "4eb940096a5c", "loop_done"),
    (0x4000f450, "4fefffc448d77cfc", "rs_entry"),
    (SC_SAVE, "2f002f012f02", "sv_copy"),
]


def main():
    img = bytearray(SRC.read_bytes())
    p = "out/_rs8"
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
    print(f"blob {len(blob)} B; logs the slot of every resolver call (first 16) + a load-boundary marker")
    print("  -> DO NOT USE UI SLOTS 252, 253")
    print(f"{OUT}: {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
