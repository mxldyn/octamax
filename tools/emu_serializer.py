#!/usr/bin/env python3
"""
emu_serializer.py -- run the STATIC [SAMPLE] serializer loop in Unicorn to (1) prove the harness
reproduces stock SLOT=001..128 output, then (2) verify a 256-extension patch emits SLOT=001..256
reading slots 128..255 from SET-B -- all WITHOUT flashing.

The STATIC loop lives inside the big project.work serializer. We enter at the STATIC-loop init
(0x400893ee: sets a3=SET+0x129, d4=1, a4=strlen, a5=IO_WRITE, fp=sprintf, a2=scratch, d5/d6/d7=path
helpers) and run to the loop exit (0x40089612). Only IO_WRITE (0x400166b8) is hooked -> it appends
(buf,len) to a Python capture; sprintf/strlen/path-helpers execute natively (pure string ops).

    python3 tools/emu_serializer.py            # stock loop
    python3 tools/emu_serializer.py --patch    # 256-extension loop (SET-B for 128..255)
"""
import sys, pathlib
from unicorn import *
from unicorn.m68k_const import *

IMG = pathlib.Path("out/stock_mainos.bin").read_bytes()
BASE = 0x40000400
SET_A = 0x100d5b30
SET_B = 0x40a955e0          # SETTINGS-B (matches build_dual256)
STRIDE = 0x448
IO_WRITE = 0x400166b8
LOOP_INIT = 0x400893ee
LOOP_EXIT = 0x40089612

R = {n: getattr(sys.modules['unicorn.m68k_const'], f"UC_M68K_REG_{n.upper()}")
     for n in ["d0","d1","d2","d3","d4","d5","d6","d7","a0","a1","a2","a3","a4","a5","a6","a7","pc"]}


def put_slot(mu, table, idx, path):
    """write a minimal slot record: path C-string at offset 0 (rest zero)."""
    addr = table + idx * STRIDE
    mu.mem_write(addr, path.encode() + b"\x00")


def run(patch=False, a_paths=None, b_paths=None, img=None):
    mu = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    mu.mem_map(0x40000000, 0x2000000)          # code + rodata
    mu.mem_map(0x10000000, 0x400000)           # SET-A (+ overflow room)
    mu.mem_map(0x46000000, 0x400000)           # DDR scratch 0x460bcca4 (path helper)
    mu.mem_map(0x47700000, 0x200000)           # SET-B
    mu.mem_map(0x00008000, 0x20000)            # stack
    mu.mem_write(BASE, bytes(img) if img is not None else IMG)

    # apply the 256-extension patch to the loop tail if requested (skip when the image is pre-patched)
    if patch and img is None:
        apply_patch(mu)

    # populate slots
    for i, p in (a_paths or {}).items():
        put_slot(mu, SET_A, i, p)
    for i, p in (b_paths or {}).items():
        put_slot(mu, SET_B, i, p)

    cap = bytearray()

    def hook_write(mu, addr, size, value, ud):
        pass

    def hook_code(mu, address, size, ud):
        if address == IO_WRITE:
            sp = mu.reg_read(R["a7"])
            buf = int.from_bytes(mu.mem_read(sp + 8, 4), "big")
            ln = int.from_bytes(mu.mem_read(sp + 12, 4), "big")
            if 0 < ln < 0x1000:
                cap.extend(mu.mem_read(buf, ln))
            # return: set d0=len (success) and RTS (pop retpc)
            mu.reg_write(R["d0"], ln)
            ret = int.from_bytes(mu.mem_read(sp, 4), "big")
            mu.reg_write(R["a7"], sp + 4)
            mu.reg_write(R["pc"], ret)

    mu.hook_add(UC_HOOK_CODE, hook_code)

    sp = 0x0001F000
    mu.reg_write(R["a7"], sp)
    mu.reg_write(R["d3"], 0x1234)               # stream handle (sentinel; IO_WRITE hooked)
    try:
        mu.emu_start(LOOP_INIT, LOOP_EXIT, count=2_000_000)
    except UcError as e:
        print(f"  emu stopped: {e} at pc=0x{mu.reg_read(R['pc']):08x}")
    return bytes(cap)


def apply_patch(mu):
    """Loop tail at 0x40089602: addq#1,d4 / lea a3@(0x448),a3 / cmpi#129,d4 / bne 0x40089420.
    Replace `cmpi.l #129,d4`(0c84 00000081 @0x40089608) + `bnew 0x40089420`(6600 fe10 @0x4008960e)
    with `jmp tail_patch`. tail_patch: if d4==129 -> a3=SET_B+0x129 ; if d4!=257 -> loop 0x40089420
    ; else jmp exit 0x40089612."""
    import subprocess
    CAVE = 0x400d6900
    asm = f"""    .cpu 5407
    .text
tail:
    cmpi.l  #129,%d4
    bne.b   1f
    lea     0x{SET_B + 0x129:x},%a3
1:  cmpi.l  #257,%d4
    beq.b   2f
    jmp     0x40089420
2:  jmp     0x40089612
"""
    p = "out/_tp"
    pathlib.Path(p + ".s").write_text(asm)
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", p + ".o", p + ".s"], check=True)
    subprocess.run(["m68k-elf-ld", "-Ttext=0x%x" % CAVE, "-o", p + ".elf", p + ".o"], capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", p + ".elf", p + ".bin"], check=True)
    blob = pathlib.Path(p + ".bin").read_bytes()
    mu.mem_write(CAVE, blob)
    # patch the 10 bytes at 0x40089608: jmp CAVE (4ef9 + addr) then 4 bytes pad (nop)
    patch = b"\x4e\xf9" + CAVE.to_bytes(4, "big") + b"\x4e\x71\x4e\x71"
    mu.mem_write(0x40089608, patch)
    for f in (".s", ".o", ".elf", ".bin"):
        pathlib.Path(p + f).unlink(missing_ok=True)


def main():
    imgpath = None
    if "--img" in sys.argv:
        imgpath = sys.argv[sys.argv.index("--img") + 1]
    img = bytearray(pathlib.Path(imgpath).read_bytes()) if imgpath else None
    patch = "--patch" in sys.argv or imgpath is not None    # a supplied image is already patched
    # populate a handful of A slots (and B slots when patched) with recognizable paths
    a = {0: "AUDIO/a000.wav", 1: "AUDIO/a001.wav", 56: "yok-vox.aif", 127: "AUDIO/a127.wav"}
    b = {0: "AUDIO/b128.wav", 1: "yok-vox.aif", 127: "AUDIO/b255.wav"} if patch else {}
    text = run(patch=patch, a_paths=a, b_paths=b, img=img)
    txt = text.decode("latin1")
    slots = [l for l in txt.splitlines() if l.startswith("SLOT=")]
    paths = [l for l in txt.splitlines() if l.startswith("PATH=")]
    print(f"mode: {'PATCH(256)' if patch else 'STOCK(128)'}")
    print(f"captured {len(text)} bytes; SLOT= lines: {len(slots)}; PATH= lines: {len(paths)}")
    print(f"  first SLOT: {slots[0] if slots else '-'}   last SLOT: {slots[-1] if slots else '-'}")
    # show the boundary + populated slots
    for want in (["SLOT=001", "SLOT=057", "SLOT=128", "SLOT=129", "SLOT=256"] if patch
                 else ["SLOT=001", "SLOT=057", "SLOT=128"]):
        ln = next((i for i, l in enumerate(txt.splitlines()) if l == want), None)
        if ln is not None:
            block = txt.splitlines()[ln:ln + 2]
            print(f"  {want}: {' | '.join(block)}")
        else:
            print(f"  {want}: (absent)")


if __name__ == "__main__":
    main()
