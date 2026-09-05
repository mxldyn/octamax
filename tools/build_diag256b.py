#!/usr/bin/env python3
"""build_diag256b.py -- decisive test: is the P11 project-load HANG inside FN-VIEW(128)'s BODY? PD showed
skipping the streaming/map (DSP) calls did NOT stop the hang, so it is earlier. This build makes
FN-VIEW, FOR idx==128 ONLY, RETURN SUCCESS (1) IMMEDIATELY at entry -- skipping the ENTIRE body
(FN-CLEAR, file open, header parse, samplehdr, sampleslice, 0x40016fe8, streaming, waveform).

Detour the raised clamp `cmpi.l #255,d7` @0x4009398c -> jsr diag_entry:
  - d7==128: write marker, pop our return addr, jmp 0x40093e56 (moveb #1,d2 -> return 1). fp-frame intact.
  - else   : replicate `cmpi.l #255,d7` (sets CC for the following `bhiw 0x40093e5c`), rts.

  RESULT:
    * BOOTS now  -> the hang IS inside FN-VIEW(128)'s body. Next: bisect the body (return after each
                   stage). Also gives a STABLE FALLBACK (high slots skip the audio open, keep name/settings).
    * STILL hangs -> the hang is NOT in FN-VIEW's body: it is in the bulk-loader loop itself or in a
                   post-load pass over the slots. Redirect the hunt there.
  Marker @0x40aa67e0 -> project.256[0x11200]: [0]=count, [0x1c]=magic 0xE27A0000. Read after boot+SAVE.

    python3 tools/build_diag256b.py   # -> out/mainos_diag256b.bin  (package as DUAL256PE)
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd

SRC = pathlib.Path("out/mainos_persist256.bin")     # P11 base
OUT = pathlib.Path("out/mainos_diag256b.bin")
CODE = 0x400d6a00
PROBE = 0x40aa67e0
CLAMP = 0x4009398c                                  # cmpi.l #255,d7
RET1 = 0x40093e56                                   # moveb #1,d2 ; bras 0x40093e5e (-> return 1)

ASM = f"""    .cpu 5407
    .text
diag_entry:
    cmpi.l  #128,%d7
    bne.b   9f
    | idx==128: marker + immediate success return
    move.l  %d0,-(%sp)
    move.l  %a0,-(%sp)
    lea     0x{PROBE:x},%a0
    move.l  #0xe27a0000,%d0
    move.l  %d0,0x1c(%a0)
    addq.l  #1,(%a0)
    move.l  (%sp)+,%a0
    move.l  (%sp)+,%d0
    addq.l  #4,%sp                | discard diag_entry return addr
    jmp     0x{RET1:x}
9:  cmpi.l  #255,%d7             | replicate original clamp (CC for the following bhiw)
    rts
"""


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC} -- run tools/build_persist256.py first")
    img = bytearray(SRC.read_bytes())

    p = "out/_diagb"
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
    img[bd.off(CODE):bd.off(CODE) + len(blob)] = blob
    o = bd.off(CLAMP)
    assert bytes(img[o:o + 6]) == b"\x0c\x87\x00\x00\x00\xff", img[o:o + 6].hex()
    img[o:o + 6] = b"\x4e\xb9" + sym["diag_entry"].to_bytes(4, "big")

    OUT.write_bytes(bytes(img))
    print(f"diag2: {len(blob)} B @0x{CODE:08x}; FN-VIEW(128) -> immediate success (skip whole body); "
          f"marker @0x{PROBE:08x}")
    print(f"{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
