#!/usr/bin/env python3
"""
classify_sites.py — for each static-settings base-reference site, disassemble an instruction-
aligned window around it and decide RANDOM-ACCESS (index*0x448 + base, i.e. a `muls` feeds the
pointer -> must branch at idx>=128) vs WALK/LITERAL (loop bound / sequential / base as a plain
pointer -> leave on SRAM; the sidecar loader handles 128-255). 0x448 is not a power of two, so
index scaling is always a `muls` -- its presence in the same basic region is the discriminator.

Emits, per site: the muls-near verdict, the exact opcode, and a short pre-context so ambiguous
ones can be eyeballed. Groups the final verdict by role.

    python3 tools/classify_sites.py
"""
import subprocess

SITES = [
    0x400050d0, 0x4000f4b6, 0x40021e3e, 0x4002263e, 0x40023e36, 0x40023f4c, 0x40024574,
    0x40024fbc, 0x40025000, 0x400252b4, 0x40027728, 0x400277f8, 0x40029026, 0x4004411a,
    0x40044df8, 0x4004ff2e, 0x4006da9a, 0x40077e0a, 0x40079450, 0x40084c6e, 0x40084cb4,
    0x40086022, 0x40086472, 0x400869ce, 0x4008996e, 0x40089fa6, 0x4008b906, 0x4008f42c,
    0x4008f76a, 0x4008f8c8, 0x4008f9e2, 0x4008fb0a, 0x40090854, 0x40090f94, 0x400910f6,
    0x40091340, 0x400936cc, 0x400939a4, 0x40093f88, 0x40094380, 0x40098d0a, 0x400991dc,
    0x40099412, 0x40004f54, 0x40004ff4, 0x4000c6b8, 0x400893f0,
]
WIN_BACK = 0x50


def dis(start, stop):
    out = subprocess.run(
        ["m68k-elf-objdump", "-D", "-b", "binary", "-m", "m68k:68040",
         "--adjust-vma=0x40000400", f"--start-address=0x{start:x}",
         f"--stop-address=0x{stop:x}", "out/stock_mainos.bin"],
        capture_output=True, text=True).stdout.splitlines()
    # keep only disasm lines "40xxxxxx:\t..."
    return [l for l in out if l[:1] == "4" and ":" in l[:12]]


def main():
    rnd, walk = [], []
    for s in SITES:
        lines = dis(s - WIN_BACK, s + 8)
        muls = [l for l in lines if "muls" in l]
        siteln = next((l for l in lines if l.lstrip().startswith(f"{s:08x}:")), "")
        op = siteln.split("\t")[-1].strip() if "\t" in siteln else "?"
        # nearest muls distance in bytes (if any within window)
        near = None
        for l in muls:
            a = int(l.split(":")[0], 16)
            if 0 <= s - a <= WIN_BACK:
                near = s - a
        verdict = "RANDOM" if near is not None else "walk/lit"
        (rnd if near is not None else walk).append((s, op))
        d = f"muls-{near}B" if near is not None else "no-muls"
        print(f"0x{s:08x}  {verdict:8} [{d:9}]  {op}")

    print(f"\nRANDOM-ACCESS (branch at idx>=128): {len(rnd)}")
    for s, op in rnd:
        print(f"    0x{s:08x}  {op}")
    print(f"\nWALK/LITERAL (leave SRAM; sidecar for 128-255): {len(walk)}")
    for s, op in walk:
        print(f"    0x{s:08x}  {op}")


if __name__ == "__main__":
    main()
