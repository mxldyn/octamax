#!/usr/bin/env python3
"""dis.py -- targeted m68k/ColdFire disassembly of the stock OS by VIRTUAL ADDRESS.
   VA 0x40000400 == file offset 0.  Usage:
     python3 tools/dis.py 0x40093980 0x40093e70          # disasm VA range
     python3 tools/dis.py 0x40093980 +0x200             # start + length
   Also importable: dis(va_start, va_end) -> list[(va, bytes, text)].
"""
import subprocess, sys, tempfile, pathlib

BASE = 0x40000400
# Which image to disassemble. DEFAULTS TO THE BUILT IMAGE, not stock: reading stock while reasoning
# about the patched build produced three wrong conclusions in one session (a guard looks closed at
# #128 in stock when the build has already raised it to #256). Override with OTDIS_IMG=<path>, or
# pass src= explicitly. The chosen file is announced once on first use so it can never be silent.
import os
_ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = pathlib.Path(os.environ.get("OTDIS_IMG") or (_ROOT / "out" / "mainos_persist256.bin"))
if not SRC.exists():
    SRC = _ROOT / "out" / "stock_mainos.bin"
_ANNOUNCED = set()


def off(va):
    return va - BASE


def dis(va0, va1, src=SRC):
    src = pathlib.Path(src)
    if src not in _ANNOUNCED:                      # never disassemble an unnamed image
        _ANNOUNCED.add(src)
        print(f"[otdis] disassembling {src}", file=sys.stderr)
    img = src.read_bytes()
    o0, o1 = off(va0), off(va1)
    chunk = img[o0:o1]
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
        f.write(chunk)
        tmp = f.name
    out = subprocess.run(
        ["m68k-elf-objdump", "-D", "-b", "binary", "-m", "m68k:5407",
         "--adjust-vma=0x%x" % va0, tmp],
        capture_output=True, text=True).stdout
    pathlib.Path(tmp).unlink(missing_ok=True)
    rows = []
    for ln in out.splitlines():
        s = ln.strip()
        if ":" not in s:
            continue
        head = s.split(":", 1)[0]
        try:
            int(head, 16)
        except ValueError:
            continue
        rows.append(ln)
    return rows


if __name__ == "__main__":
    a = int(sys.argv[1], 16)
    b = sys.argv[2]
    b = a + int(b[1:], 16) if b.startswith("+") else int(b, 16)
    for ln in dis(a, b):
        print(ln)
