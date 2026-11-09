#!/usr/bin/env python3
"""emu_ptnrestart.py -- prove patch_ptnrestart on the BUILT image (default out/mainos_all.bin).

The reference is the same image with the five detours put back to their original bytes, so every
"stock" comparison runs the exact firmware the patch sits on. Real firmware runs in every case:

  pick    the [PTN] select call as the trig handler makes it (0x40056b68 -> SELECT 0x400a1030 ->
          the real cue function 0x400a0570): the flag toggles only for the playing pattern with
          nothing cued while playing outside arranger mode; the sequencer globals end up exactly
          as stock leaves them; callee-saved registers and SP intact
  cue     any other caller of 0x400a0570 clears a cued restart
  switch  the real per-step decision 0x400a42fa..: a cued restart switches at the window
          (step % 16 == 0) and only there, is consumed by the switch, and with no restart cued the
          outcome and registers equal stock (window, other-pattern cue, natural end, no switch)
  led     the real pattern-trig LED painter 0x400353d4: with a restart cued, the playing trig
          gets the cued look (red + green); everything else equals stock
"""
import pathlib, struct, sys
from unicorn import *
from unicorn.m68k_const import *

sys.path.insert(0, "tools")
import build_ptnrestart as P

IMG_PATH = sys.argv[1] if len(sys.argv) > 1 else "out/mainos_all.bin"
IMG = pathlib.Path(IMG_PATH).read_bytes()
BASE = 0x40000400


def unpatched(img):
    b = bytearray(img)
    for site, _, exp, n, _ in P.DETOURS:
        b[site - BASE:site - BASE + n] = bytes.fromhex(exp)
    return bytes(b)


REF = unpatched(IMG)
C = sys.modules["unicorn.m68k_const"]
R = {f"d{i}": getattr(C, f"UC_M68K_REG_D{i}") for i in range(8)}
R.update({f"a{i}": getattr(C, f"UC_M68K_REG_A{i}") for i in range(7)})
SP = UC_M68K_REG_A7
SENT = {k: 0x5e000000 + i * 0x1111 for i, k in enumerate(sorted(R))}
CALLEE = ["d2", "d3", "d4", "d5", "d6", "d7", "a2", "a3", "a4", "a5", "a6"]

CUR_BANK, CUR_PTN, CUE_BANK, CUE_PTN = 0x800065bd, 0x800065be, 0x800065bf, 0x800065c0
PLAYING, ARRANGER, UI_BANK, CHAIN = 0x800065b8, 0x460d1aec, 0x80000002, 0x80006546
STEP, ENDSTEP = 0x800065b2, 0x8000662c
SHOWN = 0x100b14d0
LEDMAP = 0x460ba98c
RET = 0x0fff0000
SP0 = 0x41010000
FAILS = []


def syms():
    import subprocess
    nm = subprocess.run(["m68k-elf-nm", "out/patch_ptnrestart.elf"], capture_output=True, text=True).stdout
    return {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}


S = syms()
FLAG, SAME = S["RS_FLAG"], S["RS_SAME"]


def w8(uc, a, v):
    uc.mem_write(a, bytes([v & 0xff]))


def w16(uc, a, v):
    uc.mem_write(a, struct.pack(">H", v & 0xffff))


def w32(uc, a, v):
    uc.mem_write(a, struct.pack(">I", v & 0xffffffff))


def r8(uc, a):
    return uc.mem_read(a, 1)[0]


def r32(uc, a):
    return struct.unpack(">I", uc.mem_read(a, 4))[0]


def mk(img):
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    uc.mem_map(0x40000000, 0x1400000)
    uc.mem_map(0x46000000, 0x1000000)
    uc.mem_map(0x80000000, 0x10000)
    uc.mem_map(0x10000000, 0x200000)
    uc.mem_map(0x0fff0000, 0x10000)
    uc.mem_write(BASE, img)
    for k, v in SENT.items():
        uc.reg_write(R[k], v)
    return uc


def run(uc, start, stops, sp, stubs=()):
    uc.reg_write(SP, sp)
    st = {"calls": []}

    def h(uc, addr, size, _):
        if addr in stops:
            st["at"], st["sp"] = addr, uc.reg_read(SP)
            st["regs"] = {k: uc.reg_read(R[k]) for k in R}
            uc.emu_stop()
        elif addr in stubs:
            s = uc.reg_read(SP)
            st["calls"].append(addr)
            uc.reg_write(UC_M68K_REG_PC, r32(uc, s))
            uc.reg_write(SP, s + 4)
    uc.hook_add(UC_HOOK_CODE, h)
    try:
        uc.emu_start(start, 0, count=200000)
    except UcError as e:
        st["err"] = str(e)
    return st


def check(name, p):
    print(("PASS " if not p else "FAIL ") + name)
    for x in p:
        print("      -", x)
    if p:
        FAILS.append(name)


def seq_state(uc, cur, cue, playing=1, arranger=0):
    w8(uc, CUR_BANK, cur[0]); w8(uc, CUR_PTN, cur[1])
    w8(uc, CUE_BANK, cue[0]); w8(uc, CUE_PTN, cue[1])
    w32(uc, PLAYING, playing)
    w32(uc, ARRANGER, arranger)


SEQ_RANGE = (0x80006500, 0x80006700)
CUE_STUBS = {0x40009e00, 0x4009da20, 0x40000c3c, 0x4009e884, 0x40010bc8}


# ------------------------------------------------------------------ pick (the [PTN] select call)
def case_pick(name, cur, cue, pick_bp, flag, want_flag, playing=1, arranger=0):
    # start at the hook site: patched runs jsr rs_pick, reference runs the stock jsr SELECT
    def go(img):
        uc = mk(img)
        seq_state(uc, cur, cue, playing, arranger)
        w8(uc, FLAG, flag)
        sp = SP0
        w32(uc, sp, pick_bp[0]); w32(uc, sp + 4, pick_bp[1])
        st = run(uc, 0x40056b68, {0x40056b6e}, sp, CUE_STUBS)
        st["flag"], st["same"] = r8(uc, FLAG), r8(uc, SAME)
        st["seq"] = bytes(uc.mem_read(SEQ_RANGE[0], SEQ_RANGE[1] - SEQ_RANGE[0]))
        st["args"] = (r32(uc, sp), r32(uc, sp + 4))
        return st
    a, b = go(IMG), go(REF)
    p = []
    for s, n in ((a, "patched"), (b, "stock")):
        if "err" in s or s.get("at") != 0x40056b6e:
            return check(name, [f"{n} did not return to 0x40056b6e: {s.get('err')}"])
    if a["flag"] != want_flag:
        p.append(f"RS_FLAG {a['flag']}, expected {want_flag}")
    if a["same"] != 0:
        p.append("RS_SAME left set")
    if a["seq"] != b["seq"]:
        diff = [hex(SEQ_RANGE[0] + i) for i, (x, y) in enumerate(zip(a["seq"], b["seq"])) if x != y]
        p.append(f"sequencer globals differ from stock at {diff[:8]}")
    if a["calls"] != b["calls"]:
        p.append(f"firmware calls {[hex(c) for c in a['calls']]} != stock {[hex(c) for c in b['calls']]}")
    if a["sp"] != b["sp"]:
        p.append(f"sp {a['sp']:#x} != stock {b['sp']:#x}")
    if a["args"] != (pick_bp[0], pick_bp[1]):
        p.append(f"caller's argument slots changed to {a['args']} (stock clobbers its own copy only)")
    p += [f"{k} = {a['regs'][k]:#x} != stock {b['regs'][k]:#x}" for k in CALLEE if a["regs"][k] != b["regs"][k]]
    check(name, p)


A05, A06, B05 = (0, 4), (0, 5), (1, 4)
case_pick("pick the playing pattern, nothing cued: restart cued", A05, A05, A05, 0, 1)
case_pick("pick it again: the cued restart is cancelled", A05, A05, A05, 1, 0)
case_pick("restart cued, pick another pattern: restart dropped, other cued as stock", A05, A05, A06, 1, 0)
case_pick("another pattern cued, pick the playing one: stock cancel, no restart", A05, A06, A05, 0, 0)
case_pick("same pattern number in another bank: a normal cue", A05, A05, B05, 0, 0)
case_pick("stopped: immediate select as stock, no restart", A05, A05, A05, 0, 0, playing=0)
case_pick("arranger mode: no restart", A05, A05, A05, 0, 0, arranger=1)
case_pick("highest pattern P16 of bank P: restart cued", (15, 15), (15, 15), (15, 15), 0, 1)


# ------------------------------------------------------------------ cue: other callers clear it
def case_cue(name, same, want):
    uc = mk(IMG)
    seq_state(uc, A05, A05)
    w8(uc, FLAG, 1)
    w8(uc, SAME, same)
    sp = SP0
    for i, v in enumerate([RET, 0, 5, 0, 0xffffffff, 0]):
        w32(uc, sp + 4 * i, v)
    st = run(uc, 0x400a0570, {RET}, sp, CUE_STUBS)
    p = []
    if "err" in st or st.get("at") != RET:
        return check(name, [f"did not return: {st.get('err')}"])
    if r8(uc, FLAG) != want:
        p.append(f"RS_FLAG {r8(uc, FLAG)}, expected {want}")
    if r8(uc, CUE_PTN) != 5:
        p.append("the cue itself did not happen")
    p += [f"{k} = {st['regs'][k]:#x}" for k in CALLEE if st["regs"][k] != SENT[k]]
    check(name, p)


case_cue("any other cue (stop, MIDI PC, bank window, arranger) clears a cued restart", 0, 0)
case_cue("rs_pick's own cue call keeps it", 1, 1)


# ------------------------------------------------------------------ switch decision
PATTERN = 0x41200000
CELL = 0x41300000
SWITCH, NOSWITCH = 0x400a43a6, 0x400a4b9e


def decide(img, step, cue, flag, length=64, window_idx=8):
    uc = mk(img)
    w8(uc, 0x8000004e, 8)                      # global CHAIN BEHAVIOR = table[8] = 16
    seq_state(uc, A05, cue)
    w8(uc, FLAG, flag)
    w8(uc, PATTERN + 0x8e56, window_idx)       # CHAIN BEHAVIOR -> table 0x400d80dc[8] = 16
    w16(uc, STEP, step)
    w32(uc, ENDSTEP, 0xffffffff)
    w32(uc, CELL, 0x40)
    uc.reg_write(R["a4"], PATTERN)
    uc.reg_write(R["a2"], CELL)
    uc.reg_write(R["d7"], length)
    st = run(uc, 0x400a42fa, {SWITCH, NOSWITCH}, SP0)
    st["flag"] = r8(uc, FLAG)
    return st


def case_decide(name, step, cue, flag, want, want_flag, length=64, window_idx=8):
    a = decide(IMG, step, cue, flag, length, window_idx)
    b = decide(REF, step, cue, 0, length, window_idx)
    p = []
    if "err" in a or "at" not in a:
        return check(name, [f"patched did not reach a decision: {a.get('err')}"])
    if a["at"] != want:
        p.append(f"{'switch' if a['at'] == SWITCH else 'no switch'}, expected {'switch' if want == SWITCH else 'no switch'}")
    if a["flag"] != want_flag:
        p.append(f"RS_FLAG {a['flag']} after, expected {want_flag}")
    if a["sp"] != SP0:
        p.append(f"sp {a['sp']:#x}")
    if not flag:                                # nothing of ours involved: must be stock exactly
        if a["at"] != b["at"]:
            p.append(f"stock decides {b['at']:#x}")
        p += [f"{k} = {a['regs'][k]:#x} != stock {b['regs'][k]:#x}" for k in R if a["regs"][k] != b["regs"][k]]
    else:
        p += [f"{k} = {a['regs'][k]:#x} != stock {b['regs'][k]:#x}"
              for k in ["d3", "d4", "d5", "d7", "a2", "a3", "a4", "a5", "a6"] if a["regs"][k] != b["regs"][k]]
    check(name, p)


case_decide("restart cued, step 32 of 64, window 16: switches (restart), flag consumed", 32, A05, 1, SWITCH, 0)
case_decide("restart cued, step 33: waits for the window, flag kept", 33, A05, 1, NOSWITCH, 1)
case_decide("restart cued, step 16 (first window): switches", 16, A05, 1, SWITCH, 0)
case_decide("restart cued, window from the global setting (pattern byte -1)", 48, A05, 1, SWITCH, 0, window_idx=0xff)
case_decide("nothing cued, step 32: no switch (stock)", 32, A05, 0, NOSWITCH, 0)
case_decide("other pattern cued, step 32: switches (stock)", 32, A06, 0, SWITCH, 0)
case_decide("other pattern cued, step 33: waits (stock)", 33, A06, 0, NOSWITCH, 0)
case_decide("nothing cued, step 64 = length: natural loop switch (stock)", 64, A05, 0, SWITCH, 0)
case_decide("restart cued, step 64 = length before any window hit: switch consumes it", 64, A05, 1, SWITCH, 0,
            window_idx=12)


# ------------------------------------------------------------------ LED painter
def paint(img, cue, flag, playing=1, ui_bank=0, shown=4):
    uc = mk(img)
    seq_state(uc, A05, cue, playing)
    w8(uc, FLAG, flag)
    w8(uc, UI_BANK, ui_bank)
    w8(uc, SHOWN, shown)
    w32(uc, CHAIN, 0)
    uc.mem_write(LEDMAP, b"\x00" * 8)
    w32(uc, SP0, RET)
    st = run(uc, 0x400353d4, {RET}, SP0, {0x40010db0, 0x40010aa4, 0x40010d90})   # LED HW queue
    st["map"] = int.from_bytes(uc.mem_read(LEDMAP, 4), "big")
    return st


def case_led(name, cue, flag, extra, playing=1, ui_bank=0):
    a = paint(IMG, cue, flag, playing, ui_bank)
    b = paint(REF, cue, 0, playing, ui_bank)
    p = []
    for s, n in ((a, "patched"), (b, "stock")):
        if "err" in s or s.get("at") != RET:
            return check(name, [f"{n} painter did not return: {s.get('err')}"])
    # LED id n -> byte n>>3, bit n&7 of the map (FUN_400131a0); read as a big-endian long
    want = b["map"] | sum(1 << (24 - 8 * (i >> 3) + (i & 7)) for i in extra)
    if a["map"] != want:
        p.append(f"LED map {a['map']:#010x}, expected {want:#010x} (stock {b['map']:#010x})")
    p += [f"{k} = {a['regs'][k]:#x}" for k in CALLEE if a["regs"][k] != SENT[k]]
    check(name, p)


case_led("restart cued: the playing trig (P5) also lights green = the cued look", A05, 1, [9])
case_led("nothing cued: stock painting", A05, 0, [])
case_led("other pattern cued: stock cued painting", A06, 0, [])
case_led("restart flag while stopped: stock painting", A05, 1, [], playing=0)
case_led("restart cued but another bank shown: stock painting", A05, 1, [], ui_bank=3)

print("\nALL GREEN" if not FAILS else "FAILED: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
