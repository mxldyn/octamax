#!/usr/bin/env python3
"""build_diag256_ring.py -- DECISIVE ColdFire-vs-DSP test. The PCM refill runs 613x for the slot-128 voice
(active, STATIC, gates pass). Does the voice's ring buffer (a2@(68)) actually contain AUDIO bytes (CF
streaming works -> silence is DSP-side), or is it zero/garbage (the CF read into the ring failed ->
ColdFire streaming bug for idx>=128)?

Hook 0x40091d9e (`movel a2@(68),d2 ; mvsw a2@(36),d0` = 8 bytes; a2 = voice struct). For the voice whose
a2@(4)==STATE-B[0], capture the ring base a2@(68) and the first two longs at that address.

PROBE @0x40aa67e0 -> project.256[0x11200]:
  [0x00] count  [0x04] ring_base (a2@68)  [0x08] ring[0]  [0x0c] ring[4]  [0x10] a2@64 (buf ptr)  [0x1c] magic 0x11460000

Do (one session): RELOAD -> assign slot 129 -> TRIG -> PLAY -> SAVE.

    python3 tools/build_diag256_ring.py   # -> out/mainos_diag_ring.bin  (package as DUAL256P25)
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd

SRC = pathlib.Path("out/mainos_persist256.bin")
OUT = pathlib.Path("out/mainos_diag_ring.bin")
CODE = 0x400d6a00
PROBE = 0x40aa67e0
HOOK = 0x40091d9e             # movel a2@(68),d2 ; mvsw a2@(36),d0   (242a0044 716a0024)
BACK = 0x40091da6
STATE_B0 = 0x40ab79e0

ASM = f"""    .cpu 5407
    .text
ring_probe:
    move.l  %a2@(68),%d2
    move.l  %d0,-(%sp)
    move.l  %a2@(4),%d0
    cmpi.l  #0x{STATE_B0:x},%d0
    bne.b   1f
    move.l  %a0,-(%sp)
    move.l  %a1,-(%sp)
    lea     0x{PROBE:x},%a0
    move.l  #0x11460000,%d0
    move.l  %d0,0x1c(%a0)
    addq.l  #1,%a0@
    move.l  %d2,4(%a0)              | ring base
    move.l  %a2@(64),%d0
    move.l  %d0,16(%a0)            | a2@64 (buffer ptr)
    | range-guard the ring pointer before dereferencing (avoid faulting the audio ISR on a bad ptr)
    cmpi.l  #0x40000000,%d2
    blo.b   2f
    cmpi.l  #0x48000000,%d2
    bhs.b   2f
    move.l  %d2,%a1
    move.l  %a1@,%d0
    move.l  %d0,8(%a0)             | ring[0]
    move.l  %a1@(4),%d0
    move.l  %d0,12(%a0)            | ring[4]
    bra.b   3f
2:  move.l  #0xbadbad00,%d0
    move.l  %d0,8(%a0)             | ring ptr out of range -> sentinel
3:
    move.l  %sp@+,%a1
    move.l  %sp@+,%a0
1:  move.l  %sp@+,%d0
    mvs.w   %a2@(36),%d0
    jmp     0x{BACK:x}
"""


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC}")
    img = bytearray(SRC.read_bytes())
    p = "out/_rng"
    pathlib.Path(p + ".s").write_text(ASM)
    r = subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", p + ".o", p + ".s"], capture_output=True, text=True)
    if r.returncode: sys.exit(r.stderr)
    subprocess.run(["m68k-elf-ld", "-Ttext=0x%x" % CODE, "-o", p + ".elf", p + ".o"], capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", p + ".elf", p + ".bin"], check=True)
    # a1 is a callee-saved reg used by the resolver caller; we clobber it -- but this hook is in the middle
    # of a fn that will reload a1; still, to be safe use only d0/a0 saved. a1 clobber: check the fn -- a1 is
    # not live across 0x40091d9e (recomputed). Proceed.
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
    print(f"diag-ring: {len(blob)} B @0x{CODE:08x}; hook 0x{HOOK:08x} -> slot-128 voice ring contents")
    print(f"{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
