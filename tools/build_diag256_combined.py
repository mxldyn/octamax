#!/usr/bin/env python3
"""build_diag256_combined.py -- ONE session, TWO correlated measurements: (A) the assign slot-write at
0x400795c0 (value + dest addr), and (B) the voice-bind resolver 0x4000f484 per-idx histogram (what slots
the frame builder actually feeds the voice engine). This settles whether the per-part slot byte the
assign wrote (128) is the same byte the frame builder reads for the voice.

Do in ONE session: RELOAD -> assign slot 129 to a track (double-click track, dial 129, YES, NO) ->
place a TRIG on that track -> PLAY so it triggers -> SAVE.

Read: if the resolver histogram contains idx 128  -> the voice engine DID reach slot 128 (the silence is
DSP-side / downstream of the resolver). If it does NOT (only the old slots) while assign wrote 128 -> the
frame builder reads a DIFFERENT byte/copy than the assign wrote (part/pattern mismatch).

PROBE @0x40aa67e0 -> project.256[0x11200]:
  [0x000] assign_count  [0x004] assign_slot  [0x008] assign_dest_addr
  [0x010] resolver_count [0x014] magic 0xC0DE2000
  [0x040 + idx] resolver per-idx type byte (type|0x80 ; 0 = idx never seen), idx 0..255

    python3 tools/build_diag256_combined.py   # -> out/mainos_diag_comb.bin  (package as DUAL256P21)
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd

SRC = pathlib.Path("out/mainos_persist256.bin")
OUT = pathlib.Path("out/mainos_diag_comb.bin")
CODE = 0x400d6a00
PROBE = 0x40aa67e0
AW_HOOK = 0x400795c0          # moveb d1,a0@ ; addal #0x100a5198,a1
AW_BACK = 0x400795c8
RH_HOOK = 0x4000f484          # adda.l #0x800049d8,a2
RH_BACK = 0x4000f48a

ASM = f"""    .cpu 5407
    .text
| --- (A) assign slot-write capture ---
awrite_probe:
    move.l  %d0,-(%sp)
    move.l  %a2,-(%sp)
    lea     0x{PROBE:x},%a2
    move.l  #0xc0de2000,%d0
    move.l  %d0,0x14(%a2)
    addq.l  #1,%a2@
    move.l  %d1,4(%a2)
    move.l  %a0,%d0
    move.l  %d0,8(%a2)
    move.l  %sp@+,%a2
    move.l  %sp@+,%d0
    move.b  %d1,%a0@
    adda.l  #0x100a5198,%a1
    jmp     0x{AW_BACK:x}
| --- (B) resolver per-idx histogram ---
hist_probe:
    move.l  %d0,-(%sp)
    move.l  %d1,-(%sp)
    move.l  %a0,-(%sp)
    move.l  %sp@(80),%d0            | idx = arg1
    cmpi.l  #256,%d0
    bcc.b   1f
    move.l  %sp@(68),%d1            | machine type
    lea     0x{PROBE:x},%a0
    ori.l   #0x80,%d1
    move.b  %d1,%a0@(0x40,%d0:l)    | histogram[0x40+idx] = type|0x80
    addq.l  #1,%a0@(0x10)           | resolver count
    move.l  #0xc0de2000,%d1
    move.l  %d1,%a0@(0x14)
1:  move.l  %sp@+,%a0
    move.l  %sp@+,%d1
    move.l  %sp@+,%d0
    adda.l  #0x800049d8,%a2
    jmp     0x{RH_BACK:x}
"""


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC}")
    img = bytearray(SRC.read_bytes())
    p = "out/_comb"
    pathlib.Path(p + ".s").write_text(ASM)
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", p + ".o", p + ".s"], check=True)
    subprocess.run(["m68k-elf-ld", "-Ttext=0x%x" % CODE, "-o", p + ".elf", p + ".o"], capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", p + ".elf", p + ".bin"], check=True)
    nm = subprocess.run(["m68k-elf-nm", p + ".elf"], capture_output=True, text=True).stdout
    sym = {q[2]: int(q[0], 16) for q in (l.split() for l in nm.splitlines()) if len(q) == 3}
    blob = pathlib.Path(p + ".bin").read_bytes()
    for f in (".s", ".o", ".elf", ".bin"):
        pathlib.Path(p + f).unlink(missing_ok=True)
    assert not any(img[bd.off(CODE):bd.off(CODE) + len(blob)]), "cave not empty"
    img[bd.off(CODE):bd.off(CODE) + len(blob)] = blob
    # hook A (8-byte -> jmp + nop)
    o = bd.off(AW_HOOK)
    assert bytes(img[o:o + 8]) == b"\x10\x81\xd3\xfc\x10\x0a\x51\x98", img[o:o + 8].hex()
    img[o:o + 6] = b"\x4e\xf9" + sym["awrite_probe"].to_bytes(4, "big")
    img[o + 6:o + 8] = b"\x4e\x71"
    # hook B (6-byte -> jmp)
    o = bd.off(RH_HOOK)
    assert bytes(img[o:o + 6]) == b"\xd5\xfc\x80\x00\x49\xd8", img[o:o + 6].hex()
    img[o:o + 6] = b"\x4e\xf9" + sym["hist_probe"].to_bytes(4, "big")
    OUT.write_bytes(bytes(img))
    print(f"diag-combined: {len(blob)} B @0x{CODE:08x}; hooks assign-write 0x{AW_HOOK:08x} + resolver-hist 0x{RH_HOOK:08x}")
    print(f"{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
