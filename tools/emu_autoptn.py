#!/usr/bin/env python3
"""
emu_autoptn.py -- Unicorn proof for BANK AUTO PTN 1, run against the BUILT image.

Loads out/mainos_all.bin (override with argv[1]) next to out/stock_mainos.bin and drives the
bank window's REAL trig-press handler FUN_4007b2fc the way the key dispatcher does, with the
firmware entries that touch windows / LEDs / the sequencer replaced by `rts` and their stacked
arguments recorded. The assertions are about what the key press DOES to the bank state machine:

  toggle OFF        : stock and patched produce the same call log and the same globals, for every
                      bank 0..15, [BANK] up or held, phase 0 / 1 / 2 and an unavailable bank
  toggle ON, phase 0: FUN_4007b26c runs (phase 1, "BANK %c: SELECT PTN"), then the synthetic
                      trig-1 press closes the window (only if [BANK] is up), requests
                      FUN_400a1030(bank, 0) exactly once, lands in phase 2 with the held-key mask
                      on the BANK's trig; releasing that trig runs the stock cleanup
  toggle ON, other  : phases 1 and 2 and the unavailable-bank path stay byte-for-byte stock;
                      a stale held-key bit (stock quirk) is dropped so the pick selects, not chains;
                      a flag word holding anything but 1 reads as OFF
  dispatcher        : the same gestures driven through the REAL key dispatcher FUN_40031734 and
                      the REAL per-key table rebuild FUN_4003125c, with a synthetic "normal" trig
                      handler node in front of the bank node: the bank trig's release is routed to
                      FUN_4007b434 and afterwards the trig keys belong to the normal handler again
  menu              : getter returns the right glyph, setter normalises runtime + battery shadow
"""
import pathlib, struct, subprocess, sys
from unicorn import *
from unicorn.m68k_const import *

IMG_PATH = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "out/mainos_all.bin")
STOCK_PATH = pathlib.Path("out/stock_mainos.bin")
BASE = 0x40000400
RET = 0x0fff0000
SP0 = 0x41010000

F_FLAG, SH_FLAG = 0x800000a8, 0x100fff38
PHASE, BANK, ARMED, MASK, TOGGLE = 0x460e73c6, 0x460e73b8, 0x460e73bc, 0x460e73c0, 0x460e73c2
WIN, WIN_CB, WIN_EN = 0x460d1e5c, 0x460d1e60, 0x460d1e4c
KEYLIST, CBLIST = 0x460d165c, 0x460e7624
KEYNODE, CBNODE = 0x400cff14, 0x400cff28
BANKTBL, BANKSTRIDE = 0x4017d516, 0x9b340

TRIG_PRESS, TRIG_RELEASE, BANK_RELEASE, SELECT_PTN, ON_CLOSE = 0x4007b2fc, 0x4007b434, 0x4007b3e0, 0x4007b26c, 0x4007b408

# firmware entries replaced by rts (+ modelled side effect), with the names used in the logs
STUBS = {
    0x4005829c: "win_alloc",     0x40057008: "win_text",     0x40037cc8: "win_show",
    0x40012f30: "text_width",    0x40055db4: "win_free",     0x40000c3c: "post",
    0x4003125c: "keymap_rebuild", 0x4007e998: "cb_fire",
    0x400a1030: "PATTERN_SELECT", 0x4009c634: "PATTERN_CHAIN",
    0x400418e0: "ui_a", 0x40083bc0: "ui_b", 0x40032208: "ui_c", 0x400486cc: "ui_d",
    0x4004b528: "ui_e", 0x4004b08c: "ui_f", 0x40027de4: "led_bankptn",
    0x4005a2b8: "BANK_UNAVAILABLE_MSG",
}
# real code kept: FUN_4007b26c/2fc/434/3e0/408, FUN_40059f8c (window create), FUN_40056b00/a70
# (window close), FUN_40031494/46c (key-handler list), FUN_4007e760/81c (callback list),
# FUN_40031200, FUN_4009a404, the sprintf FUN_40013a08

NM = {}
for l in subprocess.run(["m68k-elf-nm", "out/patch_autoptn.elf"], capture_output=True, text=True).stdout.splitlines():
    p = l.split()
    if len(p) == 3:
        NM[p[2]] = int(p[0], 16)

IMGS = {"patched": IMG_PATH.read_bytes(), "stock": STOCK_PATH.read_bytes()}


def cstr(uc, p):
    b = b""
    while len(b) < 64:
        c = bytes(uc.mem_read(p, 1))
        if c == b"\0":
            break
        b += c
        p += 1
    return b.decode("latin1")


def mk(which):
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    for base, size in ((0x40000000, 0x1000000), (0x80000000, 0x10000), (0x10000000, 0x100000),
                       (0x46000000, 0x1100000), (0x41000000, 0x100000), (RET & ~0xfff, 0x1000)):
        uc.mem_map(base, size)
    uc.mem_write(BASE, IMGS[which])
    log = []

    def hook(uc, addr, size, user):
        if addr == RET:
            uc.emu_stop()
            return
        name = STUBS.get(addr)
        if name is None:
            return
        sp = uc.reg_read(UC_M68K_REG_A7)
        args = [struct.unpack(">I", uc.mem_read(sp + 4 + i * 4, 4))[0] for i in range(4)]
        if name == "win_alloc":
            uc.reg_write(UC_M68K_REG_D0, 0x1111)
        elif name == "text_width":
            uc.reg_write(UC_M68K_REG_D0, 50)
        elif name == "win_free":
            uc.mem_write(args[0], b"\0\0\0\0")
        log.append((name, args))

    for a in STUBS:
        uc.mem_write(a, b"\x4e\x75")
    uc.hook_add(UC_HOOK_CODE, hook)
    return uc, log


def w32(uc, a, v): uc.mem_write(a, struct.pack(">I", v & 0xFFFFFFFF))
def w16(uc, a, v): uc.mem_write(a, struct.pack(">H", v & 0xFFFF))
def r32(uc, a): return struct.unpack(">I", uc.mem_read(a, 4))[0]
def r16(uc, a): return struct.unpack(">H", uc.mem_read(a, 2))[0]


def seed(uc, flag, bank_up, phase=0, bank=0, mask=0, unavailable=None):
    """State right after [BANK] was pressed (FUN_4007af80) and, if bank_up, released
    (FUN_4007b3e0): window open with the close callback, trig handlers + LED callback
    registered, countdown armed only when [BANK] is up."""
    w32(uc, F_FLAG, flag)
    w32(uc, PHASE, phase); w32(uc, BANK, bank); w32(uc, ARMED, 1 if bank_up else 0)
    w16(uc, MASK, mask); w32(uc, TOGGLE, 1)
    w32(uc, WIN, 0x1111); w32(uc, WIN_CB, ON_CLOSE); w32(uc, WIN_EN, 1 if bank_up else 0)
    w32(uc, KEYLIST, KEYNODE); w32(uc, KEYNODE, 0)
    w32(uc, CBLIST, CBNODE); w32(uc, CBNODE, 0)
    if unavailable is not None:
        w32(uc, BANKTBL + unavailable * BANKSTRIDE, 1)


CANARY = {UC_M68K_REG_D2: 0x22222222, UC_M68K_REG_D3: 0x33333333, UC_M68K_REG_D4: 0x44444444,
          UC_M68K_REG_D5: 0x55555555, UC_M68K_REG_D6: 0x66666666, UC_M68K_REG_D7: 0x77777777,
          UC_M68K_REG_A2: 0x41020000, UC_M68K_REG_A3: 0x41030000, UC_M68K_REG_A4: 0x41040000,
          UC_M68K_REG_A5: 0x41050000, UC_M68K_REG_A6: 0x41060000}


def call(uc, fn, *args):
    """Call fn(*args) with the dispatcher's convention: args pushed, return to RET."""
    for r, v in CANARY.items():
        uc.reg_write(r, v)
    sp = SP0
    for a in reversed(args):
        sp -= 4
        w32(uc, sp, a)
    sp -= 4
    w32(uc, sp, RET)
    uc.reg_write(UC_M68K_REG_A7, sp)
    uc.emu_start(fn, 0, count=200000)
    pc = uc.reg_read(UC_M68K_REG_PC)
    assert pc == RET, f"did not return: pc={pc:#x}"
    assert uc.reg_read(UC_M68K_REG_A7) == SP0 - 4 * len(args), "stack unbalanced"
    for r, v in CANARY.items():
        assert uc.reg_read(r) == v, f"callee-saved register clobbered: {r} = {uc.reg_read(r):#x}"


def state(uc):
    return {"phase": r32(uc, PHASE), "bank": r32(uc, BANK), "armed": r32(uc, ARMED),
            "mask": r16(uc, MASK), "toggle": r32(uc, TOGGLE), "win": r32(uc, WIN),
            "win_cb": r32(uc, WIN_CB), "win_en": r32(uc, WIN_EN), "keylist": r32(uc, KEYLIST),
            "cblist": r32(uc, CBLIST), "chain": (r32(uc, 0x80006546), r32(uc, 0x8000654a), r32(uc, 0x8000654e))}


FAILS = []


def check(name, cond, detail=""):
    print(f"  {'ok ' if cond else 'FAIL'} {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def press(which, n, **kw):
    uc, log = mk(which)
    seed(uc, **kw)
    win_text = {}

    def spy(uc, addr, size, user):      # the text handed to the window creator
        if addr == 0x40059f8c:
            sp = uc.reg_read(UC_M68K_REG_A7)
            win_text.setdefault("texts", []).append(cstr(uc, r32(uc, sp + 4)))
    uc.hook_add(UC_HOOK_CODE, spy)
    call(uc, TRIG_PRESS, n, 1)
    return uc, log, state(uc), win_text.get("texts", [])


# ---------------- static: the build ----------------
print("image")
img = IMGS["patched"]
check("detour at 0x4007b344 -> ap_stub", img[0x4007b344 - BASE:0x4007b344 - BASE + 6] == b"\x4e\xf9" + NM["ap_stub"].to_bytes(4, "big"))
check("menu entry 20 = autoptn label/getter/setter",
      int.from_bytes(img[0x400d6a4c - BASE:0x400d6a50 - BASE], "big") == NM["lbl_autoptn"] and
      int.from_bytes(img[0x400d6a9c - BASE:0x400d6aa0 - BASE], "big") == NM["get_autoptn"] and
      int.from_bytes(img[0x400d6aec - BASE:0x400d6af0 - BASE], "big") == NM["set_autoptn"])
check("menu count: unconditional moveq #20 (MKII-flag sub.l replaced by nop)",
      img[0x40068fb2 - BASE:0x40068fb6 - BASE] == b"\x72\x14\x4e\x71", img[0x40068fb2 - BASE:0x40068fb6 - BASE].hex())
uc, _ = mk("patched")
check("label reads BANK AUTO PTN 1", cstr(uc, NM["lbl_autoptn"]) == "BANK AUTO PTN 1")

# ---------------- toggle OFF: stock equivalence ----------------
print("toggle OFF: stock equivalence")
cases = []
for n in range(16):
    for up in (True, False):
        cases.append(dict(flag=0, bank_up=up, phase=0, bank=0, mask=0))
cases += [dict(flag=0, bank_up=True, phase=1, bank=3, mask=0),      # SELECT PTN: pick a pattern
          dict(flag=0, bank_up=True, phase=2, bank=3, mask=0x10),   # a pattern key held: chain
          dict(flag=0, bank_up=False, phase=1, bank=9, mask=0),
          dict(flag=0, bank_up=True, phase=0, bank=0, mask=0, unavailable=4)]
allsame = True
for i, kw in enumerate(cases):
    n = i % 16 if kw["phase"] == 0 and "unavailable" not in kw else {1: 7, 2: 9, 0: 4}[kw["phase"]]
    _, ls, ss, ts = press("stock", n, **kw)
    _, lp, sp_, tp = press("patched", n, **kw)
    same = ls == lp and ss == sp_ and ts == tp
    allsame = allsame and same
    if not same:
        print(f"    DIFF case {kw} n={n}\n      stock   {ls} {ss} {ts}\n      patched {lp} {sp_} {tp}")
check(f"{len(cases)} cases: identical call log, globals and window text", allsame)
_, lp, sp_, tp = press("patched", 2, flag=0, bank_up=True)
check("phase-0 press lands in phase 1 with the SELECT PTN window",
      sp_["phase"] == 1 and sp_["bank"] == 2 and tp == ["BANK C: SELECT PTN"] and sp_["win"] == 0x1111
      and not any(nm == "PATTERN_SELECT" for nm, _ in lp), f"{sp_} {tp}")

# ---------------- toggle ON: phase 0, [BANK] up ----------------
print("toggle ON: bank trig with [BANK] up")
uc, log, st, texts = press("patched", 2, flag=1, bank_up=True)
sel = [a for nm, a in log if nm == "PATTERN_SELECT"]
check("SELECT PTN window was created (phase 1 reached through stock code)", texts == ["BANK C: SELECT PTN"], str(texts))
check("exactly one pattern request: (bank 2, pattern 0)", len(sel) == 1 and sel[0][:2] == [2, 0], str(sel))
check("window closed by the synthetic press", st["win"] == 0, str(st))
check("phase 2, bank 2, held-key mask = bit 2 (the bank's trig), [BANK] still armed",
      st["phase"] == 2 and st["bank"] == 2 and st["mask"] == 1 << 2 and st["armed"] == 1, str(st))
check("trig handlers still registered until the trig is released", st["keylist"] == KEYNODE and st["cblist"] == CBNODE)
check("no chain, no unavailable message", not any(nm in ("PATTERN_CHAIN", "BANK_UNAVAILABLE_MSG") for nm, _ in log))
names = [nm for nm, _ in log]
check("stock post-select refreshes ran once, in order",
      names[names.index("PATTERN_SELECT"):names.index("PATTERN_SELECT") + 8] ==
      ["PATTERN_SELECT", "ui_a", "ui_b", "ui_c", "ui_d", "ui_e", "ui_f", "led_bankptn"], str(names))
# release the bank's trig: stock FUN_4007b434 must see the mask empty and clean up
log.clear()
call(uc, TRIG_RELEASE, 2, 0)
st = state(uc)
check("release: mask empty, disarmed, trig handlers + LED callback unregistered",
      st["mask"] == 0 and st["armed"] == 0 and st["keylist"] == 0 and st["cblist"] == 0, str(st))
check("release: LED callback fired for the cleanup", any(nm == "cb_fire" for nm, _ in log), str(log))

# ---------------- toggle ON: phase 0, [BANK] held ----------------
print("toggle ON: bank trig with [BANK] held")
uc, log, st, texts = press("patched", 5, flag=1, bank_up=False)
sel = [a for nm, a in log if nm == "PATTERN_SELECT"]
check("pattern request (bank 5, pattern 0)", len(sel) == 1 and sel[0][:2] == [5, 0], str(sel))
check("window stays open while [BANK] is held (stock gesture)", st["win"] == 0x1111 and st["win_en"] == 0, str(st))
check("phase 2, mask = bit 5, not armed", st["phase"] == 2 and st["mask"] == 1 << 5 and st["armed"] == 0, str(st))
call(uc, TRIG_RELEASE, 5, 0)
st = state(uc)
check("trig release: mask empty, nothing torn down yet", st["mask"] == 0 and st["keylist"] == KEYNODE and st["win"] == 0x1111, str(st))
log.clear()
call(uc, BANK_RELEASE)
st = state(uc)
check("[BANK] release: window closed through its callback, handlers unregistered",
      st["win"] == 0 and st["keylist"] == 0 and st["cblist"] == 0 and st["armed"] == 0, str(st))
# a second pattern while [BANK] is held and the bank trig is up: stock select path
uc, log, st, _ = press("patched", 5, flag=1, bank_up=False)
call(uc, TRIG_RELEASE, 5, 0)
log.clear()
call(uc, TRIG_PRESS, 9, 1)
st = state(uc)
sel = [a for nm, a in log if nm == "PATTERN_SELECT"]
check("then trig 10: plain (bank 5, pattern 9) select, mask = bit 9", sel and sel[0][:2] == [5, 9] and st["mask"] == 1 << 9, f"{sel} {st}")

# ---------------- toggle ON: bank edges ----------------
print("toggle ON: banks A and P")
for n in (0, 15):
    uc, log, st, _ = press("patched", n, flag=1, bank_up=True)
    sel = [a for nm, a in log if nm == "PATTERN_SELECT"]
    check(f"bank {n}: request ({n}, 0), mask = 1<<{n}", sel and sel[0][:2] == [n, 0] and st["mask"] == (1 << n) & 0xffff, f"{sel} {st}")
    call(uc, TRIG_RELEASE, n, 0)
    check(f"bank {n}: release cleans up", state(uc)["mask"] == 0 and state(uc)["keylist"] == 0)

# ---------------- toggle ON: chaining from the held bank trig ----------------
print("toggle ON: hold the bank trig, press another trig")
uc, log, st, _ = press("patched", 2, flag=1, bank_up=True)
log.clear()
call(uc, TRIG_PRESS, 6, 1)
st = state(uc)
check("goes down the stock chain path (mask non-empty), no new select",
      any(nm == "PATTERN_CHAIN" for nm, _ in log) and not any(nm == "PATTERN_SELECT" for nm, _ in log)
      and st["mask"] == (1 << 2) | (1 << 6), f"{log} {st}")

# ---------------- toggle ON: the other phases and the unavailable bank are stock ----------------
print("toggle ON: untouched paths")
same = True
for kw, n in ((dict(flag=1, bank_up=True, phase=1, bank=3, mask=0), 7),
              (dict(flag=1, bank_up=True, phase=2, bank=3, mask=0x10), 9),
              (dict(flag=1, bank_up=True, phase=0, bank=0, mask=0, unavailable=4), 4)):
    _, ls, ss, ts = press("stock", n, **{**kw, "flag": 0})
    _, lp, sp_, tp = press("patched", n, **kw)
    same = same and ls == lp and ss == sp_ and ts == tp
check("phase 1, phase 2 and BANK UNAVAILABLE: identical to stock", same)
_, lp, sp_, _ = press("patched", 4, flag=1, bank_up=True, unavailable=4)
check("unavailable bank: message only, still phase 0, no request",
      [nm for nm, _ in lp] == ["BANK_UNAVAILABLE_MSG"] and sp_["phase"] == 0 and sp_["bank"] == 0, str(lp))

# ---------------- toggle ON: stale held-key bit from an earlier session ----------------
print("toggle ON: stale held-key bit (stock quirk) must not turn the pick into a chain")
uc, log, st, _ = press("patched", 5, flag=1, bank_up=True, mask=0x0004)
sel = [a for nm, a in log if nm == "PATTERN_SELECT"]
check("select, not chain: one (5, 0) request", len(sel) == 1 and sel[0][:2] == [5, 0]
      and not any(nm == "PATTERN_CHAIN" for nm, _ in log), f"{log}")
check("mask = only the bank's trig", st["mask"] == 1 << 5, str(st))
call(uc, TRIG_RELEASE, 5, 0)
st = state(uc)
check("release cleans up (mask empty, handlers unregistered)", st["mask"] == 0 and st["keylist"] == 0, str(st))

# ---------------- flag word holding junk (stale ANDY content) ----------------
print("flag word junk: anything but 1 is OFF")
for junk in (2, 0xffffffff, 0x80000000):
    uc, log, st, tp = press("patched", 2, flag=junk, bank_up=True)
    check(f"flag={junk:#x}: stock path (phase 1, no request)", st["phase"] == 1 and not any(nm == "PATTERN_SELECT" for nm, _ in log), str(st))
    uc, _ = mk("patched")
    w32(uc, F_FLAG, junk)
    call(uc, NM["get_autoptn"])
    check(f"flag={junk:#x}: getter shows unchecked", uc.reg_read(UC_M68K_REG_D0) == 0x400b5e8e)
    w32(uc, SH_FLAG, junk)
    call(uc, NM["set_autoptn"], 1, 1)
    check(f"flag={junk:#x}: one press -> exactly 1 in both copies", r32(uc, F_FLAG) == 1 and r32(uc, SH_FLAG) == 1)

# ---------------- through the REAL key dispatcher ----------------
print("real key dispatcher + per-key table rebuild")
DISPATCH, REBUILD = 0x40031734, 0x4003125c
BANK_PRESS = 0x4007af80
KPRESS, KREL, KSTATE = 0x46c7d8de, 0x46c7d8e2, 0x46c7d8ee     # per-key tables, stride 0x18
BASENODE, BASETBL = 0x41080000, 0x41080100                     # synthetic "normal trig" handler node
NORMAL_PRESS, NORMAL_REL = 0x41090000, 0x41090010


def mk_dispatch(which, flag):
    """Idle unit with a normal trig-handler node registered and the real rebuild run."""
    uc, log = mk(which)
    uc.mem_write(REBUILD, IMGS[which][REBUILD - BASE:REBUILD - BASE + 2])   # un-stub: run it for real
    del_stub = {REBUILD}
    for a, nm in ((NORMAL_PRESS, "NORMAL_PRESS"), (NORMAL_REL, "NORMAL_REL")):
        uc.mem_write(a, b"\x4e\x75")

    def spy(uc, addr, size, user):
        if addr in (NORMAL_PRESS, NORMAL_REL, TRIG_PRESS, TRIG_RELEASE):
            sp = uc.reg_read(UC_M68K_REG_A7)
            log.append(({NORMAL_PRESS: "NORMAL_PRESS", NORMAL_REL: "NORMAL_REL", TRIG_PRESS: "bank_press",
                         TRIG_RELEASE: "bank_release"}[addr], [r32(uc, sp + 4), r32(uc, sp + 8)]))
        elif addr == REBUILD:
            log.append(("keymap_rebuild", []))
    uc.hook_add(UC_HOOK_CODE, spy)
    w32(uc, BASENODE, 0); w32(uc, BASENODE + 4, BASETBL); w32(uc, BASENODE + 8, 0); w32(uc, BASENODE + 12, 0); w32(uc, BASENODE + 16, 0xffffffff)
    a = BASETBL
    for k in range(16):
        uc.mem_write(a, bytes([k, 0]) + NORMAL_PRESS.to_bytes(4, "big") + NORMAL_REL.to_bytes(4, "big") + b"\0" * 16)
        a += 0x1a
    uc.mem_write(a, b"\xff")
    w32(uc, F_FLAG, flag)
    w32(uc, PHASE, 0); w32(uc, BANK, 0); w32(uc, ARMED, 0); w16(uc, MASK, 0); w32(uc, TOGGLE, 0)
    w32(uc, WIN, 0); w32(uc, WIN_CB, 0); w32(uc, WIN_EN, 0)
    w32(uc, KEYLIST, BASENODE); w32(uc, CBLIST, 0)
    call(uc, REBUILD)
    return uc, log


def keymap(uc, k):
    return r32(uc, KPRESS + k * 0x18), r32(uc, KREL + k * 0x18), r32(uc, KSTATE + k * 0x18)


def nodes(uc):
    out, n = [], r32(uc, KEYLIST)
    while n:
        out.append(n); n = r32(uc, n)
    return out


def names(log, *only):
    return [nm for nm, _ in log if not only or nm in only]


for n in (2, 0, 15):
    uc, log = mk_dispatch("patched", 1)
    call(uc, BANK_PRESS); call(uc, BANK_RELEASE)              # [BANK] tap
    check(f"trig {n}: after the [BANK] tap the trig keys belong to the bank handler",
          keymap(uc, n)[:2] == (TRIG_PRESS, TRIG_RELEASE) and nodes(uc) == [BASENODE, KEYNODE], str(nodes(uc)))
    log.clear()
    call(uc, DISPATCH, n, 1)                                  # press the bank's trig
    sel = [a for nm, a in log if nm == "PATTERN_SELECT"]
    st = state(uc)
    # the bank handler is entered twice: by the dispatcher, then by the hook's synthetic trig-1 press
    check(f"trig {n}: dispatcher -> bank handler (+ synthetic press) -> one ({n}, 0) request, phase 2, mask = 1<<{n}, window closed",
          names(log, "bank_press", "NORMAL_PRESS") == ["bank_press", "bank_press"] and len(sel) == 1 and sel[0][:2] == [n, 0]
          and st["phase"] == 2 and st["mask"] == (1 << n) & 0xffff and st["win"] == 0, f"{names(log)} {st}")
    check(f"trig {n}: release handler still the bank's, key state 1 (held)",
          keymap(uc, n) == (TRIG_PRESS, TRIG_RELEASE, 1), str([hex(x) for x in keymap(uc, n)]))
    log.clear()
    call(uc, DISPATCH, n, 0)                                  # release it
    st = state(uc)
    check(f"trig {n}: release routed to FUN_4007b434, cleanup done, back to the normal handler",
          "bank_release" in names(log) and st["mask"] == 0 and st["armed"] == 0 and nodes(uc) == [BASENODE]
          and keymap(uc, n) == (NORMAL_PRESS, NORMAL_REL, 0), f"{names(log)} {st} {[hex(x) for x in keymap(uc, n)]}")
    log.clear()
    call(uc, DISPATCH, n, 1); call(uc, DISPATCH, n, 0)
    check(f"trig {n}: a later press/release is a normal trig again", names(log) == ["NORMAL_PRESS", "NORMAL_REL"], str(names(log)))

# the stale-bit gesture that stock gets wrong: hold the bank trig across a [BANK] re-press
uc, log = mk_dispatch("patched", 1)
call(uc, BANK_PRESS); call(uc, BANK_RELEASE); call(uc, DISPATCH, 2, 1)
call(uc, BANK_PRESS)                                          # [BANK] again while trig 2 is held
call(uc, DISPATCH, 2, 0); call(uc, BANK_RELEASE)
check("stale gesture: bit 2 left behind by the swallowed release (stock quirk reproduced)", state(uc)["mask"] == 1 << 2, str(state(uc)))
log.clear()
call(uc, BANK_PRESS); call(uc, BANK_RELEASE); call(uc, DISPATCH, 5, 1)
sel = [a for nm, a in log if nm == "PATTERN_SELECT"]
check("next session still selects (5, 0), no chain", len(sel) == 1 and sel[0][:2] == [5, 0] and "PATTERN_CHAIN" not in names(log), str(names(log)))
call(uc, DISPATCH, 5, 0)
check("and its release cleans up", state(uc)["mask"] == 0 and nodes(uc) == [BASENODE], str(state(uc)))

# [BANK] held, both release orders
for order in ("trig first", "[BANK] first"):
    uc, log = mk_dispatch("patched", 1)
    call(uc, BANK_PRESS); log.clear()
    call(uc, DISPATCH, 2, 1)
    sel = [a for nm, a in log if nm == "PATTERN_SELECT"]
    st = state(uc)
    check(f"[BANK] held, {order}: (2, 0) requested, window still up", len(sel) == 1 and sel[0][:2] == [2, 0] and st["win"] == 0x1111, str(st))
    if order == "trig first":
        call(uc, DISPATCH, 2, 0); call(uc, BANK_RELEASE)
    else:
        call(uc, BANK_RELEASE); call(uc, DISPATCH, 2, 0)
    st = state(uc)
    check(f"[BANK] held, {order}: ends closed, clean, normal handler back",
          st["win"] == 0 and st["mask"] == 0 and nodes(uc) == [BASENODE] and keymap(uc, 2) == (NORMAL_PRESS, NORMAL_REL, 0), f"{st} {[hex(x) for x in keymap(uc, 2)]}")

# chain from the held bank trig, then the countdown expiring before the release
uc, log = mk_dispatch("patched", 1)
call(uc, BANK_PRESS); call(uc, BANK_RELEASE); call(uc, DISPATCH, 2, 1); log.clear()
call(uc, DISPATCH, 6, 1)
check("hold bank trig, press trig 7: chain path", "PATTERN_CHAIN" in names(log) and "PATTERN_SELECT" not in names(log), str(names(log)))
call(uc, DISPATCH, 6, 0); call(uc, DISPATCH, 2, 0)
check("both released: clean", state(uc)["mask"] == 0 and nodes(uc) == [BASENODE], str(state(uc)))
uc, log = mk_dispatch("patched", 1)
call(uc, BANK_PRESS); call(uc, BANK_RELEASE); call(uc, DISPATCH, 2, 1); log.clear()
w32(uc, 0x460d1e50, 1); w32(uc, 0x460d1e54, 1)
call(uc, 0x40056ab8)                                          # countdown tick reaches zero
st = state(uc)
check("countdown expiry with the window already closed: no callback, state untouched",
      st["phase"] == 2 and st["mask"] == 1 << 2 and nodes(uc) == [BASENODE, KEYNODE], f"{names(log)} {st}")
call(uc, DISPATCH, 2, 0)
check("then the release cleans up", state(uc)["mask"] == 0 and nodes(uc) == [BASENODE], str(state(uc)))

# stock, toggle off, through the dispatcher: identical to the stock image
for which in ("stock", "patched"):
    uc, log = mk_dispatch(which, 0)
    call(uc, BANK_PRESS); call(uc, BANK_RELEASE); call(uc, DISPATCH, 2, 1); call(uc, DISPATCH, 2, 0)
    call(uc, DISPATCH, 9, 1); call(uc, DISPATCH, 9, 0)
    globals()[f"_{which}"] = (names(log), state(uc), nodes(uc), keymap(uc, 2), keymap(uc, 9))
check("toggle OFF through the dispatcher: stock and patched identical", _stock == _patched, f"{_stock}\n{_patched}")

# ---------------- menu ----------------
print("menu")
for flag, want in ((0, 0x400b5e8e), (1, 0x400b5e90)):
    uc, _ = mk("patched")
    w32(uc, F_FLAG, flag)
    call(uc, NM["get_autoptn"])
    check(f"getter flag={flag}", uc.reg_read(UC_M68K_REG_D0) == want, hex(uc.reg_read(UC_M68K_REG_D0)))
uc, _ = mk("patched")
w32(uc, F_FLAG, 0); w32(uc, SH_FLAG, 0)
call(uc, NM["set_autoptn"], 1, 1)
check("setter 0 -> 1 in runtime and battery shadow", r32(uc, F_FLAG) == 1 and r32(uc, SH_FLAG) == 1)
call(uc, NM["set_autoptn"], 1, 1)
check("setter 1 -> 0 in both", r32(uc, F_FLAG) == 0 and r32(uc, SH_FLAG) == 0)
call(uc, NM["set_autoptn"], 0xffffffff, 0)
check("setter -1 toggles too", r32(uc, F_FLAG) == 1 and r32(uc, SH_FLAG) == 1)
call(uc, NM["set_autoptn"], 0xffffffff, 0)
check("setter -1 back to 0", r32(uc, F_FLAG) == 0 and r32(uc, SH_FLAG) == 0)

print()
if FAILS:
    sys.exit(f"{len(FAILS)} FAILED: {FAILS}")
print(f"emu_autoptn: ALL GREEN on {IMG_PATH}")
