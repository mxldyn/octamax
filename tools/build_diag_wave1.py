#!/usr/bin/env python3
"""build_diag_wave1.py -- why does the AED keep the previous track's waveform after a track copy?

HW repro (2026-11-07, OCTAMAX_2e): open the AED on T1, close it, copy T4 -> T5 (slot 4), enable slices
on T5, open the AED on T5 -> the title says STATIC 004 but the waveform is T1's. Picking slot 4 by hand
on T5 instead of copying shows the right waveform.

The waveform path (all stock code for a low slot):
  page init 0x4006f7a8  invalidates the peak range cache, clears 0x46036830
  draw      0x4007773c  cache check: key = (scroll, zoom, slot 0x460e70a6, type 0x460e70a2);
                        returns at once while a build is pending (0x460e709c); otherwise posts a
                        type-16 job to the worker queue 0x460d17ce and sets 0x460e709c
  worker    0x4008e608  STATIC builder: sets 0x46036830 = 1, opens the slot's file through
                        STATE[slot]@36 and the FS table at 0x46c82416, and if that open fails it
                        returns -1 WITHOUT clearing 0x46036830 and without touching the old peaks
  done      0x40076fdc  clears 0x460e709c

So two explanations fit "old waveform, right title": the builder never ran for slot 4 (request dropped
or cache key matched), or it ran and the open failed. This build records both, from the most recent
AED page init on, in a log in the code cave (never in SET-B; see the probe safety rules):

  0xE....... page init      low bits = the AED slot global 0x46c8d19c
  0xB....... cache check    bits 0-8 slot arg, 9-11 type arg, 12 force, 13 build pending (709c),
                            14 builder busy (46036830), 16-24 cached slot (70a6), 25-27 cached type
                            -- logged only when the value changes
  0xA....... builder        low bits = slot arg; followed by TWO raw longs: the open result
                            (<= 0 = failed) and STATE[slot]@36 (the file id it opened)

The log is mirrored into the PROBE block (0x40ab65e0 = project.256 offset 0x21000) when the project is
SAVED. That block overlaps SET-B: DO NOT USE UI SLOTS 252/253 with this build.

PROCEDURE: back up the project (*.work, *.strd, project.256) -> load it -> open the AED on T1, close ->
copy T4 -> T5, enable slices on T5 -> open the AED on T5 (wrong waveform) -> close -> SAVE -> mount CF.
    python3 tools/build_diag_wave1.py --read /Volumes/OCTATRACK/<set>/<proj>/project.256
"""
import pathlib, struct, subprocess, sys

sys.path.insert(0, "tools")
from hookcheck import check_holes

BASE = 0x40000400
SRC = pathlib.Path("out/mainos_all.bin")          # OCTAMAX_2e
OUT = pathlib.Path("out/mainos_diag_wave1.bin")

# free cave runs (all zero, no absolute or pc-relative refs in the 2e image; checked below too)
BLOB_A, LIM_A = 0x400d6850, 0x400d6900            # after led_stub
BLOB_D, LIM_D = 0x400d6998, 0x400d6a00            # after the r10 notimer block
BLOB_B, LIM_B = 0x400d702c, 0x400d7080            # after the allocator stub
LOG, LOG_END = 0x400d7be8, 0x400d7c3c             # after the arp blob: idx, lastB, 19 entries
CAP = (LOG_END - LOG - 8) // 4
PROBE, MAGIC = 0x40ab65e0, 0x10ade111
PROBE_OFF = 0x21000                               # PROBE - SET-B base 0x40a955e0
MIRROR_LONGS = (LOG_END - LOG) // 4

PAGEINIT, CACHECHK, OPENRES, SCSAVE = 0x4006f7a8, 0x4007773c, 0x4008e64c, 0x400d6c00
OPENFAIL = 0x4008ea2c                             # the builder's "return -1" exit
HOOKS = [  # (site, expected bytes, symbol, hole size)
    (PAGEINIT, "4eb94006da78", "h_page", 6),
    (CACHECHK, "2f032f02206f000c", "h_check", 8),
    (OPENRES, "588f4a806f0003da", "h_open", 8),
    (SCSAVE, "2f002f012f02", "h_mirror", 6),
]

COMMON = f"""    .cpu 5407
    .equ LOG, 0x{LOG:x}
    .equ CAP, {CAP}
    .text
"""

# A: cache-check logger + page-init reset
ASM_A = COMMON + f"""
    .equ REC, REC_ADDR
| entry of 0x4007773c: sp@4 view, sp@8 type, sp@12 slot, sp@16 force. d0/d1/a0/a1 are free here
| (the function loads them itself after its prologue); rec clobbers d1/a0.
    .global h_check
h_check:
    move.l  12(%sp),%d0               | slot and type are small ints: no masks (cave budget)
    move.l  8(%sp),%d1
    lsl.l   #8,%d1
    add.l   %d1,%d1
    or.l    %d1,%d0
    tst.l   16(%sp)
    beq.b   1f
    bset    #12,%d0
1:  tst.l   0x460e709c
    beq.b   2f
    bset    #13,%d0
2:  tst.l   0x46036830
    beq.b   3f
    bset    #14,%d0
3:  move.l  0x460e70a6,%d1
    andi.l  #0x1ff,%d1
    swap    %d1
    or.l    %d1,%d0
    move.l  0x460e70a2,%d1
    andi.l  #7,%d1
    move.l  %d0,%a1
    moveq   #25,%d0
    lsl.l   %d0,%d1
    move.l  %a1,%d0
    or.l    %d1,%d0
    ori.l   #0xB0000000,%d0
    lea     LOG,%a0
    cmp.l   4(%a0),%d0
    beq.b   4f
    move.l  %d0,4(%a0)
    jsr     REC
4:  move.l  %d3,-(%sp)                | displaced: movel d3,-(sp) ; movel d2,-(sp) ; moveal sp@(12),a0
    move.l  %d2,-(%sp)
    movea.l 12(%sp),%a0
    jmp     0x{CACHECHK + 8:x}

| 0x4006f7a8, first instruction of the AED page-0 init (jsr 0x4006da78): start a fresh log.
    .global h_page
h_page:
    lea     LOG,%a0
    clr.l   (%a0)
    clr.l   4(%a0)
    move.l  0x46c8d19c,%d0
    ori.l   #0xE0000000,%d0
    jsr     REC
    jsr     0x4006da78
    jmp     0x{PAGEINIT + 6:x}
"""

# D: rec + builder open-result logger
ASM_D = COMMON + f"""
| rec: append d0 to the log unless full. Clobbers d1/a0.
    .global rec
rec:
    lea     LOG,%a0
    move.l  (%a0),%d1
    cmpi.l  #CAP,%d1
    bge.b   1f
    addq.l  #1,(%a0)
    lsl.l   #2,%d1
    move.l  %d0,8(%a0,%d1.l)
1:  rts

| 0x4008e64c in the STATIC builder, right after the FS open (a4 = d0 already done): d0 = handle (<= 0
| failed), a3 = STATE[slot] (or 0), slot arg at sp@(116) once the open's argument is popped. Every
| register stays live. (0x4008e64a would also do, but a stray `bvc.b` in an operand points at its
| second word, so hookcheck refuses it; this hole swallows the ble.w instead and replays it.)
    .global h_open
h_open:
    addq.l  #4,%sp                    | displaced: addql #4,sp
    move.l  %d0,-(%sp)
    move.l  %d1,-(%sp)
    move.l  %a0,-(%sp)
    move.l  128(%sp),%d0              | 116 + 12
    ori.l   #0xA0000000,%d0
    bsr.b   rec
    move.l  8(%sp),%d0                | open result
    bsr.b   rec
    move.l  %a3,%d0
    beq.b   2f
    move.l  36(%a3),%d0               | the file id it opened
2:  bsr.b   rec
    move.l  (%sp)+,%a0
    move.l  (%sp)+,%d1
    move.l  (%sp)+,%d0
    tst.l   %d0                       | displaced: tstl d0 ; blew OPENFAIL
    ble.b   3f
    jmp     0x{OPENRES + 8:x}
3:  jmp     0x{OPENFAIL:x}
"""

# B: mirror the log into the PROBE block when the sidecar saves
ASM_B = COMMON + f"""
    .global h_mirror
h_mirror:
    move.l  %d0,-(%sp)                | displaced push 1 of 3
    move.l  %a0,-(%sp)
    move.l  %a1,-(%sp)
    lea     0x{PROBE:x},%a0
    move.l  #0x{MAGIC:x},(%a0)
    lea     0x1a0(%a0),%a0
    lea     LOG,%a1
    moveq   #{MIRROR_LONGS},%d0
1:  move.l  (%a1)+,(%a0)+
    subq.l  #1,%d0
    bne.b   1b
    move.l  (%sp)+,%a1
    move.l  (%sp)+,%a0
    move.l  (%sp),%d0
    move.l  %d1,-(%sp)                | displaced pushes 2 and 3
    move.l  %d2,-(%sp)
    jmp     0x{SCSAVE + 6:x}
"""


def off(va):
    return va - BASE


def assemble(name, src, at, limit):
    p = f"out/_wave1_{name}"
    pathlib.Path(p + ".s").write_text(src)
    r = subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", p + ".o", p + ".s"], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"{name}: {r.stderr}")
    subprocess.run(["m68k-elf-ld", "-Ttext=0x%x" % at, "-o", p + ".elf", p + ".o"], check=True, capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", p + ".elf", p + ".bin"], check=True)
    blob = pathlib.Path(p + ".bin").read_bytes()
    nm = subprocess.run(["m68k-elf-nm", p + ".elf"], capture_output=True, text=True).stdout
    sym = {ln.split()[2]: int(ln.split()[0], 16) for ln in nm.splitlines() if len(ln.split()) == 3}
    for f in (".s", ".o", ".elf", ".bin"):
        pathlib.Path(p + f).unlink(missing_ok=True)
    assert at + len(blob) <= limit, f"{name}: {len(blob)} B overruns 0x{limit:08x}"
    return blob, sym


def refs_into(img, lo, hi):
    """Absolute longword operands and pc-relative word displacements that land in [lo, hi)."""
    hits = []
    for i in range(0, len(img) - 4, 2):
        v = struct.unpack(">I", img[i:i + 4])[0]
        if lo <= v < hi:
            hits.append(BASE + i)
        w = struct.unpack(">H", img[i:i + 2])[0]
        if (w & 0xf1ff) == 0x41fa or w in (0x487a, 0x4eba, 0x4efa, 0x6000, 0x6100):
            t = BASE + i + 2 + struct.unpack(">h", img[i + 2:i + 4])[0]
            if lo <= t < hi:
                hits.append(BASE + i)
    return hits


def build():
    img = bytearray(SRC.read_bytes())
    base = bytes(img)
    for lo, hi in ((BLOB_A, LIM_A), (BLOB_D, LIM_D), (BLOB_B, LIM_B), (LOG, LOG_END)):
        assert not any(img[off(lo):off(hi)]), f"0x{lo:08x}..0x{hi:08x} not empty"
        assert not refs_into(base, lo, hi), f"0x{lo:08x}..0x{hi:08x} is referenced"

    blob_d, sym_d = assemble("d", ASM_D, BLOB_D, LIM_D)
    blob_a, sym_a = assemble("a", ASM_A.replace("REC_ADDR", "0x%x" % sym_d["rec"]), BLOB_A, LIM_A)
    blob_b, sym_b = assemble("b", ASM_B, BLOB_B, LIM_B)
    for at, blob in ((BLOB_A, blob_a), (BLOB_D, blob_d), (BLOB_B, blob_b)):
        img[off(at):off(at) + len(blob)] = blob
    sym = {**sym_a, **sym_d, **sym_b}

    check_holes(base, [(va, n) for va, _, _, n in HOOKS if va < 0x400d0000])
    for va, exp, name, n in HOOKS:
        o = off(va)
        assert bytes(img[o:o + n]).hex() == exp, f"0x{va:08x}: {bytes(img[o:o+n]).hex()} != {exp}"
        img[o:o + 6] = b"\x4e\xf9" + sym[name].to_bytes(4, "big")
        if n == 8:
            img[o + 6:o + 8] = b"\x4e\x71"
        print(f"  hook 0x{va:08x} -> {name} @0x{sym[name]:08x}")
    OUT.write_bytes(bytes(img))
    print(f"A {len(blob_a)}/{LIM_A-BLOB_A} B, D {len(blob_d)}/{LIM_D-BLOB_D} B, B {len(blob_b)}/{LIM_B-BLOB_B} B, "
          f"log cap {CAP}")
    print(f"{OUT}: {OUT.stat().st_size:,} bytes  -- DO NOT USE UI SLOTS 252/253")
    return sym


def decode(longs):
    """longs = [idx, lastB, entries...]"""
    n = min(longs[0], CAP)
    ent = longs[2:2 + n]
    out, i = [], 0
    while i < len(ent):
        v = ent[i]
        t = v >> 28
        if t == 0xE:
            out.append(f"AED page init      slot global = {v & 0xfffffff}  (title shows {(v & 0xfffffff) + 1:03d})")
        elif t == 0xB:
            out.append("cache check        slot={} type={} force={} pending={} busy={} | cached slot={} type={}".format(
                v & 0x1ff, (v >> 9) & 7, (v >> 12) & 1, (v >> 13) & 1, (v >> 14) & 1, (v >> 16) & 0x1ff, (v >> 25) & 7))
        elif t == 0xA:
            res = ent[i + 1] if i + 1 < len(ent) else None
            fid = ent[i + 2] if i + 2 < len(ent) else None
            r = "?" if res is None else (f"{res:#x}" + ("  <-- OPEN FAILED" if struct.unpack('>i', struct.pack('>I', res))[0] <= 0 else ""))
            out.append(f"BUILDER            slot={v & 0xfffffff} open={r} file id={fid if fid is None else hex(fid)}")
            i += 2
        else:
            out.append(f"?? {v:#010x}")
        i += 1
    if longs[0] > CAP:
        out.append(f"(log full: {longs[0]} records attempted, {CAP} kept)")
    return out


def read(path):
    data = pathlib.Path(path).read_bytes()
    blk = data[PROBE_OFF:PROBE_OFF + 0x1a0 + 4 * MIRROR_LONGS]
    magic = struct.unpack(">I", blk[:4])[0]
    if magic != MAGIC:
        sys.exit(f"no probe block (magic {magic:#x}): was the project SAVED with the diag build?")
    longs = list(struct.unpack(f">{MIRROR_LONGS}I", blk[0x1a0:0x1a0 + 4 * MIRROR_LONGS]))
    print("\n".join(decode(longs)))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--read":
        read(sys.argv[2])
    else:
        build()
