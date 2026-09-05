#!/usr/bin/env python3
"""build_diag256_alloc.py -- the resolver BINDS idx=128 (control side fully works) but no sound -> the
silence is in the STREAMING/DSP path. First link: the stream-voice allocator FUN_40094334 (opens the CF
stream + fills the ring for a slot). This probe records which slots the allocator actually processes, so
we see whether it runs for slot 128 (stream opens) or never (the streaming request is never enqueued for
the high slot).

Hook 0x40094350 (`cmpi.l #128,d0`, d0 = slot arg). Marks a per-slot histogram + count, then replicates
the cmpi (to preserve flags for the following bhiw) and returns.

PROBE @0x40aa67e0 -> project.256[0x11200]:
  [0x000 + idx] = 0xff if the allocator processed idx  (0 = never)
  [0x100] alloc call count   [0x108] magic 0xA110C000

Do (one session): RELOAD -> assign slot 129 -> TRIG -> PLAY -> SAVE.

    python3 tools/build_diag256_alloc.py   # -> out/mainos_diag_alloc.bin  (package as DUAL256P23)
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd

SRC = pathlib.Path("out/mainos_persist256.bin")
OUT = pathlib.Path("out/mainos_diag_alloc.bin")
CODE = 0x400d6a00
PROBE = 0x40aa67e0
HOOK = 0x40094350             # cmpi.l #128,d0   (0c80 00000080)
BACK = 0x40094356             # bhiw 0x400946cc

ASM = f"""    .cpu 5407
    .text
alloc_probe:
    move.l  %d1,-(%sp)
    move.l  %a0,-(%sp)
    cmpi.l  #256,%d0
    bcc.b   1f
    lea     0x{PROBE:x},%a0
    move.l  #0xa110c000,%d1
    move.l  %d1,%a0@(0x108)
    addq.l  #1,%a0@(0x100)
    adda.l  %d0,%a0
    moveq   #-1,%d1
    move.b  %d1,%a0@                | array[slot] = 0xff
1:  move.l  %sp@+,%a0
    move.l  %sp@+,%d1
    cmpi.l  #255,%d0            | replicate migrated clamp
    jmp     0x{BACK:x}
"""


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC}")
    img = bytearray(SRC.read_bytes())
    p = "out/_alc"
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
    assert bytes(img[o:o + 6]) == b"\x0c\x80\x00\x00\x00\xff", img[o:o + 6].hex()
    img[o:o + 6] = b"\x4e\xf9" + CODE.to_bytes(4, "big")
    OUT.write_bytes(bytes(img))
    print(f"diag-alloc: {len(blob)} B @0x{CODE:08x}; hook 0x{HOOK:08x} -> stream-allocator slot histogram")
    print(f"{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
