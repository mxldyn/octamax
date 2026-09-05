#!/usr/bin/env python3
"""build_probe256c.py -- pinpoint WHERE FN-VIEW (0x40093980) fails for STATIC slot 129 (idx 128) on
the RELOAD load-path. FN-VIEW is called at 0x40084c1a; it returns d0 (1=success, <=0 = failure code).
We WRAP that call (stack-neutral) and, for idx==128 only, capture the return value AND the resulting
STATE-B[0] fields, into the proven probe slot 0x40aa67e0 (SET-B slot 64) -> project.256[0x11200].

Return-code map (from the FN-VIEW disasm): 1=ok; -16 file-not-found; -30 bad magic; -43/-44/-47/-10
format/field; -29 file-too-short; <0 other = open()/dir retcode. This tells us the exact failure.

PROBE @0x40aa67e0 (project.256[0x11200]):
  [0x00] entered count   [0x04] FN-VIEW return d0   [0x08] STATE-B[0]@8   [0x0c] STATE-B[0]@12
  [0x10] STATE-B[0]@36   [0x1c] magic 0xF17E0000

  python3 tools/build_probe256c.py   # -> out/mainos_probe256c.bin  (package as DUAL256PC)
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd

SRC = pathlib.Path("out/mainos_persist256.bin")     # P9 base (built by build_persist256.py)
OUT = pathlib.Path("out/mainos_probe256c.bin")
PROBE_CODE = 0x400d6a00
PROBE = 0x40aa67e0                                   # SET-B slot 64 (unused) -> project.256[0x11200]
STATE_B0 = 0x40ab79e0
CALL_SITE = 0x40084c1a                               # jsr 0x40093980
FN_VIEW = 0x40093980

ASM = f"""    .cpu 5407
    .text
probe_wrap:
    | entry: sp@(0)=retaddr, sp@(4)=idx, sp@(8)=arg2
    move.l  %sp@(8),%d0            | arg2
    move.l  %sp@(4),%d1            | idx
    move.l  %d0,-(%sp)             | re-push arg2
    move.l  %d1,-(%sp)             | re-push idx
    jsr     0x{FN_VIEW:x}
    lea     %sp@(8),%sp            | pop the 2 temp args ; d0 = FN-VIEW return (preserved to rts)
    move.l  %sp@(4),%d1            | idx again
    cmpi.l  #128,%d1
    bne.b   1f
    lea     0x{PROBE:x},%a0
    move.l  #0xf17e0000,%d1
    move.l  %d1,0x1c(%a0)
    addq.l  #1,(%a0)
    move.l  %d0,4(%a0)             | FN-VIEW return d0
    movea.l #0x{STATE_B0:x},%a1
    move.l  %a1@(8),%d1
    move.l  %d1,8(%a0)             | STATE-B[0]@8
    move.l  %a1@(12),%d1
    move.l  %d1,0xc(%a0)           | STATE-B[0]@12
    move.l  %a1@(36),%d1
    move.l  %d1,0x10(%a0)          | STATE-B[0]@36
1:  rts
"""


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC} -- run tools/build_persist256.py first")
    img = bytearray(SRC.read_bytes())

    p = "out/_probec"
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

    o = bd.off(CALL_SITE)
    assert bytes(img[o:o + 6]) == b"\x4e\xb9\x40\x09\x39\x80", img[o:o + 6].hex()
    img[o:o + 6] = b"\x4e\xb9" + sym["probe_wrap"].to_bytes(4, "big")

    OUT.write_bytes(bytes(img))
    print(f"probe: {len(blob)} B @0x{PROBE_CODE:08x}; wrap call 0x{CALL_SITE:08x} -> probe_wrap; "
          f"data @0x{PROBE:08x} -> project.256[0x11200]")
    print(f"{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
