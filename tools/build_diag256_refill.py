#!/usr/bin/env python3
"""build_diag256_refill.py -- the resolver BINDS idx=128 (voice@4 = STATE-B[0]) but no sound. The per-frame
PCM refill FUN_40091d18 feeds the DSP; it processes a voice only if a2@20==0 (STATIC type byte) AND
STATE@8==0 AND a2@0!=0 (voice active). This probe checks, for the voice whose STATE ptr == STATE-B[0]
(the slot-128 voice), whether it passes those gates -- i.e. whether the PCM refill actually runs for it.

Hook 0x40091d90 (`moveal a2@(4),a3 ; movel a3@(8),d0` = 8 bytes; a3 = voice's STATE ptr).

PROBE @0x40aa67e0 -> project.256[0x11200]:
  [0x00] count (times the slot-128 voice seen in refill)  [0x04] a2@20 (type byte, want 0)
  [0x08] a2@0 (active byte, want !=0)  [0x0c] STATE@8 (want 0)  [0x1c] magic 0xDF111D18

Do (one session): RELOAD -> assign slot 129 -> TRIG -> PLAY -> SAVE.

    python3 tools/build_diag256_refill.py   # -> out/mainos_diag_refill.bin  (package as DUAL256P24)
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd

SRC = pathlib.Path("out/mainos_persist256.bin")
OUT = pathlib.Path("out/mainos_diag_refill.bin")
CODE = 0x400d6a00
PROBE = 0x40aa67e0
HOOK = 0x40091d90             # moveal a2@(4),a3 ; movel a3@(8),d0   (266a0004 202b0008)
BACK = 0x40091d98
STATE_B0 = 0x40ab79e0

ASM = f"""    .cpu 5407
    .text
refill_probe:
    move.l  %a2@(4),%a3
    cmpa.l  #0x{STATE_B0:x},%a3
    bne.b   1f
    move.l  %d0,-(%sp)
    move.l  %a0,-(%sp)
    lea     0x{PROBE:x},%a0
    move.l  #0xdf111d18,%d0
    move.l  %d0,0x1c(%a0)
    addq.l  #1,%a0@
    moveq   #0,%d0
    move.b  %a2@(20),%d0
    move.l  %d0,4(%a0)
    moveq   #0,%d0
    move.b  %a2@,%d0
    move.l  %d0,8(%a0)
    move.l  %a3@(8),%d0
    move.l  %d0,12(%a0)
    move.l  %sp@+,%a0
    move.l  %sp@+,%d0
1:  move.l  %a3@(8),%d0
    jmp     0x{BACK:x}
"""


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC}")
    img = bytearray(SRC.read_bytes())
    p = "out/_rfl"
    pathlib.Path(p + ".s").write_text(ASM)
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", p + ".o", p + ".s"], check=True)
    subprocess.run(["m68k-elf-ld", "-Ttext=0x%x" % CODE, "-o", p + ".elf", p + ".o"], capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", p + ".elf", p + ".bin"], check=True)
    blob = pathlib.Path(p + ".bin").read_bytes()
    for f in (".s", ".o", ".elf", ".bin"):
        pathlib.Path(p + f).unlink(missing_ok=True)
    assert not any(img[bd.off(CODE):bd.off(CODE) + len(blob)]), "cave not empty"
    img[bd.off(CODE):bd.off(CODE) + len(blob)] = blob
    o = bd.off(HOOK)
    assert bytes(img[o:o + 8]) == b"\x26\x6a\x00\x04\x20\x2b\x00\x08", img[o:o + 8].hex()
    img[o:o + 6] = b"\x4e\xf9" + CODE.to_bytes(4, "big")
    img[o + 6:o + 8] = b"\x4e\x71"
    OUT.write_bytes(bytes(img))
    print(f"diag-refill: {len(blob)} B @0x{CODE:08x}; hook 0x{HOOK:08x} -> slot-128 voice refill gate")
    print(f"{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
