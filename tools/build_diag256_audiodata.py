#!/usr/bin/env python3
"""build_diag256_audiodata.py -- FINAL decisive ColdFire-vs-DSP test. The idx=128 voice is active and
streaming, structurally identical to a playing low slot. The only thing left invisible: are the actual
SAMPLE BYTES the CF fetch returns real audio, or zeros? Hook the per-sample fetch result (0x40001494's
return, at 0x40091e5a `movel d0,d2`) and OR every fetched sample into an accumulator, split by voice
(a3 = STATE ptr, preserved across the refill).

  acc128 != 0  -> real audio IS read from CF for idx=128 -> silence is DSP-side (render/output).
  acc128 == 0 (while acc_low != 0) -> the CF read returns SILENCE for the high slot -> file-mapping /
                CF-stream-setup bug for idx>=128 (ColdFire, findable).

PROBE @0x40aa67e0 -> project.256[0x11200]:
  [0x00] acc128 (OR of fetched samples)  [0x04] acc_low  [0x08] cnt128  [0x0c] cntlow  [0x1c] magic 0xAUD10000

Do (one session): RELOAD -> assign slot 129 + trig -> ensure a low slot also plays -> PLAY -> SAVE.

    python3 tools/build_diag256_audiodata.py   # -> out/mainos_diag_audio.bin  (package as DUAL256P28)
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd

SRC = pathlib.Path("out/mainos_persist256.bin")
OUT = pathlib.Path("out/mainos_diag_audio.bin")
CODE = 0x400d6a00
PROBE = 0x40aa67e0
HOOK = 0x40091e5a             # movel d0,d2 ; lea sp@(16),sp   (2400 4fef0010)
BACK = 0x40091e60
STATE_B0 = 0x40ab79e0
STA_LO, STA_HI = 0x46c90a78, 0x46c92078

ASM = f"""    .cpu 5407
    .text
audioprobe:
    move.l  %d1,-(%sp)
    move.l  %a0,-(%sp)
    lea     0x{PROBE:x},%a0
    move.l  #0xaad10000,%d1
    move.l  %d1,%a0@(0x1c)
    move.l  %a3,%d1                | STATE ptr
    cmpi.l  #0x{STATE_B0:x},%d1
    bne.b   2f
    or.l    %d0,%a0@              | acc128 |= sample
    addq.l  #1,%a0@(8)
    bra.b   3f
2:  cmpi.l  #0x{STA_LO:x},%d1
    blo.b   3f
    cmpi.l  #0x{STA_HI:x},%d1
    bhs.b   3f
    or.l    %d0,%a0@(4)          | acc_low |= sample
    addq.l  #1,%a0@(0xc)
3:  move.l  %sp@+,%a0
    move.l  %sp@+,%d1
    move.l  %d0,%d2               | replicate movel d0,d2
    lea     %sp@(16),%sp          | replicate lea sp@(16),sp
    jmp     0x{BACK:x}
"""


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC}")
    img = bytearray(SRC.read_bytes())
    p = "out/_aud"
    pathlib.Path(p + ".s").write_text(ASM)
    r = subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", p + ".o", p + ".s"], capture_output=True, text=True)
    if r.returncode: sys.exit(r.stderr)
    subprocess.run(["m68k-elf-ld", "-Ttext=0x%x" % CODE, "-o", p + ".elf", p + ".o"], capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", p + ".elf", p + ".bin"], check=True)
    blob = pathlib.Path(p + ".bin").read_bytes()
    for f in (".s", ".o", ".elf", ".bin"):
        pathlib.Path(p + f).unlink(missing_ok=True)
    assert not any(img[bd.off(CODE):bd.off(CODE) + len(blob)]), "cave not empty"
    img[bd.off(CODE):bd.off(CODE) + len(blob)] = blob
    o = bd.off(HOOK)
    assert bytes(img[o:o + 6]) == b"\x24\x00\x4f\xef\x00\x10", img[o:o + 6].hex()
    img[o:o + 6] = b"\x4e\xf9" + CODE.to_bytes(4, "big")
    OUT.write_bytes(bytes(img))
    print(f"diag-audio: {len(blob)} B @0x{CODE:08x}; hook 0x{HOOK:08x} -> CF fetch sample OR-accumulator")
    print(f"{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
