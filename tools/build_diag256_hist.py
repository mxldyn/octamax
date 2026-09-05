#!/usr/bin/env python3
"""build_diag256_hist.py -- GROUND-TRUTH histogram: the STATE-B[0] probe (P17) NEVER fired, meaning the
voice-bind resolver 0x4000f450 never ran with a5==STATE-B[0] -> slot 128 is never bound as STATIC. To
localize WHERE the slot is lost, this probe records, for EVERY resolver call, the (idx, machine-type)
it processes -- so we see exactly which slots the track actually plays when you trigger UI slot 129.

Hook 0x4000f484 (`adda.l #0x800049d8,a2`, before the STATIC/FLEX branch, reached for ALL types). The
probe reads idx=arg1 (sp@68) and type (sp@56), and for idx<256 writes array[idx]=type|0x80, bumps a
call counter, sets a magic. Region = unused SET-B slot 64 (0x40aa67e0) -> project.256[0x11200] on SAVE.

Layout @0x40aa67e0 -> project.256[0x11200]:
  [0x000..0x0ff] : per-idx byte = (machine_type | 0x80)  (0x00 = resolver never processed that idx)
  [0x100] long   : total resolver call count
  [0x108] long   : magic 0xC0DE1200

Read after trigger + SAVE:
  python3 -c "import struct,pathlib; d=pathlib.Path('.../project.256').read_bytes()[0x11200:0x11310]; \
    a=d[:256]; print('count',struct.unpack('>I',d[0x100:0x104])[0],'magic',hex(struct.unpack('>I',d[0x108:0x10c])[0])); \
    print([(i,hex(a[i])) for i in range(256) if a[i]])"

    python3 tools/build_diag256_hist.py   # -> out/mainos_diag_hist.bin  (package as DUAL256P18)
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd

SRC = pathlib.Path("out/mainos_persist256.bin")
OUT = pathlib.Path("out/mainos_diag_hist.bin")
CODE = 0x400d6a00
PROBE = 0x40aa67e0
HOOK = 0x4000f484              # adda.l #0x800049d8,a2   (6 bytes: d5fc 800049d8)
BACK = 0x4000f48a              # moveal a2@(12),a0

ASM = f"""    .cpu 5407
    .text
hist_probe:
    move.l  %d0,-(%sp)
    move.l  %d1,-(%sp)
    move.l  %a0,-(%sp)
    move.l  %sp@(80),%d0            | idx = arg1 (sp@68 + 12 pushed)
    cmpi.l  #256,%d0
    bcc.b   1f
    move.l  %sp@(68),%d1            | machine type (sp@56 + 12)
    lea     0x{PROBE:x},%a0
    ori.l   #0x80,%d1
    move.b  %d1,%a0@(0,%d0:l)       | array[idx] = type|0x80
    addq.l  #1,%a0@(0x100)          | call count
    move.l  #0xc0de1200,%d1
    move.l  %d1,%a0@(0x108)         | magic
1:  move.l  %sp@+,%a0
    move.l  %sp@+,%d1
    move.l  %sp@+,%d0
    adda.l  #0x800049d8,%a2         | replicate displaced instruction
    jmp     0x{BACK:x}
"""


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC}")
    img = bytearray(SRC.read_bytes())
    p = "out/_hist"
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
    assert bytes(img[o:o + 6]) == b"\xd5\xfc\x80\x00\x49\xd8", img[o:o + 6].hex()
    img[o:o + 6] = b"\x4e\xf9" + CODE.to_bytes(4, "big")
    OUT.write_bytes(bytes(img))
    print(f"diag-hist: {len(blob)} B @0x{CODE:08x}; hook 0x{HOOK:08x} -> per-idx type histogram @0x{PROBE:08x}")
    print(f"{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
