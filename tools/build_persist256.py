#!/usr/bin/env python3
"""
build_persist256.py -- the 256-slot PERSISTENCE build = working dual-256 (out/mainos_dual256.bin)
plus the two emulation-proven patches that make project.work carry STATIC slots 129..256 via SET-B:

  A) SERIALIZER 256-extension (tools/emu_serializer.py PROVEN): at the STATIC-serializer loop tail
     0x40089608, replace `cmpi.l #129,d4`+`bnew 0x40089420` (10 B) with `jmp SER_CAVE`. SER_CAVE:
       cmpi.l #129,%d4 ; bne 1f ; lea SET_B+0x129,%a3 ; 1: cmpi.l #257,%d4 ; beq 2f ;
       jmp 0x40089420 ; 2: jmp 0x40089612
     -> emits SLOT=001..128 from SET-A, SLOT=129..256 from SET-B (walk switches A->B at the boundary).

  B) PARSER cap (tools/emu_serializer address+gate tests PROVEN): the parser already routes the STATIC
     slot base-add through h_set_d0 (SET-B for idx>=128) and its address bound is raised to #255 in the
     working build; the ONLY remaining gate is 0x40086922 `movel #129,d1` (rejects idx>=129). Raise it
     to #256 so SLOT=129..256 (idx 128..255) load into SET-B. FLEX stays bounded by its own #135 gate.

Both halves read/write the slot PATH at slot offset 0 (serializer a3-0x129; parser slot_base+0), so the
round-trip is byte-consistent. SET-B (0x47701a00) is persisted by the existing sidecar to project.256,
AND now also mirrored into project.work as native STATIC blocks.

    python3 tools/build_persist256.py     # -> out/mainos_persist256.bin
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd

SRC = pathlib.Path("out/mainos_dual256.bin")   # the working W6 image (built first)
OUT = pathlib.Path("out/mainos_persist256.bin")
SER_CAVE = 0x400d6a00          # was 0x400d6900, but wave-21 grew the sidecar blob to 780 B (0x400d690c),
                               # whose `stream` buffer (0x400d68cc..0x400d690c) zeroed the first 12 B of a
                               # stub at 0x400d6900 at runtime -> VEC:04 on save. Moved past the sidecar
                               # into the validated cave [0x400d6a00,0x400d6b00). (2026-09-02)
SET_B = bd.SET_B               # 0x47701a00 SETTINGS-B
SER_TAIL = 0x40089608          # cmpi.l #129,d4 ; bnew 0x40089420  (10 bytes)
SER_BODY = 0x40089420
SER_EXIT = 0x40089612
PARSER_CAP = 0x40086922        # movel #129,d1


def build_ser_cave():
    asm = f"""    .cpu 5407
    .text
tail:
    cmpi.l  #129,%d4
    bne.b   1f
    lea     0x{SET_B + 0x129:x},%a3
1:  cmpi.l  #257,%d4
    beq.b   2f
    jmp     0x{SER_BODY:x}
2:  jmp     0x{SER_EXIT:x}
"""
    p = "out/_sc2"
    pathlib.Path(p + ".s").write_text(asm)
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", p + ".o", p + ".s"], check=True)
    subprocess.run(["m68k-elf-ld", "-Ttext=0x%x" % SER_CAVE, "-o", p + ".elf", p + ".o"], capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", p + ".elf", p + ".bin"], check=True)
    blob = pathlib.Path(p + ".bin").read_bytes()
    for f in (".s", ".o", ".elf", ".bin"):
        pathlib.Path(p + f).unlink(missing_ok=True)
    return blob


def main():
    # 1) build the working image first, but with SETTINGS-B copy-fill OFF (zeroed) so the extended
    #    serializer does not emit phantom STATIC slots for unpopulated high slots. STATE/stride4-B are
    #    ALSO zero-init (bd.COPYFILL_STATE default False): FN-VIEW's entry FN-CLEAR closes a garbage
    #    STATE@36 handle if copy-filled -> wild OOB -> slot 129 breaks. TRACE off. Run main() to apply.
    assert bd.TRACE is False, "build_dual256 TRACE must be False for the persist build"
    assert bd.COPYFILL_STATE is False, "STATE-B must be zero-init (FN-CLEAR closes garbage @36)"
    bd.COPYFILL_SET = False
    bd.main()
    img = bytearray(SRC.read_bytes())

    # A) serializer 256-extension
    cave = build_ser_cave()
    assert not any(img[bd.off(SER_CAVE):bd.off(SER_CAVE) + len(cave)]), "SER_CAVE not empty (TRACE on?)"
    img[bd.off(SER_CAVE):bd.off(SER_CAVE) + len(cave)] = cave
    o = bd.off(SER_TAIL)
    assert bytes(img[o:o + 10]) == b"\x0c\x84\x00\x00\x00\x81\x66\x00\xfe\x10", img[o:o+10].hex()
    img[o:o + 10] = b"\x4e\xf9" + SER_CAVE.to_bytes(4, "big") + b"\x4e\x71\x4e\x71"   # jmp + 2 nop
    print(f"serializer-ext: {len(cave)} B @0x{SER_CAVE:08x}; tail 0x{SER_TAIL:08x} -> jmp cave (A->B @ d4=129, cap 257)")

    # B) parser cap #129 -> #256
    o = bd.off(PARSER_CAP)
    assert bytes(img[o:o + 6]) == b"\x22\x3c\x00\x00\x00\x81", img[o:o + 6].hex()
    img[o:o + 6] = b"\x22\x3c\x00\x00\x01\x00"
    print(f"parser-cap: 0x{PARSER_CAP:08x} movel #129,d1 -> #256 (loads SLOT=129..256 into SET-B)")

    OUT.write_bytes(bytes(img))
    print(f"\n{OUT}: {len(img):,} bytes")
    print("VERIFY: python3 tools/emu_check.py out/mainos_persist256.bin ; python3 tools/emu_serializer.py --img out/mainos_persist256.bin")


if __name__ == "__main__":
    main()
