#!/usr/bin/env python3
"""build_diag256.py -- localize the P11 project-load HANG for STATIC slot 129 (idx 128). P11 boots the
bulk-loader which calls FN-VIEW(128); FN-VIEW's tail now reaches the streaming/DSP + sample-map calls
and HANGS. This build makes FN-VIEW, FOR idx==128 ONLY, SKIP the two DSP/IO calls (return success):
    - 0x400180c8 (streaming/DSP precompute)  @ call 0x40093d26  -> diag_180c8 (idx128 -> return 0)
    - *0x46c82426 (map sample data to 0x4FFC9010) @ call 0x40093d94 -> diag_map sets a0 to ret0_stub
The waveform bit-depth loader (0x40093db8..df2, memory-only) still runs. Stack-neutral (jmp-through for
idx!=128; balanced for idx==128).

  RESULT INTERPRETATION:
    * BOOTS now  -> the hang was in streaming (0x400180c8) or sample-map (0x46c82426) = the DSP/IO path.
                    Slot 129 loads STATE+header (name/settings) but no real audio stream. Marker written.
    * STILL hangs -> the hang is BEFORE these (open/header/T24/sampleslice/FN-CLEAR) or in the waveform
                    loader = CPU-side, more likely fixable.
  Marker @0x40aa67e0 -> project.256[0x11200]: [0]=FN-VIEW(128) streaming-reached count, [4]=STATE-B[0]@8,
  [0x1c]=magic 0xD1A60000. Read after boot+SAVE.

    python3 tools/build_diag256.py   # -> out/mainos_diag256.bin  (package as DUAL256PD)
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd

SRC = pathlib.Path("out/mainos_persist256.bin")     # P11 base
OUT = pathlib.Path("out/mainos_diag256.bin")
CODE = 0x400d6a00                                    # free cave [0x400d6a00,0x400d7400)
PROBE = 0x40aa67e0                                   # SET-B slot 64 -> project.256[0x11200]
STATE_B0 = 0x40ab79e0
STREAM_CALL = 0x40093d26                             # jsr 0x400180c8
MAP_LOAD = 0x40093d8e                                # moveal 0x46c82426,a0 ; (jsr a0@ @0x40093d94)

ASM = f"""    .cpu 5407
    .text
diag_180c8:
    move.l  %sp@(8),%d0            | arg2 = idx
    cmpi.l  #128,%d0
    bne.b   9f
    move.l  %d1,-(%sp)
    move.l  %a0,-(%sp)
    move.l  %a1,-(%sp)
    lea     0x{PROBE:x},%a0
    move.l  #0xd1a60000,%d1
    move.l  %d1,0x1c(%a0)
    addq.l  #1,(%a0)
    movea.l #0x{STATE_B0:x},%a1
    move.l  %a1@(8),%d1
    move.l  %d1,4(%a0)
    move.l  (%sp)+,%a1
    move.l  (%sp)+,%a0
    move.l  (%sp)+,%d1
    moveq   #0,%d0                 | skip streaming -> success
    rts
9:  jmp     0x400180c8            | idx!=128: transparent tail-jump (args already on stack)

diag_map:
    cmpi.l  #128,%d7             | d7 = idx (live in FN-VIEW)
    bne.b   9f
    lea     ret0_stub,%a0
    rts
9:  movea.l 0x46c82426,%a0
    rts
ret0_stub:
    moveq   #0,%d0
    rts
"""


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC} -- run tools/build_persist256.py first")
    img = bytearray(SRC.read_bytes())

    p = "out/_diag"
    pathlib.Path(p + ".s").write_text(ASM)
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", p + ".o", p + ".s"], check=True)
    subprocess.run(["m68k-elf-ld", "-Ttext=0x%x" % CODE, "-o", p + ".elf", p + ".o"], capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", p + ".elf", p + ".bin"], check=True)
    nm = subprocess.run(["m68k-elf-nm", p + ".elf"], capture_output=True, text=True).stdout
    sym = {q[2]: int(q[0], 16) for q in (l.split() for l in nm.splitlines()) if len(q) == 3}
    blob = pathlib.Path(p + ".bin").read_bytes()
    for f in (".s", ".o", ".elf", ".bin"):
        pathlib.Path(p + f).unlink(missing_ok=True)

    assert not any(img[bd.off(CODE):bd.off(CODE) + len(blob)]), "diag cave not empty"
    assert CODE + len(blob) <= 0x400d7400, "diag overruns cave"
    img[bd.off(CODE):bd.off(CODE) + len(blob)] = blob

    o = bd.off(STREAM_CALL)
    assert bytes(img[o:o + 6]) == b"\x4e\xb9\x40\x01\x80\xc8", img[o:o + 6].hex()
    img[o:o + 6] = b"\x4e\xb9" + sym["diag_180c8"].to_bytes(4, "big")
    o = bd.off(MAP_LOAD)
    assert bytes(img[o:o + 6]) == b"\x20\x79\x46\xc8\x24\x26", img[o:o + 6].hex()
    img[o:o + 6] = b"\x4e\xb9" + sym["diag_map"].to_bytes(4, "big")

    OUT.write_bytes(bytes(img))
    print(f"diag: {len(blob)} B @0x{CODE:08x}; skip streaming 0x{STREAM_CALL:08x} + map 0x{MAP_LOAD:08x} "
          f"for idx=128; marker @0x{PROBE:08x} -> project.256[0x11200]")
    print(f"{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
