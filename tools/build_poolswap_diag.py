#!/usr/bin/env python3
"""
DIAGNOSTIC (MAXODIAG) — minimal live-pool-swap de-risk, built from STOCK.

Tests hypothesis #1: can a sustained recording-buffer voice bridge a project
change if we (a) skip the up-front voice teardown and (b) preserve the recorder
pages? Two in-place byte patches, no cave, no PERSONALIZE toggle (always on —
this is a focused test build; reflash R11 afterwards):

  1. FUN_40063e28 (do_project_change): NOP out the teardown so the change opens
     the CHOOSE PROJECT picker WITHOUT FUN_400a10c8() (panic/reset) or
     FUN_40008fe4(0xffffffff) (kill all voices). Audio stays alive through the
     picker + load.
       0x40063e2e..0x40063e40 (18 B): jsr a10c8 / pea -1 / jsr 8fe4 / addq #4,sp
       -> 9x NOP (0x4e71). The trailing `jmp FUN_400647a0` (open picker) stays.
  2. FUN_40096a5c (flex pool prep): the unload loop `cmpi.l #0x88,D2` -> #0x80,
     so slots 0x80-0x87 (the 8 recorder buffers) are NOT unloaded -> their pool
     pages survive the reload.

User test: load a project; on a track, play/hold a recording buffer so it keeps
sounding; MUTE every other track; CHANGE PROJECT to a SAME-FORMAT sibling
(same RESERVE RECORDINGS config). Observe whether the recorder keeps sounding
through the change, and whether the new project loads cleanly.

    python3 tools/build_poolswap_diag.py    # -> out/mainos_poolswap.bin
"""
import pathlib, sys

BASE = 0x40000400
STOCK = pathlib.Path("out/raw/section_3_MAIN_OS.bin")
OUT = pathlib.Path("out/mainos_poolswap.bin")


def off(a):
    return a - BASE


def main():
    if not STOCK.exists():
        sys.exit(f"missing {STOCK}")
    img = bytearray(STOCK.read_bytes())

    # --- patch 1: FUN_40063e28 teardown -> NOPs ---
    at1 = 0x40063e2e
    exp1 = bytes.fromhex("4eb9400a10c84878ffff4eb940008fe4588f")   # 18 B
    o = off(at1)
    if bytes(img[o:o + len(exp1)]) != exp1:
        sys.exit(f"FUN_40063e28 teardown mismatch @0x{at1:08x}: {bytes(img[o:o+len(exp1)]).hex()}")
    img[o:o + len(exp1)] = b"\x4e\x71" * (len(exp1) // 2)          # 9x NOP
    print(f"  0x{at1:08x}  teardown ({len(exp1)} B) -> {len(exp1)//2}x NOP  "
          f"(skip FUN_400a10c8 + FUN_40008fe4; keep jmp FUN_400647a0)")

    # --- patch 2: FUN_40096a5c unload loop bound 0x88 -> 0x80 (skip recorders) ---
    at2 = 0x40096a70
    o = off(at2)
    if bytes(img[o:o + 4]) != (0x88).to_bytes(4, "big"):
        sys.exit(f"FUN_40096a5c bound not 0x88 @0x{at2:08x}: {bytes(img[o:o+4]).hex()}")
    img[o:o + 4] = (0x80).to_bytes(4, "big")
    print(f"  0x{at2:08x}  flex unload bound  0x88 -> 0x80  (preserve recorders 0x80-0x87)")

    OUT.write_bytes(bytes(img))
    stock = STOCK.read_bytes()
    n = sum(1 for x, y in zip(stock, img) if x != y)
    print(f"\n{OUT}: {len(img):,} bytes, {n} changed vs stock")


if __name__ == "__main__":
    main()
