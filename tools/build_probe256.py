#!/usr/bin/env python3
"""
build_probe256.py -- HW load-path probe on top of P4 (out/mainos_persist256.bin, pool-reclaimed,
B-tables at 0x40a955e0). Answers WHY STATIC SLOT=129 never lands in SETTINGS-B[0] on hardware,
which offline emulation cannot reproduce (it hits real HW registers / sample IO).

Two read-mostly detours log to an UNUSED SET-B slot (slot 64 = 0x40aa67e0), which sidecar_save dumps
to project.256[0x11200] on the next SAVE:

  A) DEST-STORE  0x400869fc (movel d0,0x460fab50): for idx==128 -> count++, record dest + TYPE.
     => did the parser REACH the SLOT=129 dest computation? what address did it compute?
  B) PATH-WRITE  0x40086a78 (movel 0x460fab50,sp@, just after sprintf/strlcpy): for idx==128 ->
     count++, record the first 8 bytes actually present at dest.
     => did the parser WRITE the path, and where?

PROBE layout @0x40aa67e0 (project.256 off 0x11200):
  [0x00] deststore count   [0x04] dest        [0x08] TYPE
  [0x0c] pathwrite count   [0x10] dest[0:4]   [0x14] dest[4:8]   [0x18] magic 0xC0FFEE00

Read after LOAD + SAVE:  python3 -c "d=open('.../project.256','rb').read()[0x11200:0x11200+0x20]; ..."

    python3 tools/build_probe256.py   # -> out/mainos_probe256.bin  (package as DUAL256PRB)
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd

SRC = pathlib.Path("out/mainos_persist256.bin")     # P4 base (built first by build_persist256.py)
OUT = pathlib.Path("out/mainos_probe256.bin")
PROBE_CODE = 0x400d6a00                              # free cave [0x400d6a00, 0x400d7400)
PROBE = 0x40aa67e0                                   # SET-B slot 64 (unused by altre-galassie)
DEST_STORE, PW = 0x400869fc, 0x40086a78
LOAD_ENTRY = 0x4008ffc4                              # jsr 0x40016864 at load-orchestrator start

ASM = f"""    .cpu 5407
    .text
probe_deststore:
    move.l  %d0,0x460fab50
    move.l  %d1,-(%sp)
    move.l  %a0,-(%sp)
    lea     0x{PROBE:x},%a0
    move.l  #0xc0ffee00,%d1
    move.l  %d1,0x18(%a0)
    move.l  0x400d1668,%d1
    cmpi.l  #128,%d1
    bne.b   1f
    addq.l  #1,(%a0)
    move.l  %d0,4(%a0)
    move.l  0x400d166c,%d1
    move.l  %d1,8(%a0)
1:  move.l  (%sp)+,%a0
    move.l  (%sp)+,%d1
    jmp     0x40086a02

probe_pathwrite:
    move.l  %d1,-(%sp)
    move.l  %a0,-(%sp)
    move.l  %a1,-(%sp)
    move.l  0x400d1668,%d1
    cmpi.l  #128,%d1
    bne.b   2f
    lea     0x{PROBE:x},%a0
    addq.l  #1,0xc(%a0)
    move.l  0x460fab50,%a1
    move.l  (%a1),%d1
    move.l  %d1,0x10(%a0)
    move.l  4(%a1),%d1
    move.l  %d1,0x14(%a0)
2:  move.l  (%sp)+,%a1
    move.l  (%sp)+,%a0
    move.l  (%sp)+,%d1
    move.l  0x460fab50,%sp@
    jmp     0x40086a7e

probe_loadentry:
    move.l  %d0,-(%sp)
    move.l  %a0,-(%sp)
    lea     0x{PROBE:x},%a0
    move.l  #0x10adcafe,%d0
    move.l  %d0,0x1c(%a0)
    addq.l  #1,0x20(%a0)
    move.l  (%sp)+,%a0
    move.l  (%sp)+,%d0
    jsr     0x40016864
    jmp     0x4008ffca
"""


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC} -- run tools/build_persist256.py first")
    img = bytearray(SRC.read_bytes())

    p = "out/_probe"
    pathlib.Path(p + ".s").write_text(ASM)
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", p + ".o", p + ".s"], check=True)
    subprocess.run(["m68k-elf-ld", "-Ttext=0x%x" % PROBE_CODE, "-o", p + ".elf", p + ".o"], capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", p + ".elf", p + ".bin"], check=True)
    nm = subprocess.run(["m68k-elf-nm", p + ".elf"], capture_output=True, text=True).stdout
    sym = {q[2]: int(q[0], 16) for q in (l.split() for l in nm.splitlines()) if len(q) == 3}
    blob = pathlib.Path(p + ".bin").read_bytes()
    for f in (".s", ".o", ".elf", ".bin"):
        pathlib.Path(p + f).unlink(missing_ok=True)

    assert not any(img[bd.off(PROBE_CODE):bd.off(PROBE_CODE) + len(blob)]), "probe cave not empty"
    assert PROBE_CODE + len(blob) <= 0x400d7400, "probe overruns helper cave"
    img[bd.off(PROBE_CODE):bd.off(PROBE_CODE) + len(blob)] = blob

    o = bd.off(DEST_STORE)
    assert bytes(img[o:o + 6]) == b"\x23\xc0\x46\x0f\xab\x50", img[o:o + 6].hex()
    img[o:o + 6] = b"\x4e\xf9" + sym["probe_deststore"].to_bytes(4, "big")
    o = bd.off(PW)
    assert bytes(img[o:o + 6]) == b"\x2e\xb9\x46\x0f\xab\x50", img[o:o + 6].hex()
    img[o:o + 6] = b"\x4e\xf9" + sym["probe_pathwrite"].to_bytes(4, "big")
    o = bd.off(LOAD_ENTRY)
    assert bytes(img[o:o + 6]) == b"\x4e\xb9\x40\x01\x68\x64", img[o:o + 6].hex()
    img[o:o + 6] = b"\x4e\xf9" + sym["probe_loadentry"].to_bytes(4, "big")

    OUT.write_bytes(bytes(img))
    print(f"probe: {len(blob)} B @0x{PROBE_CODE:08x}; detours 0x{DEST_STORE:08x}->probe_deststore, "
          f"0x{PW:08x}->probe_pathwrite; data @0x{PROBE:08x} -> project.256[0x11200]")
    print(f"{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
