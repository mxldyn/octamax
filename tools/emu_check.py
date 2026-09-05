#!/usr/bin/env python3
"""
emu_check.py — pre-flash safety net. Unit-emulate individual firmware routines with
Unicorn (m68k/ColdFire CPU) and diff a PATCHED image against pristine STOCK, so we catch
the class of bug that cost us several flash/crash/sysex-recover cycles WITHOUT flashing.

What it CAN test (where every bug so far lived):
  - what a routine writes to the DSP/peripheral registers (0x8000xxxx) and to memory,
  - whether a modified routine computes the SAME register/memory effects as stock,
  - behaviour-equivalence of "neutral" changes (state accessors, relocation code).
What it CANNOT test: the DSP56300, real peripherals, or full-system boot/audio timing.
The non-determinism we hit came from the DSP consuming a desynced count; this harness
shows that desync at the SOURCE (the register write), which is the actionable signal.

Memory map (generous, zero-initialised like fresh Unicorn RAM):
  0x10000000 +2MB   SRAM  (stock settings block 0x100b14f0..)
  0x40000000 +16MB  DDR low: OS code @0x40000400, stack, pool/reserved/DDR-settings
  0x46000000 +16MB  DDR mid: STATE table 0x46c90a78, DSP buffers 0x46c2xxxx
  0x80000000 +64KB  DSP / peripheral registers
  0x0fff0000 +4KB   return trampoline (emu stops when a routine rts's back here)

CLI:
    python3 tools/emu_check.py [patched.bin]      # default: out/mainos_phase1.bin
    STOCK defaults to out/stock_mainos.bin (decode once via elektron-firmware-tool).

Add a check: write a function check_xxx(stock, patched) -> (name, ok, detail) and append
it to CHECKS. Use Emu.call(entry, regs=..., mem=..., max_insn=...) to drive a routine.
"""
import pathlib, sys
from unicorn import *
from unicorn.m68k_const import *

LOAD = 0x40000400
RET_TRAMP = 0x0fff0000
STACK_TOP = 0x40700000

REGS = {
    "d0": UC_M68K_REG_D0, "d1": UC_M68K_REG_D1, "d2": UC_M68K_REG_D2, "d3": UC_M68K_REG_D3,
    "d4": UC_M68K_REG_D4, "d5": UC_M68K_REG_D5, "d6": UC_M68K_REG_D6, "d7": UC_M68K_REG_D7,
    "a0": UC_M68K_REG_A0, "a1": UC_M68K_REG_A1, "a2": UC_M68K_REG_A2, "a3": UC_M68K_REG_A3,
    "a4": UC_M68K_REG_A4, "a5": UC_M68K_REG_A5, "a6": UC_M68K_REG_A6, "a7": UC_M68K_REG_A7,
    "pc": UC_M68K_REG_PC,
}


class Emu:
    """One firmware image loaded into a fresh emulated address space."""

    def __init__(self, image_path):
        self.img = pathlib.Path(image_path).read_bytes()
        self.name = pathlib.Path(image_path).name

    def _fresh(self):
        mu = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
        for base, size in [(0x00000000, 0x00400000), (0x10000000, 0x00200000),
                           (0x40000000, 0x01000000), (0x46000000, 0x01000000),
                           (0x80000000, 0x00010000), (RET_TRAMP & ~0xfff, 0x1000)]:
            mu.mem_map(base, size)
        # load the OS image at its link address
        span = min(len(self.img), 0x40000000 + 0x01000000 - LOAD)
        mu.mem_write(LOAD, self.img[:span])
        return mu

    def call(self, entry, regs=None, mem=None, watch_writes=True, log_access=False,
             max_insn=200000):
        """Run `entry` as a subroutine. Returns dict(regs_out, writes, reason[, reads, wcov]).
        `regs`: {name:val} initial registers. `mem`: {addr:bytes} pre-writes.
        `log_access=True` also records read-coverage (`reads`) and write-coverage (`wcov`)
        as sets of touched addresses — used by the DDR free-region tracer.
        Emulation stops when the routine rts's back to RET_TRAMP or max_insn is hit."""
        mu = self._fresh()
        if mem:
            for a, b in mem.items():
                mu.mem_write(a, b)
        if regs:
            for k, v in regs.items():
                mu.reg_write(REGS[k], v & 0xffffffff)
        # push the return trampoline as the subroutine's return address
        sp = STACK_TOP - 4
        mu.reg_write(UC_M68K_REG_A7, sp)
        mu.mem_write(sp, RET_TRAMP.to_bytes(4, "big"))

        writes = {}
        reads, wcov = set(), set()
        if watch_writes or log_access:
            def on_write(uc, access, address, size, value, user):
                writes[address] = (value & ((1 << (size * 8)) - 1), size)
                if log_access:
                    for k in range(size): wcov.add(address + k)
            mu.hook_add(UC_HOOK_MEM_WRITE, on_write)
        if log_access:
            def on_read(uc, access, address, size, value, user):
                for k in range(size): reads.add(address + k)
            mu.hook_add(UC_HOOK_MEM_READ, on_read)

        reason = "ret"
        try:
            mu.emu_start(entry, RET_TRAMP, count=max_insn)
        except UcError as e:
            reason = f"UcError:{e} @pc=0x{mu.reg_read(UC_M68K_REG_PC):08x}"
        pc = mu.reg_read(UC_M68K_REG_PC)
        if reason == "ret" and pc != RET_TRAMP:
            reason = f"count-exhausted @pc=0x{pc:08x}"
        out = {k: mu.reg_read(REGS[k]) for k in REGS}
        res = {"regs": out, "writes": writes, "reason": reason}
        if log_access:
            res["reads"], res["wcov"] = reads, wcov
        return res


# ---------------------------------------------------------------------------
# CHECKS  — each returns (name, ok: bool, detail: str)
# ---------------------------------------------------------------------------

# The DUAL-256 build intentionally reclaims 384 KB from the flex pool (build_ramdump.py Step 1,
# hardware-confirmed): pool base 0x40a955e0 -> 0x40af55e0 (all 23 code operands) and page count
# 0x390A -> 0x38CA at 0x40096f82 (-> DSP reg 0x80006920). 0x40a955e0 then hosts the B-tables, so it
# reappears as a few B-references. These three checks validate that EXACT reclaim and nothing more
# (audio buffers 0x46c2e9c0/e580/e780 must stay put; no other 0x390A count may change).
POOL_OLD, POOL_NEW, POOL_COUNT_OLD, POOL_COUNT_NEW = 0x40a955e0, 0x40af55e0, 0x390A, 0x38CA


def check_dsp_init_regs(stock, patched):
    """DSP-init prologue at 0x40096f80 programs regs 0x80006914/18/1c/20. Only 0x80006920 (the pool
    page count) may change, and only to the intended reclaim value 0x38CA; the rest must match stock."""
    entry = 0x40096f80
    s = stock.call(entry, max_insn=12)
    p = patched.call(entry, max_insn=12)
    diffs = []
    for r in (0x80006914, 0x80006918, 0x8000691c, 0x80006920):
        sv = s["writes"].get(r, (None, 0))[0]
        pv = p["writes"].get(r, (None, 0))[0]
        if r == 0x80006920:
            if pv != POOL_COUNT_NEW:
                diffs.append(f"0x{r:08x}: count patched={hex(pv) if pv is not None else None} != intended 0x{POOL_COUNT_NEW:x}")
        elif sv != pv:
            diffs.append(f"0x{r:08x}: stock={hex(sv) if sv is not None else None} "
                         f"patched={hex(pv) if pv is not None else None}")
    ok = not diffs
    detail = "DSP regs match stock (pool count -> 0x38CA)" if ok else "DSP REGS DIVERGE -> " + "; ".join(diffs)
    return ("dsp_init_regs", ok, detail)


def check_dsp_struct_intact(stock, patched):
    """Audio buffer bases 0x46c2e9c0/e580/e780 must be unrelocated. The flex-pool base is INTENTIONALLY
    reclaimed: all stock 0x40a955e0 operands become 0x40af55e0, and 0x40a955e0 reappears only as a
    handful of B-table references (<= the stock pool-ref count)."""
    cnt = lambda img, v: img.count(v.to_bytes(4, "big"))
    bad = []
    for v in (0x46c2e9c0, 0x46c2e580, 0x46c2e780):
        sc, pc = cnt(stock.img, v), cnt(patched.img, v)
        if sc != pc:
            bad.append(f"0x{v:08x}: stock refs={sc} patched refs={pc} (audio buffer moved!)")
    s_old = cnt(stock.img, POOL_OLD)
    p_new = cnt(patched.img, POOL_NEW)
    p_old = cnt(patched.img, POOL_OLD)      # additive B-table refs at the reclaimed base (expected)
    # all stock pool operands must relocate to the new base; the new base must be unused in stock.
    if p_new != s_old or cnt(stock.img, POOL_NEW) != 0:
        bad.append(f"pool reclaim off: 0x{POOL_OLD:08x} stock={s_old} -> new-base 0x{POOL_NEW:08x} refs={p_new}, "
                   f"stock new-base={cnt(stock.img, POOL_NEW)}")
    ok = not bad
    return ("dsp_struct_intact", ok, f"audio buffers intact; pool reclaimed (0x{POOL_OLD:08x} x{s_old} -> "
            f"0x{POOL_NEW:08x} x{p_new}, +{p_old} B-refs)" if ok else "DSP MEMORY RELOCATED -> " + "; ".join(bad))


def check_count_consistency(stock, patched):
    """Exactly ONE 0x390A (the pool page count at 0x40096f82) may become 0x38CA; every other 0x390A
    occurrence must be unchanged (changing a subset of a real DSP buffer count would crash audio)."""
    def counts(img):
        return img.count((0x390A).to_bytes(4, "big")), img.count((0x390A).to_bytes(2, "big"))
    sl, sw = counts(stock.img)
    pl, pw = counts(patched.img)
    # the single reclaim edit removes one long and one word occurrence of 0x390A
    ok = (pl, pw) == (sl - 1, sw - 1)
    return ("count_consistency", ok,
            f"0x390A long {sl}->{pl}, word {sw}->{pw} (intended: -1/-1 pool-count reclaim)"
            + ("" if ok else "  <-- UNEXPECTED COUNT DESYNC"))


def check_dual256_helpers(stock, patched):
    """DUAL-256 build: the redirect helper family (tools/patch_dual256.s) is installed at 0x400d7400.
    Re-assemble it and assert the image bytes byte-match the assembled+emu-verified blob (the return
    contract itself is proven by tools/verify_dual256.py). If the family isn't present, skip."""
    import subprocess, pathlib
    CAVE = 0x400d7400
    try:
        subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", "out/_dg.o", "tools/patch_dual256.s"],
                       check=True, capture_output=True)
        subprocess.run(["m68k-elf-ld", "-Ttext=0x%x" % CAVE, "-o", "out/_dg.elf", "out/_dg.o"],
                       capture_output=True)
        subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/_dg.elf", "out/_dg.bin"],
                       check=True, capture_output=True)
        blob = pathlib.Path("out/_dg.bin").read_bytes()
    finally:
        for f in ("out/_dg.o", "out/_dg.elf", "out/_dg.bin"):
            pathlib.Path(f).unlink(missing_ok=True)
    got = bytes(patched.img[CAVE - LOAD:CAVE - LOAD + len(blob)])
    # signature: the family begins with cmpi.l #0x22400,d0 (SET_LO) — the folded settings helper.
    is_family = got[:6] == b"\x0c\x80\x00\x02\x24\x00"
    if not is_family:
        return ("dual256_helpers", True, "no dual256 family present (skip)")
    ok = got == blob
    return ("dual256_helpers", ok,
            f"installed family byte-matches assembled+verified blob ({len(blob)} B)" if ok
            else "INSTALLED FAMILY DIFFERS from assembled patch_dual256.s")


def check_state_helpers(stock, patched):
    """If the image has state-accessor cave helpers, emulate each and confirm it returns
    base + product (the passthrough contract). Dynamic proof the jsr-to-cave plumbing runs
    and computes correctly — the thing we could not verify statically."""
    CAVE = 0x400d7400
    sig = patched.img[CAVE - LOAD:CAVE - LOAD + 2]
    # the DUAL-256 family also starts with 0c80; it is validated by check_dual256_helpers -> skip here.
    if patched.img[CAVE - LOAD:CAVE - LOAD + 6] == b"\x0c\x80\x00\x02\x24\x00":
        return ("state_helpers", True, "dual256 family (validated by dual256_helpers, skip)")
    if not any(patched.img[CAVE - LOAD:CAVE - LOAD + 72]):
        return ("state_helpers", True, "no cave helpers present (skip)")
    # only the passthrough (addi.l #,d0 = 0x0680) / redirect (cmpi.l #,d0 = 0x0c80) helpers have
    # this contract; other cave content (e.g. MAX256 loop trampolines) is not a state helper.
    if sig not in (b"\x06\x80", b"\x0c\x80"):
        return ("state_helpers", True, "cave present but not state helpers (skip)")
    TA = 0x46c90a78
    helpers = [(0x400d7400, "d0"), (0x400d7408, "d1"), (0x400d7410, "d2"), (0x400d7418, "d4"),
               (0x400d7420, "d5"), (0x400d7428, "a0"), (0x400d7430, "a2"), (0x400d7438, "a3"),
               (0x400d7440, "a5")]
    bad = []
    for addr, reg in helpers:
        for product in (0, 44, 127 * 44, 128 * 44):     # incl. the index-128 template
            r = patched.call(addr, regs={reg: product}, max_insn=20)
            got = r["regs"][reg]
            if got != ((TA + product) & 0xffffffff):
                bad.append(f"{reg}@0x{addr:x}(prod 0x{product:x})->0x{got:08x}")
    ok = not bad
    return ("state_helpers", ok,
            "all 9 helpers return base+product" if ok else "HELPER WRONG: " + "; ".join(bad[:5]))


CHECKS = [check_dsp_init_regs, check_dsp_struct_intact, check_count_consistency,
          check_dual256_helpers, check_state_helpers]


def main():
    patched_path = sys.argv[1] if len(sys.argv) > 1 else "out/mainos_phase1.bin"
    stock_path = "out/stock_mainos.bin"
    if not pathlib.Path(stock_path).exists():
        sys.exit(f"missing {stock_path} — decode stock once:\n"
                 f"  elektron-firmware-tool -i downloads/extracted/OCTATRACK_OS1.40C.syx -d 3 -o out/_s "
                 f"&& cp out/_s/section_3_MAIN_OS.bin {stock_path}")
    stock = Emu(stock_path)
    patched = Emu(patched_path)
    print(f"STOCK  : {stock_path}")
    print(f"PATCHED: {patched_path}\n")
    allok = True
    for chk in CHECKS:
        name, ok, detail = chk(stock, patched)
        allok &= ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:22} {detail}")
    print(f"\n{'ALL GREEN — safe to consider flashing' if allok else 'FAILURES — DO NOT FLASH'}")
    sys.exit(0 if allok else 1)


if __name__ == "__main__":
    main()
