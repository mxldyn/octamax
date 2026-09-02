#!/usr/bin/env python3
"""build_diag_bugA4.py -- BUG A write-trace probe. Traces every memcpy (0x40020898) whose dst OR src
falls in the ACTIVE bank's pattern/track region *(0x46c82456)+[0x8e000,0x92000), recording
[caller_PC][dst][src][len]. Rationale: the reload clears the per-pattern tagged track-slot array
(@0x8f1ad, idx>=128 -> 0). If that clear is a struct copy (validated live-state -> bank buffer, or a
rebuilt tagged array copied in), this names the caller_PC that writes the region. Header: [0]=TOTAL
memcpy calls, [4]=count recorded. If TOTAL>0 but count==0, the write is NOT via 0x40020898 (direct
byte-store) -> switch to a direct-store trace.

PROCEDURE: same track, assign UI 160, SAVE, RELOAD, (play), SAVE. Delete project.256 first. Avoid 252/253.
    python3 tools/read_probe.py <project.256> --build build_diag_bugA4
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd
from hookcheck import check_holes

SRC = pathlib.Path("out/mainos_persist256.bin")
BASE_VA = 0x40000400
OUT = pathlib.Path("out/mainos_diag_bugA4.bin")
CODE, PROBE = 0x400d7100, 0x40ab65e0
MAGIC = 0x10ade111
BANKPTR = 0x46c82456
MEMCPY = 0x40020898
RLO, RHI = 0x8e000, 0x92000

ASM = f"""    .cpu 5407
    .text
trace_mc:
    move.l  %d0,-(%sp)
    move.l  %d1,-(%sp)
    move.l  %d2,-(%sp)
    move.l  %d3,-(%sp)
    move.l  %a0,-(%sp)
    movea.l #0x{PROBE:x},%a0
    movea.l #0x{MAGIC:x},%a1
    move.l  %a1,(%a0)                    | magic
    move.l  4(%a0),%d2
    addq.l  #1,%d2
    move.l  %d2,4(%a0)                   | [4] TOTAL memcpy calls
    move.l  %sp@(24),%d0                 | dst (caller sp@(4), +20)
    move.l  %sp@(28),%d1                 | src (caller sp@(8), +20)
    movea.l #0x{BANKPTR:x},%a0
    move.l  (%a0),%d3                    | bankbase
    | dst in [base+RLO, base+RHI) ?
    move.l  %d3,%a1
    adda.l  #0x{RLO:x},%a1
    cmp.l   %a1,%d0
    blo.b   ck_src
    move.l  %d3,%a1
    adda.l  #0x{RHI:x},%a1
    cmp.l   %a1,%d0
    blo.b   record
ck_src:
    move.l  %d3,%a1
    adda.l  #0x{RLO:x},%a1
    cmp.l   %a1,%d1
    blo.b   done
    move.l  %d3,%a1
    adda.l  #0x{RHI:x},%a1
    cmp.l   %a1,%d1
    bhs.b   done
record:
    movea.l #0x{PROBE + 8:x},%a0
    move.l  (%a0),%d2                    | recorded count
    addq.l  #1,%d2
    move.l  %d2,(%a0)                    | [8] count++
    subq.l  #1,%d2
    andi.l  #15,%d2
    lsl.l   #4,%d2
    movea.l #0x{PROBE + 0x40:x},%a0
    adda.l  %d2,%a0
    move.l  %sp@(20),(%a0)+              | caller_PC (caller sp@(0), +20)
    move.l  %d0,(%a0)+                   | dst
    move.l  %d1,(%a0)+                   | src
    move.l  %sp@(32),(%a0)               | len (caller sp@(12), +20)
done:
    move.l  %sp@+,%a0
    move.l  %sp@+,%d3
    move.l  %sp@+,%d2
    move.l  %sp@+,%d1
    move.l  %sp@+,%d0
    move.l  %d2,-(%sp)
    movea.l %sp@(8),%a1
    jmp     0x{MEMCPY + 6:x}
"""

LAYOUT = {
    "MC": {"counter": 0x08, "array": 0x40, "entry": 16, "cap": 16, "total": 0x04,
           "fields": [("callerPC", 0, "hex"), ("dst", 4, "hex"), ("src", 8, "hex"), ("len", 12, "u32")]},
}

HOOKS = [
    (MEMCPY, "2f02226f0008", "trace_mc"),
]


def main():
    img = bytearray(SRC.read_bytes())
    p = "out/_bugA4"
    pathlib.Path(p + ".s").write_text(ASM)
    r = subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", p + ".o", p + ".s"], capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr)
    subprocess.run(["m68k-elf-ld", "-Ttext=0x%x" % CODE, "-o", p + ".elf", p + ".o"], capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", p + ".elf", p + ".bin"], check=True)
    blob = pathlib.Path(p + ".bin").read_bytes()
    nm = subprocess.run(["m68k-elf-nm", p + ".elf"], capture_output=True, text=True).stdout
    sym = {ln.split()[2]: int(ln.split()[0], 16) for ln in nm.splitlines() if len(ln.split()) == 3}
    for f in (".s", ".o", ".elf", ".bin"):
        pathlib.Path(p + f).unlink(missing_ok=True)
    assert not any(img[bd.off(CODE):bd.off(CODE) + len(blob)]), "cave not empty"
    img[bd.off(CODE):bd.off(CODE) + len(blob)] = blob
    base = bytes(SRC.read_bytes())
    check_holes(base, [(va, len(exp) // 2) for va, exp, _ in HOOKS])
    for va, exp, name in HOOKS:
        o, hole = bd.off(va), len(exp) // 2
        assert bytes(img[o:o + hole]).hex() == exp
        img[o:o + 6] = b"\x4e\xf9" + sym[name].to_bytes(4, "big")
        print(f"  hook 0x{va:08x} -> {name} @0x{sym[name]:08x}")
    OUT.write_bytes(bytes(img))
    print(f"blob {len(blob)} B; trace memcpy dst/src in *(0x{BANKPTR:x})+[0x{RLO:x},0x{RHI:x})")
    print("  -> DO NOT USE UI SLOTS 252, 253")
    print(f"{OUT}: {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
