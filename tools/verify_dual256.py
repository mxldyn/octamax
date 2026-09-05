#!/usr/bin/env python3
"""
verify_dual256.py — emu-verify the DUAL-256 redirect helper family (no flashing).

Assembles tools/patch_dual256.s, loads the blob into Unicorn, and calls every helper across
boundary slot indices, asserting the exact per-table redirect contract:

  SETTINGS (stride 0x448):  idx<128 -> A ; 128..255 -> B ; >=256 -> A
  STATE    (stride 44):     idx<=128 -> A (template A[128]) ; 129..255 -> B ; >=256 -> A
  STRIDE4  (stride 4):      idx<=128 -> A ; 129..255 -> B ; >=256 -> A

Each helper receives PRODUCT=idx*stride in its register and returns the table pointer.

    python3 tools/verify_dual256.py     # -> ALL PASS / FAILURES
"""
import subprocess, pathlib, sys
from unicorn import *
from unicorn.m68k_const import *

REG = {"d0": UC_M68K_REG_D0, "d1": UC_M68K_REG_D1, "d2": UC_M68K_REG_D2, "d3": UC_M68K_REG_D3,
       "d4": UC_M68K_REG_D4, "d5": UC_M68K_REG_D5,
       "a0": UC_M68K_REG_A0, "a1": UC_M68K_REG_A1, "a2": UC_M68K_REG_A2, "a3": UC_M68K_REG_A3,
       "a4": UC_M68K_REG_A4}

# table params: base_A, stride, adj_B (SYNCED to patch_dual256.s .equ after SET-B relocation to the
# pool-reclaimed reserve 0x40a955e0; the old 0x476xxxxx values were the pre-relocation SET_B=0x47701a00).
SET_A, SET_ADJ = 0x100d5b30, 0x40a731e0
SETF_A, SETF_ADJ = 0x100d5c3e, 0x40a732ee
ST_A, ST_ADJ = 0x46c90a78, 0x40ab63e0
S41_A, S41_ADJ = 0x46c920a4, 0x40ab8de0
S42_A, S42_ADJ = 0x46c93a24, 0x40ab8fe0


def exp_settings(idx, A=SET_A, ADJ=SET_ADJ, stride=0x448):
    p = (idx * stride) & 0xffffffff
    if 128 <= idx < 256:
        return (ADJ + p) & 0xffffffff
    return (A + p) & 0xffffffff


def exp_state(idx, A=ST_A, ADJ=ST_ADJ, stride=44):
    # CURRENT aligned design: idx=128..255 -> STATE-B (idx=128 -> B[0], aligned with SETTINGS; the old
    # template-at-128 contract was replaced -- see patch_dual256.s STD "idx=128->B[0], aligned w/ SETTINGS").
    p = (idx * stride) & 0xffffffff
    if 128 <= idx <= 255:
        return (ADJ + p) & 0xffffffff
    return (A + p) & 0xffffffff


def exp_stride4(idx, A, ADJ, stride=4):
    p = (idx * stride) & 0xffffffff
    if 128 <= idx <= 255:
        return (ADJ + p) & 0xffffffff
    return (A + p) & 0xffffffff


# helper -> (register, stride, expected-fn)
HELPERS = {
    "h_set_d0": ("d0", 0x448, exp_settings), "h_set_d1": ("d1", 0x448, exp_settings),
    "h_set_d2": ("d2", 0x448, exp_settings), "h_set_d3": ("d3", 0x448, exp_settings),
    "h_set_a1": ("a1", 0x448, exp_settings), "h_set_a2": ("a2", 0x448, exp_settings),
    "h_set_a3": ("a3", 0x448, exp_settings), "h_set_a4": ("a4", 0x448, exp_settings),
    "h_setf_d0": ("d0", 0x448, lambda i: exp_settings(i, SETF_A, SETF_ADJ)),
    "h_st_d0": ("d0", 44, exp_state), "h_st_d1": ("d1", 44, exp_state),
    "h_st_d4": ("d4", 44, exp_state),
    "h_st_d5": ("d5", 44, exp_state), "h_st_a0": ("a0", 44, exp_state),
    "h_st_a2": ("a2", 44, exp_state), "h_st_a3": ("a3", 44, exp_state),
    "h_s41_a0": ("a0", 4, lambda i: exp_stride4(i, S41_A, S41_ADJ)),
    "h_s41_d0": ("d0", 4, lambda i: exp_stride4(i, S41_A, S41_ADJ)),
    "h_s42_a0": ("a0", 4, lambda i: exp_stride4(i, S42_A, S42_ADJ)),
    "h_s42_d0": ("d0", 4, lambda i: exp_stride4(i, S42_A, S42_ADJ)),
}
IDXS = [0, 1, 127, 128, 129, 200, 255, 256, 300, 0xffffffff]  # incl OOR + -1 sentinel (as huge)


def build():
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", "out/_d256.o", "tools/patch_dual256.s"],
                   check=True)
    subprocess.run(["m68k-elf-ld", "-Ttext=0x400d7400", "-o", "out/_d256.elf", "out/_d256.o"],
                   capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/_d256.elf", "out/_d256.bin"], check=True)
    nm = subprocess.run(["m68k-elf-nm", "out/_d256.elf"], capture_output=True, text=True).stdout
    sym = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    return pathlib.Path("out/_d256.bin").read_bytes(), sym


def call(blob, sym, name, reg, product):
    mu = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    mu.mem_map(0x400d7000, 0x2000)
    mu.mem_map(0x00010000, 0x1000)
    mu.mem_write(0x400d7400, blob)
    sp, ret = 0x00010800, 0x00010ffc
    mu.mem_write(sp, ret.to_bytes(4, "big"))
    mu.reg_write(UC_M68K_REG_A7, sp)
    mu.reg_write(REG[reg], product & 0xffffffff)
    mu.emu_start(sym[name], ret, count=20)
    return mu.reg_read(REG[reg])


def main():
    blob, sym = build()
    bad = 0; total = 0
    for name, (reg, stride, expfn) in HELPERS.items():
        for idx in IDXS:
            product = (idx * stride) & 0xffffffff
            got = call(blob, sym, name, reg, product)
            want = expfn(idx if idx < 256 else idx) & 0xffffffff
            # for the 0xffffffff sentinel idx, product huge -> treat as OOR -> A
            if idx == 0xffffffff:
                want = expfn(idx) & 0xffffffff
            total += 1
            if got != want:
                bad += 1
                print(f"  FAIL {name:10} idx={idx:<10} prod=0x{product:08x} -> 0x{got:08x} want 0x{want:08x}")
    for f in ("out/_d256.o", "out/_d256.elf", "out/_d256.bin"):
        pathlib.Path(f).unlink(missing_ok=True)
    print(f"blob {len(blob)} B; {len(HELPERS)} helpers x {len(IDXS)} indices = {total} checks; "
          f"{'ALL PASS' if bad == 0 else str(bad)+' FAILURES'}")
    sys.exit(0 if bad == 0 else 1)


if __name__ == "__main__":
    main()
