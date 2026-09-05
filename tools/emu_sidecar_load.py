#!/usr/bin/env python3
"""emu_sidecar_load.py -- EMULATOR proof of the persistence CLOBBER.

sidecar_load (0x400d669e, installed at LOAD_HOOK 0x4009021a = epilogue of the FLEX loader, which runs
AFTER the STATIC load-loop) does an UNCONDITIONAL block IO_READ of <projdir>/project.256 over the whole
SETTINGS-B region (0x40a955e0, ln bytes). This runs it in Unicorn with the IO calls stubbed, seeding
SET-B[0]@0 with a "parser-written" path first, and tests three project.256 states:

  (A) populated  (slot-0 path present)  -> SET-B[0]@0 = that path        (restore works)
  (B) empty      (slot-0 zeros)         -> SET-B[0]@0 = 0  (CLOBBERED)   <<< the name-blank bug
  (C) missing    (open fails)           -> SET-B[0]@0 unchanged (skip)

    python3 tools/emu_sidecar_load.py
"""
import pathlib, sys
from unicorn import *
from unicorn.m68k_const import *
sys.path.insert(0, "tools")
import build_dual256 as bd

BASE = 0x40000400
IMGPATH = sys.argv[1] if len(sys.argv) > 1 else "out/mainos_persist256.bin"
IMG = bytes(pathlib.Path(IMGPATH).read_bytes())   # tools/build_all.py relocates the sidecar, so the
                                                  # stub VAs are read from whichever image is passed
# Both stub VAs are READ FROM THE IMAGE (the wave-23 refactor moves them), never hardcoded.
LOAD_HOOK, BULK_HOOK = bd.LOAD_HOOK, bd.BULKLOAD_HOOK
def _jmp_target(va):
    o = va - BASE
    assert IMG[o:o + 2] == b"\x4e\xf9", f"0x{va:08x} is not a jmp stub: {IMG[o:o+2].hex()}"
    return int.from_bytes(IMG[o + 2:o + 6], "big")
SIDE_LOAD = _jmp_target(LOAD_HOOK)     # sidecar_load  (restore + prime, then the verbatim moveml)
BULK_LOAD = _jmp_target(BULK_HOOK)     # bulk_restore  (restore only, then the replicated prologue)
END = LOAD_HOOK + 6                    # where sidecar_load jmps when done
BULK_END = BULK_HOOK + 8               # where bulk_restore jmps when done
SETB_LO = bd.SETB_LO                    # 0x40a955e0
STRIDE = 0x448
DIR_OF, IO_SPRINTF = 0x40025230, 0x40013a08
SAMPLEVIEW = 0x40093980   # wave-21 priming call; pure HW (file+DSP), stubbed here
IO_OPEN, IO_READ, IO_CLOSE = 0x40016864, 0x40016564, 0x4001677c
DIRSTR = 0x00008100                     # scratch dir string


def run(mode, file_bytes, entry="load"):
    mu = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    for a, s in [(0x40000000, 0x2000000), (0x10000000, 0x400000),
                 (0x46000000, 0x1000000), (0x00008000, 0x8000)]:
        mu.mem_map(a, s)
    mu.mem_write(BASE, IMG)
    mu.mem_write(DIRSTR, b"SET\x00")
    # seed SET-B[0]@0 with a path the parser "already wrote"
    seeded = b"PARSER.wav\x00"
    mu.mem_write(SETB_LO, seeded + b"\x00" * (STRIDE - len(seeded)))

    state = {"primed": []}

    def stub(mu, address, size, ud):
        sp = mu.reg_read(UC_M68K_REG_A7)
        def ret_with(d0):
            r = int.from_bytes(mu.mem_read(sp, 4), "big")
            mu.reg_write(UC_M68K_REG_D0, d0)
            mu.reg_write(UC_M68K_REG_A7, sp + 4)
            mu.reg_write(UC_M68K_REG_PC, r)
        if address == DIR_OF:
            ret_with(DIRSTR)                                   # return dir ptr
        elif address == IO_SPRINTF:
            ret_with(0)                                        # no-op (path content irrelevant; open stubbed)
        elif address == IO_OPEN:
            ret_with(0 if mode != "missing" else 0xffffffff)   # >=0 success / <0 fail
        elif address == IO_READ:
            # stack after jsr (top->): retaddr, stream(sp+4), dest(sp+8), len(sp+12)
            dest = int.from_bytes(mu.mem_read(sp + 8, 4), "big")
            ln = int.from_bytes(mu.mem_read(sp + 12, 4), "big")
            data = (file_bytes + b"\x00" * ln)[:ln]
            mu.mem_write(dest, data)
            ret_with(len(file_bytes))
        elif address == IO_CLOSE:
            ret_with(0)
        elif address == SAMPLEVIEW:
            slot = int.from_bytes(mu.mem_read(sp + 4, 4), "big")
            state["primed"].append(slot)
            if slot >= 128:                     # the real one always writes @16 (>=64) at 0x40093c92;
                mu.mem_write(bd.ST_B + (slot - 128) * bd.ST_STRIDE + 16,   # model that, so the wave-24
                             (0x300).to_bytes(4, "big"))                   # sweep correctly skips it
            ret_with(1)

    for f in (DIR_OF, IO_SPRINTF, IO_OPEN, IO_READ, IO_CLOSE, SAMPLEVIEW):
        mu.hook_add(UC_HOOK_CODE, stub, begin=f, end=f)

    sp = 0x0000c000
    start, stop = (SIDE_LOAD, END) if entry == "load" else (BULK_LOAD, BULK_END)
    mu.mem_write(sp, stop.to_bytes(4, "big"))
    mu.reg_write(UC_M68K_REG_A7, sp)
    mu.reg_write(UC_M68K_REG_A6, 0x0000b000)      # fp: moveml fp@(-576) lands in mapped stack
    # sentinels in every caller-visible register: a PROLOGUE hook must not disturb its function
    sent = {UC_M68K_REG_D0: 0x11111111, UC_M68K_REG_D1: 0x22222222, UC_M68K_REG_D2: 0x33333333,
            UC_M68K_REG_D3: 0x44444444, UC_M68K_REG_A0: 0x55555555, UC_M68K_REG_A1: 0x66666666,
            UC_M68K_REG_A2: 0x77777777, UC_M68K_REG_A3: 0x88888888}
    for r, v in sent.items():
        mu.reg_write(r, v)
    mu.reg_write(UC_M68K_REG_PC, start)
    mu.emu_start(start, stop, count=100000)
    got = bytes(mu.mem_read(SETB_LO, 16)).split(b"\x00", 1)[0]
    if entry == "load":
        clobbered = [n for n, r in [("d0", UC_M68K_REG_D0), ("d1", UC_M68K_REG_D1),
                                    ("a0", UC_M68K_REG_A0), ("a1", UC_M68K_REG_A1)]
                     if mu.reg_read(r) != sent[r]]
    else:
        # the bulk stub replicates the prologue, which SAVES d2-d7/a2-fp to the new frame; the
        # subroutine itself must leave every register untouched, so all eight sentinels must survive
        clobbered = [n for n, r in sent.items() if False] or \
                    [n for n, r in [("d0", UC_M68K_REG_D0), ("d1", UC_M68K_REG_D1), ("d2", UC_M68K_REG_D2),
                                    ("d3", UC_M68K_REG_D3), ("a0", UC_M68K_REG_A0), ("a1", UC_M68K_REG_A1),
                                    ("a2", UC_M68K_REG_A2), ("a3", UC_M68K_REG_A3)]
                     if mu.reg_read(r) != sent[r]]
        # and the prologue must have opened its 44-byte frame + saved 11 regs (sp -44 from entry)
        clobbered += [] if mu.reg_read(UC_M68K_REG_A7) == sp - 44 else [f"sp={mu.reg_read(UC_M68K_REG_A7)-sp}"]
    return got, clobbered, state["primed"]


def main():
    ln = bd.SETB_HI - bd.SETB_LO
    # a "populated" project.256: slot-0 path present
    populated = b"RESTORED.wav\x00" + b"\x00" * (ln - 13)
    empty = b"\x00" * ln
    print("sidecar_load 0x%08x, block read of %d B into SET-B 0x%08x\n" % (SIDE_LOAD, ln, SETB_LO))
    print("  seed (parser-written) SET-B[0]@0 = b'PARSER.wav'\n")
    a, ca, pa = run("populated", populated)
    b, cb, _ = run("empty", empty)
    c, cc, _ = run("missing", b"")
    print(f"  (A) project.256 populated (slot0='RESTORED.wav') -> SET-B[0]@0 = {a!r}   (restore)")
    print(f"  (B) project.256 empty     (slot0=zeros)          -> SET-B[0]@0 = {b!r}   (parser SURVIVES)")
    print(f"  (C) project.256 missing   (open fails)           -> SET-B[0]@0 = {c!r}   (unchanged)")
    # FIXED (skip-empty) contract: populated wins; empty does NOT clobber; missing untouched.
    okA = a == b"RESTORED.wav"
    okB = b == b"PARSER.wav"      # <-- was b'' before the fix; skip-empty preserves the parser path
    okC = c == b"PARSER.wav"
    # --- WAVE 23: the same restore, entered through the BULK-LOADER prologue stub (the boot path) ---
    print()
    print("  wave 23 -- bulk_restore 0x%08x (prologue hook 0x%08x, the path a POWER-CYCLE takes):"
          % (BULK_LOAD, BULK_HOOK))
    d, cd, pd = run("populated", populated, entry="bulk")
    e, ce, _ = run("missing", b"", entry="bulk")
    print(f"  (D) project.256 populated -> SET-B[0]@0 = {d!r}   regs+frame: {'OK' if not cd else cd}")
    print(f"  (E) project.256 missing   -> SET-B[0]@0 = {e!r}   regs+frame: {'OK' if not ce else ce}")
    print(f"      priming: LOAD path primed slots {pa} (wave 21 copy-loop + the wave-24 sweep, which "
          f"skips slots already armed) | BULK path primed {pd} (none by design -- the load loop it "
          f"precedes preps every populated slot itself)")
    okD = d == b"RESTORED.wav" and not cd and pd == [] and pa == [128]
    okE = e == b"PARSER.wav" and not ce
    okA = okA and not ca
    okB = okB and not cb
    okC = okC and not cc
    okAll = okA and okB and okC and okD and okE
    print("\n" + ("ALL GREEN -- skip-empty FIX verified: project.256 wins for populated slots (incl slices), "
                  "an EMPTY project.256 slot no longer clobbers SET-B (parser path survives) => name shows, "
                  "and a missing file leaves parser data intact."
                  " Wave 23: the bulk-loader prologue entry restores identically and leaves every "
                  "register and the replicated 44-byte frame exactly as the stock prologue would."
                  if okAll else
                  f"UNEXPECTED: A={okA} B={okB} C={okC} D={okD} E={okE} -- re-examine"))


if __name__ == "__main__":
    main()
