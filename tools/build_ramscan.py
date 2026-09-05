#!/usr/bin/env python3
"""
RAM SCAN probe (Phase A, read-only) builder — on R11. See tools/patch_ramscan.s.
Repurposes the RELOAD confirm (FUN_40063bf8) to scan three proven-mapped RAM regions for
runs of all-zero 64 KB blocks (free-hole candidates for the static-pool extension) and
write the map + longest run to /RAMSCAN.TXT on the CF. Does NOT reload. Read-only: no
writes to RAM under test -> zero corruption / zero bus-fault risk.

    python3 tools/build.py          # -> out/mainos.bin (R11)
    python3 tools/build_ramscan.py  # -> out/mainos_ramscan.bin
"""
import pathlib, subprocess, sys

BASE = 0x40000400
CAVE_AT = 0x400d7240
R11 = pathlib.Path("out/mainos.bin")
OUT = pathlib.Path("out/mainos_ramscan.bin")

DETOURS = [(0x40063bf8, "recon_trigger", "4aaf0004661c")]   # RELOAD confirm


def off(a):
    return a - BASE


def main():
    if not R11.exists():
        sys.exit(f"missing {R11} — run tools/build.py first")
    img = bytearray(R11.read_bytes())
    r = subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", "out/ramscan.o",
                        "tools/patch_ramscan.s"])
    if r.returncode:
        sys.exit("assembler failed")
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{CAVE_AT:x}", "-o", "out/ramscan.elf",
                    "out/ramscan.o"], capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/ramscan.elf",
                    "out/ramscan.bin"], check=True)
    nm = subprocess.run(["m68k-elf-nm", "out/ramscan.elf"], capture_output=True,
                        text=True).stdout
    sym = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    blob = pathlib.Path("out/ramscan.bin").read_bytes()
    end = CAVE_AT + len(blob)
    print(f"ramscan cave {len(blob)} B @ 0x{CAVE_AT:08x} .. 0x{end - 1:08x}  (cave ends 0x400d7c3b)")
    if end > 0x400d7c3c:
        sys.exit("blob overruns the code cave — shrink logbuf")
    if any(img[off(CAVE_AT):off(end)]):
        sys.exit(f"cave not free in R11: {bytes(img[off(CAVE_AT):off(CAVE_AT)+16]).hex()}")
    img[off(CAVE_AT):off(end)] = blob
    for site, s, exp in DETOURS:
        o = off(site)
        if not bytes(img[o:o + len(exp) // 2]).hex().startswith(exp):
            sys.exit(f"detour 0x{site:08x}: {bytes(img[o:o+6]).hex()} want {exp}")
        img[o:o + 6] = b"\x4e\xf9" + sym[s].to_bytes(4, "big")
        print(f"  detour 0x{site:08x} -> {s} 0x{sym[s]:08x}")
    OUT.write_bytes(bytes(img))
    print(f"\n{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
