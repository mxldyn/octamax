#!/usr/bin/env python3
"""build_diag256_assignstate.py -- the assign of UI slot 129 (idx 128) to a track is REJECTED by the
gate at 0x40079502: ui_apply reads STATE[selected_slot]@8 and if != 0 branches away (0x40079506 bnew
0x40079684) WITHOUT writing the slot to the track. idx 127 works (its STATE@8==0 = loaded); idx 128 is
rejected -> STATE-B[0]@8 != 0. This probe captures the ACTUAL STATE-B[0] fields at that gate, to reveal
whether FN-VIEW(128) actually loaded the slot on RELOAD (handle@36 set, @8 cleared to 0) or not.

Hook 0x40079500 (`moveal d0,a0 ; movel a0@(8),d0` = 6 bytes; a0 = STATE[selected_slot]). If a0 ==
STATE-B[0] (0x40ab79e0, i.e. selecting slot 129) capture @8/@16/@20/@36 -> unused SET-B slot 64.

PROBE @0x40aa67e0 -> project.256[0x11200]:
  [0x00] count  [0x04] STATE@8  [0x08] STATE@16  [0x0c] STATE@20  [0x10] STATE@36(handle)  [0x1c] magic 0x57A7E800

Do: RELOAD -> double-click track -> open slot selector -> dial to slot 129 -> YES (fires probe) -> NO -> SAVE.

    python3 tools/build_diag256_assignstate.py   # -> out/mainos_diag_astate.bin  (package as DUAL256P19)
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd

SRC = pathlib.Path("out/mainos_persist256.bin")
OUT = pathlib.Path("out/mainos_diag_astate.bin")
CODE = 0x400d6a00
PROBE = 0x40aa67e0
HOOK = 0x40079500              # moveal d0,a0 ; movel a0@(8),d0   (2040 2028 0008)
BACK = 0x40079506              # bnew 0x40079684
STATE_B0 = 0x40ab79e0

ASM = f"""    .cpu 5407
    .text
astate_probe:
    movea.l %d0,%a0
    cmpa.l  #0x{STATE_B0:x},%a0
    bne.b   1f
    move.l  %d1,-(%sp)
    move.l  %a1,-(%sp)
    lea     0x{PROBE:x},%a1
    move.l  #0x57a7e800,%d1
    move.l  %d1,0x1c(%a1)
    addq.l  #1,%a1@
    move.l  %a0@(8),%d1
    move.l  %d1,4(%a1)
    move.l  %a0@(16),%d1
    move.l  %d1,8(%a1)
    move.l  %a0@(20),%d1
    move.l  %d1,12(%a1)
    move.l  %a0@(36),%d1
    move.l  %d1,16(%a1)
    move.l  %sp@+,%a1
    move.l  %sp@+,%d1
1:  move.l  %a0@(8),%d0
    jmp     0x{BACK:x}
"""


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC}")
    img = bytearray(SRC.read_bytes())
    p = "out/_ast"
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
    assert bytes(img[o:o + 6]) == b"\x20\x40\x20\x28\x00\x08", img[o:o + 6].hex()
    img[o:o + 6] = b"\x4e\xf9" + CODE.to_bytes(4, "big")
    OUT.write_bytes(bytes(img))
    print(f"diag-astate: {len(blob)} B @0x{CODE:08x}; hook 0x{HOOK:08x} -> STATE-B[0] at assign gate -> 0x{PROBE:08x}")
    print(f"{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
