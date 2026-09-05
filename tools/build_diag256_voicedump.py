#!/usr/bin/env python3
"""build_diag256_voicedump.py -- DECISIVE comprehensive diff. Everything measured is structurally identical
between a playing low slot and idx=128. Dump the FULL 168-byte voice struct for the idx=128 voice AND a
working low-slot STATIC voice, in one session, and diff them offline. The one field that differs (beyond
the STATE/SETTINGS pointers and stream positions) is the bug -- or confirms the divergence is DSP-side.

Hook 0x40091d9e (in the per-frame refill; a2 = voice struct, a2@(4) = its STATE ptr).

PROBE @0x40aa67e0 -> project.256[0x11200]:
  [0x000] count128  [0x004] countlow  [0x008] magic 0x7C1CE000
  [0x010 .. 0x0b8]  idx=128 voice struct (168 bytes)
  [0x0c0 .. 0x168]  low-slot voice struct (168 bytes)

Do (one session): RELOAD -> assign slot 129 -> trig on that track -> ensure a low-slot track also plays
-> PLAY both -> SAVE.

    python3 tools/build_diag256_voicedump.py   # -> out/mainos_diag_vdump.bin  (package as DUAL256P27)
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd

SRC = pathlib.Path("out/mainos_persist256.bin")
OUT = pathlib.Path("out/mainos_diag_vdump.bin")
CODE = 0x400d6a00
PROBE = 0x40aa67e0
HOOK = 0x40091d9e             # movel a2@(68),d2 ; mvsw a2@(36),d0
BACK = 0x40091da6
STATE_B0 = 0x40ab79e0
STA_LO, STA_HI = 0x46c90a78, 0x46c92078

ASM = f"""    .cpu 5407
    .text
voicedump:
    move.l  %a2@(68),%d2
    move.l  %d0,-(%sp)
    move.l  %d1,-(%sp)
    move.l  %a0,-(%sp)
    move.l  %a1,-(%sp)
    move.l  %a2@(4),%d1
    lea     0x{PROBE:x},%a1
    move.l  #0x7c1ce000,%d0
    move.l  %d0,%a1@(8)
    cmpi.l  #0x{STATE_B0:x},%d1
    bne.b   2f
    addq.l  #1,%a1@
    lea     %a1@(0x10),%a1
    bra.b   4f
2:  cmpi.l  #0x{STA_LO:x},%d1
    blo.b   9f
    cmpi.l  #0x{STA_HI:x},%d1
    bhs.b   9f
    addq.l  #1,%a1@(4)
    lea     %a1@(0xc0),%a1
4:  move.l  %a2,%a0
    moveq   #41,%d0
6:  move.l  %a0@+,%d1
    move.l  %d1,%a1@+
    subq.l  #1,%d0
    bpl.b   6b
9:  move.l  %sp@+,%a1
    move.l  %sp@+,%a0
    move.l  %sp@+,%d1
    move.l  %sp@+,%d0
    mvs.w   %a2@(36),%d0
    jmp     0x{BACK:x}
"""


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC}")
    img = bytearray(SRC.read_bytes())
    p = "out/_vdp"
    pathlib.Path(p + ".s").write_text(ASM)
    r = subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", p + ".o", p + ".s"], capture_output=True, text=True)
    if r.returncode: sys.exit(r.stderr)
    subprocess.run(["m68k-elf-ld", "-Ttext=0x%x" % CODE, "-o", p + ".elf", p + ".o"], capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", p + ".elf", p + ".bin"], check=True)
    blob = pathlib.Path(p + ".bin").read_bytes()
    for f in (".s", ".o", ".elf", ".bin"):
        pathlib.Path(p + f).unlink(missing_ok=True)
    assert not any(img[bd.off(CODE):bd.off(CODE) + len(blob)]), "cave not empty"
    img[bd.off(CODE):bd.off(CODE) + len(blob)] = blob
    o = bd.off(HOOK)
    assert bytes(img[o:o + 8]) == b"\x24\x2a\x00\x44\x71\x6a\x00\x24", img[o:o + 8].hex()
    img[o:o + 6] = b"\x4e\xf9" + CODE.to_bytes(4, "big")
    img[o + 6:o + 8] = b"\x4e\x71"
    OUT.write_bytes(bytes(img))
    print(f"diag-vdump: {len(blob)} B @0x{CODE:08x}; hook 0x{HOOK:08x} -> full voice-struct dump (128 vs low)")
    print(f"{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
