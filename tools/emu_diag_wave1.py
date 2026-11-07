#!/usr/bin/env python3
"""emu_diag_wave1.py -- prove the four build_diag_wave1 hooks on the BUILT image before flashing.

Each case starts at the hooked firmware address, stops at the address the stub must resume at, and
checks: it got there, the stack delta equals what the displaced instructions do, every register the
firmware keeps live is untouched (sentinels), the displaced instructions' effects happened, and the
log / PROBE mirror holds exactly the expected records.
"""
import pathlib, struct, sys
from unicorn import *
from unicorn.m68k_const import *

sys.path.insert(0, "tools")
import build_diag_wave1 as W

IMG = pathlib.Path("out/mainos_diag_wave1.bin").read_bytes()
R = {f"d{i}": getattr(sys.modules["unicorn.m68k_const"], f"UC_M68K_REG_D{i}") for i in range(8)}
R.update({f"a{i}": getattr(sys.modules["unicorn.m68k_const"], f"UC_M68K_REG_A{i}") for i in range(7)})
SP = UC_M68K_REG_A7
SENT = {k: 0x5e000000 + i * 0x1111 for i, k in enumerate(sorted(R))}
FAILS = []


def mk():
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    uc.mem_map(0x40000000, 0x400000)
    uc.mem_map(0x40a00000, 0x200000)
    uc.mem_map(0x46000000, 0x200000)
    uc.mem_map(0x46c00000, 0x100000)
    uc.mem_map(0x41000000, 0x20000)
    uc.mem_write(0x40000400, IMG)
    for k, v in SENT.items():
        uc.reg_write(R[k], v)
    return uc


def w32(uc, a, v):
    uc.mem_write(a, struct.pack(">I", v & 0xffffffff))


def r32(uc, a):
    return struct.unpack(">I", uc.mem_read(a, 4))[0]


def run(uc, start, stops, sp, count=4000):
    uc.reg_write(SP, sp)
    hit = {}

    def h(uc, addr, size, _):
        if addr in stops:
            hit["at"] = addr
            hit["regs"] = {k: uc.reg_read(R[k]) for k in R}
            hit["sp"] = uc.reg_read(SP)
            uc.emu_stop()
    uc.hook_add(UC_HOOK_CODE, h)
    try:
        uc.emu_start(start, 0, count=count)
    except UcError as e:
        hit["err"] = str(e)
    return hit


def log(uc):
    n = r32(uc, W.LOG)
    return [r32(uc, W.LOG + 8 + 4 * i) for i in range(min(n, W.CAP))], n


def check(name, problems):
    print(("PASS " if not problems else "FAIL ") + name)
    for p in problems:
        print("      -", p)
    if problems:
        FAILS.append(name)


def regs_kept(hit, keep, want=None):
    want = want or {}
    return [f"{k} = {hit['regs'][k]:#x}, expected {want.get(k, SENT[k]):#x}"
            for k in keep if hit["regs"][k] != want.get(k, SENT[k])]


# ---------------------------------------------------------------- cache check 0x4007773c
def case_check():
    uc = mk()
    sp0 = 0x41010000
    VIEW = 0x41000100
    for i, v in enumerate([0x40077882, VIEW, 0, 3, 0]):       # ret, view, type 0, slot 3, force 0
        w32(uc, sp0 + 4 * i, v)
    w32(uc, 0x460e709c, 0)          # no build pending
    w32(uc, 0x46036830, 1)          # builder flag stuck
    w32(uc, 0x460e70a6, 3)          # cached slot 3
    w32(uc, 0x460e70a2, 0)          # cached type 0
    w32(uc, W.LOG, 0)
    w32(uc, W.LOG + 4, 0)
    hit = run(uc, W.CACHECHK, {W.CACHECHK + 8}, sp0)
    p = []
    if "err" in hit or hit.get("at") != W.CACHECHK + 8:
        return check("cache check: resumes at 0x40077744", [f"did not resume: {hit.get('err')}"])
    if hit["sp"] != sp0 - 8:
        p.append(f"sp {hit['sp']:#x}, expected {sp0 - 8:#x}")
    if r32(uc, sp0 - 8) != SENT["d2"] or r32(uc, sp0 - 4) != SENT["d3"]:
        p.append("displaced pushes of d2/d3 wrong")
    if hit["regs"]["a0"] != VIEW:
        p.append(f"a0 = {hit['regs']['a0']:#x}, expected the view arg {VIEW:#x}")
    p += regs_kept(hit, ["d2", "d3", "d4", "d5", "d6", "d7", "a2", "a3", "a4", "a5", "a6"])
    ent, n = log(uc)
    want = 0xB0000000 | 3 | (1 << 14) | (3 << 16)
    if ent != [want]:
        p.append(f"log {[hex(x) for x in ent]}, expected [{want:#x}]")
    # same state again: deduped, no second record
    uc2 = uc
    uc2.reg_write(SP, sp0)
    hit2 = run(uc2, W.CACHECHK, {W.CACHECHK + 8}, sp0)
    if log(uc2)[1] != 1:
        p.append(f"dedupe failed: {log(uc2)[1]} records after an identical call")
    # pending build + different slot: new record with bit 13
    w32(uc2, 0x460e709c, 1)
    w32(uc2, sp0 + 12, 7)
    run(uc2, W.CACHECHK, {W.CACHECHK + 8}, sp0)
    ent, n = log(uc2)
    want2 = 0xB0000000 | 7 | (1 << 13) | (1 << 14) | (3 << 16)
    if n != 2 or ent[-1] != want2:
        p.append(f"second record {[hex(x) for x in ent]}, expected ...{want2:#x}")
    check("cache check: resumes at 0x40077744, pushes d3/d2, a0 = view, logs + dedupes", p)


# ---------------------------------------------------------------- page init 0x4006f7a8
def case_page():
    uc = mk()
    sp0 = 0x41010000
    w32(uc, sp0, 0x40020c40)
    w32(uc, 0x46c8d19c, 3)          # slot index 3 -> "STATIC 004"
    w32(uc, 0x46c8d1a0, 0)          # type static
    w32(uc, W.LOG, 7)               # stale log from an earlier session
    w32(uc, W.LOG + 4, 0xB1234567)
    # reference: what 0x4006da78 returns for these globals
    hit = run(uc, W.PAGEINIT, {W.PAGEINIT + 6}, sp0)
    p = []
    if "err" in hit or hit.get("at") != W.PAGEINIT + 6:
        return check("page init", [f"did not resume: {hit.get('err')}"])
    if hit["sp"] != sp0:
        p.append(f"sp {hit['sp']:#x}, expected {sp0:#x}")
    want_d0 = 3 * 1096 + 0x100d5b30 if False else None
    # 0x4006da78 for type 0, slot 3 = SET-A/B helper result; compare with running the stock call alone
    ref = mk()
    w32(ref, 0x46c8d19c, 3)
    w32(ref, 0x46c8d1a0, 0)
    w32(ref, sp0 - 4, 0x40000400)
    rhit = run(ref, 0x4006da78, {0x40000400}, sp0 - 4)
    if hit["regs"]["d0"] != rhit["regs"]["d0"]:
        p.append(f"d0 = {hit['regs']['d0']:#x}, stock 0x4006da78 gives {rhit['regs']['d0']:#x}")
    p += regs_kept(hit, ["d2", "d3", "d4", "d5", "d6", "d7", "a2", "a3", "a4", "a5", "a6"])
    ent, n = log(uc)
    if ent != [0xE0000003] or r32(uc, W.LOG + 4) != 0:
        p.append(f"log {[hex(x) for x in ent]} lastB {r32(uc, W.LOG + 4):#x}, expected [0xe0000003], 0")
    check("page init: resets the log, records the slot, d0 = stock 0x4006da78 result", p)


# ---------------------------------------------------------------- builder open 0x4008e64c
def case_open(handle):
    uc = mk()
    frame = 0x41010000              # sp after the open's argument is popped
    sp0 = frame - 4                 # the open's argument still pushed at the hook
    w32(uc, sp0, 0xdeadbeef)
    w32(uc, frame + 116, 3)         # slot arg
    STATE = 0x46100000
    w32(uc, STATE + 36, 0x00001234)
    uc.reg_write(R["a3"], STATE)
    uc.reg_write(R["a4"], handle)
    uc.reg_write(R["d0"], handle)
    w32(uc, W.LOG, 0)
    good, bad = W.OPENRES + 8, W.OPENFAIL
    hit = run(uc, W.OPENRES, {good, bad}, sp0)
    p = []
    want_at = bad if struct.unpack(">i", struct.pack(">I", handle))[0] <= 0 else good
    if "err" in hit or hit.get("at") != want_at:
        return check(f"builder open {handle:#x}", [f"stopped at {hit.get('at')}, expected {want_at:#x}: {hit.get('err')}"])
    if hit["sp"] != frame:
        p.append(f"sp {hit['sp']:#x}, expected {frame:#x} (addql #4 replayed)")
    p += regs_kept(hit, ["d0", "d1", "d2", "d3", "d4", "d5", "d6", "d7", "a0", "a1", "a2", "a3", "a4", "a5", "a6"],
                   {"d0": handle, "a3": STATE, "a4": handle})
    ent, n = log(uc)
    if ent != [0xA0000003, handle, 0x1234]:
        p.append(f"log {[hex(x) for x in ent]}, expected [0xa0000003, {handle:#x}, 0x1234]")
    check(f"builder open result {handle:#x}: branches like the stock ble.w, regs intact, logs slot/result/file id", p)


# ---------------------------------------------------------------- mirror 0x400d6c00
def case_mirror():
    uc = mk()
    sp0 = 0x41010000
    data = [5, 0xB0000003] + [0x11110000 + i for i in range(W.CAP)]
    for i, v in enumerate(data):
        w32(uc, W.LOG + 4 * i, v)
    hit = run(uc, W.SCSAVE, {W.SCSAVE + 6}, sp0)
    p = []
    if "err" in hit or hit.get("at") != W.SCSAVE + 6:
        return check("mirror", [f"did not resume: {hit.get('err')}"])
    if hit["sp"] != sp0 - 12:
        p.append(f"sp {hit['sp']:#x}, expected {sp0 - 12:#x}")
    if [r32(uc, sp0 - 12), r32(uc, sp0 - 8), r32(uc, sp0 - 4)] != [SENT["d2"], SENT["d1"], SENT["d0"]]:
        p.append("displaced pushes d0/d1/d2 wrong")
    p += regs_kept(hit, list(R))
    if r32(uc, W.PROBE) != W.MAGIC:
        p.append("no magic in PROBE")
    got = [r32(uc, W.PROBE + 0x1a0 + 4 * i) for i in range(W.MIRROR_LONGS)]
    if got != data[:W.MIRROR_LONGS]:
        p.append("mirror content differs")
    if r32(uc, W.PROBE + 0x1a0 + 4 * W.MIRROR_LONGS) != 0:
        p.append("mirror wrote past its end")
    check("sidecar save: mirrors the whole log into PROBE, replays the three pushes, regs intact", p)
    # decoder round trip on what was mirrored
    print("      decoder:", W.decode(got)[:2])


case_check()
case_page()
case_open(0x2a)
case_open(0)
case_open(0xffffffff)
case_mirror()
print("\nALL GREEN" if not FAILS else "FAILED: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
