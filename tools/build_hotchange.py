#!/usr/bin/env python3
"""
HOT CHANGE prototype v2 (MAXOHOT) — built ON TOP OF R11 (out/mainos.bin).

v1 skipped only FUN_40063e28's teardown and still cut AFTER selecting the project
(the second synchronous panic, in the load-post handler, killed the recorder).
v2 arms g_hot at the change and makes FUN_400a10c8 a one-shot no-op while armed.

Changes over R11:
  cave @0x400d7240 (patch_hotchange.s): hot_change + hot_panic + g_hot.
  detour FUN_40063e28 -> hot_change (arm g_hot + open picker, skip panic+stop-all).
  detour FUN_400a10c8 -> hot_panic  (one-shot skip while g_hot; else stock panic).
  in-place FUN_40096a5c unload bound 0x88 -> 0x80 (preserve recorder pages).
Lazy parts (R11) bridges the sounding recorder track's def -> enable LAZY TRANSITIONS
in PERSONALIZE after flashing.

Run tools/build.py first (produces out/mainos.bin = R11).

    python3 tools/build_hotchange.py    # -> out/mainos_hot.bin
"""
import pathlib, subprocess, sys

BASE = 0x40000400
CAVE_AT = 0x400d7240
R11 = pathlib.Path("out/mainos.bin")
OUT = pathlib.Path("out/mainos_hot.bin")

DETOURS = [(0x40063e28, "hot_change", "4aaf00046618"),
           (0x400a10c8, "hot_panic",  "4fefffdc48d7"),
           (0x400238a4, "hot_resync", "2f0a4eb94009"),
           (0x40096300, "hot_unload", "4fefffd848d7"),
           (0x40095a90, "hot_reclaim","4fefffd448d7"),
           (0x40096f24, "hot_reinit", "4fefffd448d7"),
           (0x40006820, "hot_vstop",  "2f0a2f02222f000c"),
           (0x40008f84, "hot_vstop2", "4feffff448d7040c"),
           (0x40007960, "hot_recmeta","4e56ff7448d73cfc"),
           (0x40008110, "hot_m1",     "4ebae70e206e0008"),
           (0x4000812c, "hot_m2",     "41f940095bdc")]
# NOTE: hot_noteoff on FUN_4000672c was REMOVED (v17 regression). FUN_4000672c is
# voice-ALLOCATION (0x461054ec free-mask + ff1 slot pick), not a pure DSP note-off;
# gating it corrupts track 6's voice -> absolute cut for the whole load. The patch
# source keeps hot_noteoff defined but it is no longer wired as a detour.


def off(a):
    return a - BASE


def main():
    if not R11.exists():
        sys.exit(f"missing {R11} — run tools/build.py first")
    img = bytearray(R11.read_bytes())

    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", "out/hc.o",
                    "tools/patch_hotchange.s"], check=True)
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{CAVE_AT:x}", "-o", "out/hc.elf",
                    "out/hc.o"], capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/hc.elf",
                    "out/hc.bin"], check=True)
    nm = subprocess.run(["m68k-elf-nm", "out/hc.elf"], capture_output=True,
                        text=True).stdout
    sym = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    blob = pathlib.Path("out/hc.bin").read_bytes()
    print(f"cave {len(blob)} B @ 0x{CAVE_AT:08x}")
    if any(img[off(CAVE_AT):off(CAVE_AT) + len(blob)]):
        sys.exit("cave not free in R11")
    img[off(CAVE_AT):off(CAVE_AT) + len(blob)] = blob

    for site, s, exp in DETOURS:
        o = off(site)
        n_exp = len(exp) // 2
        if not bytes(img[o:o + n_exp]).hex().startswith(exp):
            sys.exit(f"detour 0x{site:08x}: {bytes(img[o:o+n_exp]).hex()} want {exp}")
        img[o:o + 6] = b"\x4e\xf9" + sym[s].to_bytes(4, "big")
        # a detour that displaces >6 bytes (whole-instruction alignment) gets the
        # remaining displaced bytes filled with nop so no partial instruction is left
        for p in range(o + 6, o + n_exp, 2):
            img[p:p + 2] = b"\x4e\x71"
        print(f"  detour 0x{site:08x} -> {s} 0x{sym[s]:08x}"
              + (f" (+{n_exp-6}B nop)" if n_exp > 6 else ""))

    # recorder-page preservation is now handled by the gated hot_unload hook on
    # FUN_40096300 (covers every unload site), so no in-place FUN_40096a5c change.

    OUT.write_bytes(bytes(img))
    r11 = R11.read_bytes()
    n = sum(1 for x, y in zip(r11, img) if x != y)
    print(f"\n{OUT}: {len(img):,} bytes, {n} changed vs R11")


if __name__ == "__main__":
    main()
