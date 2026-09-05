#!/usr/bin/env python3
"""build_diag256_stateb.py -- P16 candidate fix (flag-clobber fix already in mainos_persist256.bin) PLUS
a ground-truth probe: capture the STATE-B[0] fields the voice-bind resolver 0x4000f450 actually sees at
BIND time for STATIC slot 129 (idx=128), so we know WHICH gate condition fails when it stays silent.

Detour the two pointer-cache stores at 0x4000f4dc (movel a5,a2@(4); movel a4,a2@(8)) -> jmp probe. The
probe replicates them, and IF a5 == STATE-B[0] (0x40ab79e0, i.e. the voice is binding slot 128) it dumps
STATE-B[0]@8/@16/@20/@36 and STRIDE4#2-B[0] to an unused SET-B slot (0x40aa67e0), which sidecar_save
writes into project.256[0x11200] on the next SAVE.

Voice-bind sounds iff STATE@16>0 AND STATE@8==0 AND STRIDE4[0]==STATE@20 (and @36=handle for streaming).

PROBE @0x40aa67e0 -> project.256[0x11200]:
  [0x00] bind count (times the resolver bound slot 128)
  [0x04] STATE@8  (want 0)      [0x08] STATE@16 (want >0)     [0x0c] STATE@20 (gen)
  [0x10] STATE@36 (handle, want !=0)   [0x14] STRIDE4#2-B[0] (want == @20)   [0x1c] magic 0xB0BB1E00

Read after RELOAD + trigger slot 129 + SAVE:
  python3 -c "d=open('/Volumes/OCTATRACK/.../project.256','rb').read()[0x11200:0x11220]; import struct; \
              print(['%08x'%x for x in struct.unpack('>8I', d)])"

    python3 tools/build_diag256_stateb.py   # -> out/mainos_diag_stateb.bin  (package as DUAL256P16)
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd

SRC = pathlib.Path("out/mainos_persist256.bin")     # P16 base (flag fix + sentinel + clamps already in)
OUT = pathlib.Path("out/mainos_diag_stateb.bin")
CODE = 0x400d6a00                                   # free cave [0x400d6a00, 0x400d7400)
PROBE = 0x40aa67e0                                  # unused SET-B slot 64
HOOK = 0x4000f4dc                                   # movel a5,a2@(4) ; movel a4,a2@(8)  (8 bytes)
BACK = 0x4000f4e4                                   # tstl a5@(16)  (resume here)
STATE_B0 = 0x40ab79e0
S42_B0   = 0x40ab91e0

ASM = f"""    .cpu 5407
    .text
probe_bind:
    move.l  %a5,4(%a2)
    move.l  %a4,8(%a2)
    cmpa.l  #0x{STATE_B0:x},%a5
    bne.b   1f
    move.l  %d0,-(%sp)
    move.l  %a0,-(%sp)
    lea     0x{PROBE:x},%a0
    move.l  #0xb0bb1e00,%d0
    move.l  %d0,0x1c(%a0)
    addq.l  #1,(%a0)
    move.l  8(%a5),%d0
    move.l  %d0,4(%a0)
    move.l  16(%a5),%d0
    move.l  %d0,8(%a0)
    move.l  20(%a5),%d0
    move.l  %d0,12(%a0)
    move.l  36(%a5),%d0
    move.l  %d0,16(%a0)
    move.l  0x{S42_B0:x},%d0
    move.l  %d0,20(%a0)
    move.l  (%sp)+,%a0
    move.l  (%sp)+,%d0
1:  jmp     0x{BACK:x}
"""


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC} -- run tools/build_persist256.py first")
    img = bytearray(SRC.read_bytes())

    p = "out/_diag_sb"
    pathlib.Path(p + ".s").write_text(ASM)
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", p + ".o", p + ".s"], check=True)
    subprocess.run(["m68k-elf-ld", "-Ttext=0x%x" % CODE, "-o", p + ".elf", p + ".o"], capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", p + ".elf", p + ".bin"], check=True)
    blob = pathlib.Path(p + ".bin").read_bytes()
    for f in (".s", ".o", ".elf", ".bin"):
        pathlib.Path(p + f).unlink(missing_ok=True)

    assert not any(img[bd.off(CODE):bd.off(CODE) + len(blob)]), "diag cave not empty"
    assert len(blob) <= 0x100, f"probe too big: {len(blob)}"
    img[bd.off(CODE):bd.off(CODE) + len(blob)] = blob

    o = bd.off(HOOK)
    assert bytes(img[o:o + 8]) == b"\x25\x4d\x00\x04\x25\x4c\x00\x08", img[o:o + 8].hex()
    img[o:o + 6] = b"\x4e\xf9" + CODE.to_bytes(4, "big")   # jmp probe_bind
    img[o + 6:o + 8] = b"\x4e\x71"                          # nop

    OUT.write_bytes(bytes(img))
    print(f"diag-stateb: {len(blob)} B @0x{CODE:08x}; hook 0x{HOOK:08x} -> capture STATE-B[0] at bind of "
          f"slot 128 -> PROBE 0x{PROBE:08x} -> project.256[0x11200]")
    print(f"{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
