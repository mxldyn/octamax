#!/usr/bin/env python3
"""build_diag256_assignwrite.py -- the emulator proved ui_apply WRITES the selected slot (128) to the
track's per-part byte at 0x400795c0, and the P19 probe proved STATE-B[0]@8==0 (the gate passes). Yet the
histogram shows the track still plays its OLD slot -> on HARDWARE the assign did not persist 128. This
probe hooks the actual write 0x400795c0 (`moveb d1,a0@` = store selected slot to per-part) to capture
whether it FIRES for slot 129 and with what value/address -- testing the REAL YES-flow (not isolated emu).

  count==0 after assigning slot 129  -> ui_apply's write is NEVER reached (YES-handler rejects earlier).
  count>0, slot==128                 -> the write DOES happen; something downstream reverts it or the
                                        frame builder reads a different byte.

Hook replaces 8 bytes at 0x400795c0 (`moveb d1,a0@` + `addal #0x100a5198,a1`) with jmp probe + nop.

PROBE @0x40aa67e0 -> project.256[0x11200]:
  [0x00] count  [0x04] slot value written (d1)  [0x08] dest address (a0)  [0x1c] magic 0x5747E100

Do: RELOAD -> double-click track -> slot selector -> dial to slot 129 -> YES -> NO -> SAVE.

    python3 tools/build_diag256_assignwrite.py   # -> out/mainos_diag_awrite.bin  (package as DUAL256P20)
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd

SRC = pathlib.Path("out/mainos_persist256.bin")
OUT = pathlib.Path("out/mainos_diag_awrite.bin")
CODE = 0x400d6a00
PROBE = 0x40aa67e0
HOOK = 0x400795c0              # moveb d1,a0@ ; addal #0x100a5198,a1   (1081 d3fc 100a5198 = 8 bytes)
BACK = 0x400795c8

ASM = f"""    .cpu 5407
    .text
awrite_probe:
    move.l  %d0,-(%sp)
    move.l  %a2,-(%sp)
    lea     0x{PROBE:x},%a2
    move.l  #0x5747e100,%d0
    move.l  %d0,0x1c(%a2)
    addq.l  #1,%a2@
    move.l  %d1,4(%a2)
    move.l  %a0,%d0
    move.l  %d0,8(%a2)
    move.l  %sp@+,%a2
    move.l  %sp@+,%d0
    move.b  %d1,%a0@
    adda.l  #0x100a5198,%a1
    jmp     0x{BACK:x}
"""


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC}")
    img = bytearray(SRC.read_bytes())
    p = "out/_awr"
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
    assert bytes(img[o:o + 8]) == b"\x10\x81\xd3\xfc\x10\x0a\x51\x98", img[o:o + 8].hex()
    img[o:o + 6] = b"\x4e\xf9" + CODE.to_bytes(4, "big")
    img[o + 6:o + 8] = b"\x4e\x71"
    OUT.write_bytes(bytes(img))
    print(f"diag-awrite: {len(blob)} B @0x{CODE:08x}; hook 0x{HOOK:08x} -> capture assign slot-write -> 0x{PROBE:08x}")
    print(f"{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
