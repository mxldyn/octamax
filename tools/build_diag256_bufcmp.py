#!/usr/bin/env python3
"""build_diag256_bufcmp.py -- CLEAN comparative measurement. The resolver sets voice@64/@68/@72 = a0 (the
sample source base/position) at 0x4000f820. For idx=128 we saw a0=0xc6c49 (small) -- but that may be a
valid file position, not garbage. To know, capture a0 for the idx=128 voice AND for a WORKING low-slot
STATIC voice in the same session and compare their structure/magnitude.

Hook 0x4000f820 (`movel a0,a2@(64) ; movel a0,a2@(68)` = 8 bytes). a2 = voice; a2@(4) = its STATE ptr.
  STATE ptr == 0x40ab79e0            -> idx=128 voice
  STATE ptr in [0x46c90a78,0x46c92078) -> a working low STATIC slot

PROBE @0x40aa67e0 -> project.256[0x11200]:
  [0x00] hi_count  [0x04] hi a0 (voice@64 for idx=128)  [0x08] hi STATE@16
  [0x10] lo_count  [0x14] lo a0 (voice@64 for a low slot)  [0x18] lo STATE ptr  [0x1c] lo STATE@16
  [0x20] magic 0xB0FC0000

Do (one session): RELOAD -> assign slot 129 to a track -> put trigs on THAT track AND a working low-slot
track -> PLAY both -> SAVE.

    python3 tools/build_diag256_bufcmp.py   # -> out/mainos_diag_bufcmp.bin  (package as DUAL256P26)
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd

SRC = pathlib.Path("out/mainos_persist256.bin")
OUT = pathlib.Path("out/mainos_diag_bufcmp.bin")
CODE = 0x400d6a00
PROBE = 0x40aa67e0
HOOK = 0x4000f820             # movel a0,a2@(64) ; movel a0,a2@(68)   (25480040 25480044)
BACK = 0x4000f828
STATE_B0 = 0x40ab79e0
STA_LO, STA_HI = 0x46c90a78, 0x46c92078

ASM = f"""    .cpu 5407
    .text
bufcmp_probe:
    move.l  %d0,-(%sp)
    move.l  %d1,-(%sp)
    move.l  %a1,-(%sp)
    move.l  %a2@(4),%d1            | STATE ptr of this voice
    lea     0x{PROBE:x},%a1
    move.l  #0xb0fc0000,%d0
    move.l  %d0,0x20(%a1)
    cmpi.l  #0x{STATE_B0:x},%d1
    bne.b   2f
    | idx=128 voice
    addq.l  #1,%a1@
    move.l  %a0,%a1@(4)
    move.l  %d1,%a1@(8)            | (reuse: store STATE ptr, then @16 below via a2)
    bra.b   3f
2:  cmpi.l  #0x{STA_LO:x},%d1
    blo.b   3f
    cmpi.l  #0x{STA_HI:x},%d1
    bhs.b   3f
    | a working low STATIC slot
    addq.l  #1,%a1@(0x10)
    move.l  %a0,%a1@(0x14)
    move.l  %d1,%a1@(0x18)
3:  move.l  %sp@+,%a1
    move.l  %sp@+,%d1
    move.l  %sp@+,%d0
    move.l  %a0,%a2@(64)
    move.l  %a0,%a2@(68)
    jmp     0x{BACK:x}
"""


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC}")
    img = bytearray(SRC.read_bytes())
    p = "out/_bfc"
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
    assert bytes(img[o:o + 8]) == b"\x25\x48\x00\x40\x25\x48\x00\x44", img[o:o + 8].hex()
    img[o:o + 6] = b"\x4e\xf9" + CODE.to_bytes(4, "big")
    img[o + 6:o + 8] = b"\x4e\x71"
    OUT.write_bytes(bytes(img))
    print(f"diag-bufcmp: {len(blob)} B @0x{CODE:08x}; hook 0x{HOOK:08x} -> voice@64 idx128 vs low slot")
    print(f"{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
