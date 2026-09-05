#!/usr/bin/env python3
"""
Step 1 (pool relocation) + Step 2a (relocate the STATIC settings table to DDR 0x40a955e0)
+ ZERO-INIT hook, on R11. Tests whether the step-2a crash is uninitialized DDR.

  Step 1  flex pool +64 pages:  base 0x40a955e0->0x40af55e0 (23 refs), count 0x390A->0x38CA.
  Step 2a static settings table 0x100d5b30 -> 0x40a955e0 (delta +0x309bfab0), operand refs
          in the code region only.
  Zero-init: detour FUN_4009083c (reload orchestrator, every load) to zero
          [0x40a955e0, +0x22400) ONCE before the static slot loop reads any setting.

  If the project loads cleanly -> the crash was uninitialized DDR (2a SOLVED, do it at
  boot-init properly next). If it still hangs -> hypothesis dead; recover via EMPTY RESET
  (STARTUP menu TRIG 2) -> CF OS UPGRADE, then move to load-path logging.

    python3 tools/build.py           # -> out/mainos.bin (R11)
    python3 tools/build_zeroinit.py  # -> out/mainos_zeroinit.bin
"""
import pathlib, subprocess, sys

BASE = 0x40000400
R11 = pathlib.Path("out/mainos.bin")
OUT = pathlib.Path("out/mainos_zeroinit.bin")

# --- step 1: pool relocation ---
OLD_POOL, NEW_POOL = 0x40a955e0, 0x40af55e0
COUNT_AT, OLD_COUNT, NEW_COUNT = 0x40096f82, 0x390A, 0x38CA

# --- step 2a: static settings table relocation ---
TAB_LO, TAB_HI = 0x100d5b30, 0x100f7f31
TAB_DELTA = 0x40a955e0 - 0x100d5b30
CODE_END = 0x400e0000

# --- zero-init hook ---
CAVE_AT = 0x400d7240
DETOUR_AT = 0x4009083c
DETOUR_EXPECT = "4fefffd448d77cfc"   # 8 bytes: lea -0x2c(sp),sp ; movem.l d2-d7/a2-a6,(sp)


def off(a):
    return a - BASE


def opname(b0, b1):
    if b1 == 0xf9 and b0 in (0x41, 0x43, 0x45, 0x47, 0x49, 0x4b, 0x4d): return "lea"
    if (b0 << 8 | b1) == 0x4879: return "pea"
    if (b0 << 8 | b1) in (0x4eb9, 0x4ef9): return "jsr/jmp"
    if b1 == 0x7c and b0 in range(0x20, 0x2d, 2): return "movea#"
    if b1 == 0x3c and b0 in range(0x20, 0x2f, 2): return "move.l#"
    if (b0 << 8 | b1) == 0x23fc: return "move.l#abs"
    if b1 == 0xfc and b0 in (0xd1, 0xd3, 0xd5, 0xd7, 0xd9, 0xdb, 0xdd, 0xdf): return "adda#"
    if b1 == 0xfc and b0 in (0x91, 0x93, 0x95, 0x97, 0x99, 0x9b, 0x9d, 0x9f): return "suba#"
    if b1 == 0xfc and b0 in (0xb1, 0xb3, 0xb5, 0xb7, 0xb9, 0xbb, 0xbd, 0xbf): return "cmpa#"
    if b0 in (0x00, 0x02, 0x04, 0x06, 0x0a, 0x0c) and 0x80 <= b1 <= 0x87: return "immarith"
    return None


def main():
    if not R11.exists():
        sys.exit(f"missing {R11} — run tools/build.py first")
    img = bytearray(R11.read_bytes())

    # === step 1: pool relocation ===
    n = img.count(OLD_POOL.to_bytes(4, "big"))
    if not (18 <= n <= 30):
        sys.exit(f"pool-base count {n} unexpected — aborting")
    img = bytearray(img.replace(OLD_POOL.to_bytes(4, "big"), NEW_POOL.to_bytes(4, "big")))
    o = off(COUNT_AT)
    if int.from_bytes(img[o:o + 4], "big") != OLD_COUNT:
        sys.exit(f"count @0x{COUNT_AT:08x} != 0x{OLD_COUNT:x}")
    img[o:o + 4] = NEW_COUNT.to_bytes(4, "big")
    print(f"step 1: pool 0x{OLD_POOL:08x}->0x{NEW_POOL:08x} ({n} refs), count 0x{OLD_COUNT:x}->0x{NEW_COUNT:x}")

    # === step 2a: relocate the static settings table (operand refs in code) ===
    from collections import Counter
    byval = Counter()
    N = len(img)
    for i in range(2, N - 3):
        v = (img[i] << 24) | (img[i + 1] << 16) | (img[i + 2] << 8) | img[i + 3]
        if TAB_LO <= v < TAB_HI and (BASE + i) < CODE_END and opname(img[i - 2], img[i - 1]):
            img[i:i + 4] = (v + TAB_DELTA).to_bytes(4, "big")
            byval[v] += 1
    total = sum(byval.values())
    print(f"step 2a: settings 0x{TAB_LO:08x} -> 0x{TAB_LO+TAB_DELTA:08x}  ({total} operand refs, {len(byval)} distinct)")
    if not (50 <= total <= 62 and len(byval) == 4):
        sys.exit(f"unexpected settings-ref set (total {total}, distinct {len(byval)}) — aborting")

    # === zero-init hook: assemble, link at cave, inject, patch detour ===
    r = subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", "out/zeroinit.o",
                        "tools/patch_zeroinit.s"])
    if r.returncode:
        sys.exit("assembler failed")
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{CAVE_AT:x}", "-o", "out/zeroinit.elf",
                    "out/zeroinit.o"], capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/zeroinit.elf",
                    "out/zeroinit.bin"], check=True)
    nm = subprocess.run(["m68k-elf-nm", "out/zeroinit.elf"], capture_output=True,
                        text=True).stdout
    sym = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    blob = pathlib.Path("out/zeroinit.bin").read_bytes()
    end = CAVE_AT + len(blob)
    print(f"zero-init cave {len(blob)} B @ 0x{CAVE_AT:08x} .. 0x{end - 1:08x}  (cave ends 0x400d7c3b)")
    if end > 0x400d7c3c:
        sys.exit("blob overruns the code cave")
    if any(img[off(CAVE_AT):off(end)]):
        sys.exit(f"cave not free: {bytes(img[off(CAVE_AT):off(CAVE_AT)+16]).hex()}")
    img[off(CAVE_AT):off(end)] = blob

    o = off(DETOUR_AT)
    if bytes(img[o:o + 8]).hex() != DETOUR_EXPECT:
        sys.exit(f"detour 0x{DETOUR_AT:08x}: {bytes(img[o:o+8]).hex()} want {DETOUR_EXPECT}")
    img[o:o + 6] = b"\x4e\xf9" + sym["zi_stub"].to_bytes(4, "big")
    img[o + 6:o + 8] = b"\x4e\x71"    # nop pad to 8
    print(f"  detour 0x{DETOUR_AT:08x} -> zi_stub 0x{sym['zi_stub']:08x} (+nop pad)")

    OUT.write_bytes(bytes(img))
    print(f"\n{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
