#!/usr/bin/env python3
"""build_diag256c.py -- decisive bisection: is the P11 hang in the bulk-loader's SLOT-128 BODY, or in
the loop mechanics / downstream? Overwrite the installed loadloop stub (0x400d7700) with a SKIP-128
variant: when d3 reaches 128, jump d3->129 and a2->SET_B[1], so slot 128's body (CALL1-4 + FN-VIEW +
log + callback) NEVER runs. Slots 129..255 are empty -> skipped. The loop still runs to 256 and exits.

  RESULT:
    * BOOTS now  -> the hang IS in slot 128's BODY processing (one of the pre-FN-VIEW calls 0x400204a8/
                    0x400204cc/a4@, or the post-FN-VIEW log/callback). Next: bisect the body.
    * STILL hangs -> the hang is in the LOOP MECHANICS (my stub) or DOWNSTREAM (0x40096a5c/FLEX/post-load),
                    NOT slot 128's body. Redirect there.

    python3 tools/build_diag256c.py   # -> out/mainos_diag256c.bin  (package as DUAL256PF)
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd

SRC = pathlib.Path("out/mainos_persist256.bin")     # P11 base (loadloop already installed @0x400d7700)
OUT = pathlib.Path("out/mainos_diag256c.bin")
STUB = bd.LOADLOOP_STUB                              # 0x400d7700
SET_B = bd.SET_B                                     # 0x40a955e0
BODY = bd.LOADLOOP_BODY                              # 0x4009087a
EXIT = bd.LOADLOOP_EXIT                              # 0x40090902

ASM = f"""    .cpu 5407
    .text
loadloop_skip128:
    cmpi.l  #128,%d3
    bne.b   1f
    addq.l  #1,%d3                     | skip slot 128: d3 -> 129
    movea.l #0x{SET_B + 0x448:x},%a2   | a2 -> SET_B[1] (slot 130)
    bra.b   2f
1:  lea     %a2@(0x448),%a2
2:  cmpi.l  #256,%d3
    beq.b   3f
    jmp     0x{BODY:x}
3:  jmp     0x{EXIT:x}
"""


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC} -- run tools/build_persist256.py first")
    img = bytearray(SRC.read_bytes())

    p = "out/_diagc"
    pathlib.Path(p + ".s").write_text(ASM)
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", p + ".o", p + ".s"], check=True)
    subprocess.run(["m68k-elf-ld", "-Ttext=0x%x" % STUB, "-o", p + ".elf", p + ".o"], capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", p + ".elf", p + ".bin"], check=True)
    blob = pathlib.Path(p + ".bin").read_bytes()
    for f in (".s", ".o", ".elf", ".bin"):
        pathlib.Path(p + f).unlink(missing_ok=True)

    # sanity: the original loadloop stub starts with `cmpi.l #128,d3` (0c83 0000 0080)
    o = bd.off(STUB)
    assert bytes(img[o:o + 6]) == b"\x0c\x83\x00\x00\x00\x80", img[o:o + 6].hex()
    assert len(blob) <= 0x60, f"skip stub too big: {len(blob)}"
    # clear the old stub region then write the new one (same cave)
    for i in range(0x40):
        img[o + i] = 0
    img[o:o + len(blob)] = blob

    OUT.write_bytes(bytes(img))
    print(f"diag3: skip-128 stub {len(blob)} B @0x{STUB:08x}; slot 128 body BYPASSED in the loadloop")
    print(f"{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
