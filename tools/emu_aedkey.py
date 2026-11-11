#!/usr/bin/env python3
"""emu_aedkey.py -- prove patch_aedkey on the BUILT image (default out/mainos_all.bin).

For each case: start at the hooked key handler, stub the publisher 0x4006de34 (record its args),
stop where the stock code would go next, and assert:
  * AED closed -> publishes exactly what the firmware's own track-select publish (0x40083c64) does
    for the same bank/part/track -- run on the same image as the reference -- then opens;
  * AED open   -> no publish, stock close / stock flow;
  * stack delta matches the stock flow, every register is preserved.
And for the part-change sites (0x4006214e pattern change, 0x40062248 part change, OCTAMAX_2i):
  * AED open   -> publishes what track select would for the NEW part, then calls 0x4002e5ac
    returning to the handler;
  * AED closed -> no publish, straight into 0x4002e5ac.
"""
import pathlib, struct, sys
from unicorn import *
from unicorn.m68k_const import *

IMG_PATH = sys.argv[1] if len(sys.argv) > 1 else "out/mainos_all.bin"
IMG = pathlib.Path(IMG_PATH).read_bytes()
C = sys.modules["unicorn.m68k_const"]
R = {f"d{i}": getattr(C, f"UC_M68K_REG_D{i}") for i in range(8)}
R.update({f"a{i}": getattr(C, f"UC_M68K_REG_A{i}") for i in range(7)})
SP = UC_M68K_REG_A7
SENT = {k: 0x5e000000 + i * 0x1111 for i, k in enumerate(sorted(R))}

PUBLISH, OPEN, CLOSE, PAGEOK = 0x4006de34, 0x4006e160, 0x4006dd18, 0x4006db58
TOGGLE, SLICES, SLICES_RESUME = 0x4006e274, 0x4006e250, 0x4006e258
PART_SITES, PART_NEXT = (0x4006214e, 0x40062248), 0x4002e5ac
AEDOPEN, BANKPTR, G_PART, G_TRACK = 0x460e5e4c, 0x46c82456, 0x100b14cf, 0x100b14cc
BANK = 0x41100000
FAILS = []


def w32(uc, a, v):
    uc.mem_write(a, struct.pack(">I", v & 0xffffffff))


def r32(uc, a):
    return struct.unpack(">I", uc.mem_read(a, 4))[0]


def mk(part, track, mtype, slots, aed_open):
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    uc.mem_map(0x40000000, 0x400000)
    uc.mem_map(0x41000000, 0x200000)
    uc.mem_map(0x46000000, 0x200000)
    uc.mem_map(0x46c00000, 0x100000)
    uc.mem_map(0x10000000, 0x200000)
    uc.mem_write(0x40000400, IMG)
    w32(uc, BANKPTR, BANK)
    uc.mem_write(G_PART, bytes([part]))
    uc.mem_write(G_TRACK, bytes([track]))
    # the same arithmetic the firmware uses: type @ +0x8eda2 + part*6322 + track,
    # slots @ +0x8f04a + part*6322 + track*5 + type
    uc.mem_write(BANK + 0x8eda2 + part * 6322 + track, bytes([mtype & 0xff]))
    for t, s in enumerate(slots):
        uc.mem_write(BANK + 0x8f04a + part * 6322 + track * 5 + t, bytes([s]))
    w32(uc, AEDOPEN, aed_open)
    for k, v in SENT.items():
        uc.reg_write(R[k], v)
    return uc


def run(uc, start, stops, sp0, pageok=1):
    uc.reg_write(SP, sp0)
    st = {"pub": [], "page": []}

    def h(uc, addr, size, _):
        sp = uc.reg_read(SP)
        if addr == PUBLISH:
            st["pub"].append((r32(uc, sp + 4), r32(uc, sp + 8)))
            ret = r32(uc, sp)
            uc.reg_write(SP, sp + 4)
            uc.reg_write(UC_M68K_REG_PC, ret)
        elif addr == PAGEOK and pageok is not None:
            st["page"].append(r32(uc, sp + 4))
            ret = r32(uc, sp)
            uc.reg_write(R["d0"], pageok)
            uc.reg_write(SP, sp + 4)
            uc.reg_write(UC_M68K_REG_PC, ret)
        elif addr in stops:
            st["at"] = addr
            st["sp"] = sp
            st["regs"] = {k: uc.reg_read(R[k]) for k in R}
            uc.emu_stop()
    uc.hook_add(UC_HOOK_CODE, h)
    try:
        uc.emu_start(start, 0, count=5000)
    except UcError as e:
        st["err"] = str(e)
    return st


def reference(part, track, mtype, slots):
    """What the firmware's own track-select publish hands the setter for this state."""
    uc = mk(part, track, mtype, slots, 0)
    st = run(uc, 0x40083c64, {0x40083cac}, 0x41010000)
    assert st["pub"], f"reference run did not reach the publisher: {st.get('err')}"
    return st["pub"][0]


def check(name, p):
    print(("PASS " if not p else "FAIL ") + name)
    for x in p:
        print("      -", x)
    if p:
        FAILS.append(name)


def kept(st, keep=None):
    keep = keep or list(R)
    return [f"{k} = {st['regs'][k]:#x}, expected {SENT[k]:#x}" for k in keep if st["regs"][k] != SENT[k]]


def case_toggle(name, part, track, mtype, slots, aed_open):
    uc = mk(part, track, mtype, slots, aed_open)
    sp0 = 0x41010000
    w32(uc, sp0, 0x40001234)                           # return address into the key dispatcher
    st = run(uc, TOGGLE, {OPEN, CLOSE}, sp0)
    p = []
    if "err" in st or "at" not in st:
        return check(name, [f"did not reach open/close: {st.get('err')}"])
    if aed_open:
        if st["at"] != CLOSE:
            p.append(f"went to {st['at']:#x}, expected CLOSE")
        if st["pub"]:
            p.append(f"published {st['pub']} while closing")
    else:
        if st["at"] != OPEN:
            p.append(f"went to {st['at']:#x}, expected OPEN")
        ref = reference(part, track, mtype, slots)
        if st["pub"] != [ref]:
            p.append(f"published {st['pub']}, the firmware's track select publishes {ref}")
    if st["sp"] != sp0:
        p.append(f"sp {st['sp']:#x}, expected {sp0:#x} (stock branches, no frame)")
    p += kept(st)
    check(name, p)


def case_slices(name, part, track, mtype, slots, aed_open):
    uc = mk(part, track, mtype, slots, aed_open)
    sp0 = 0x41010000
    w32(uc, sp0, 0x40001234)
    st = run(uc, SLICES, {SLICES_RESUME}, sp0)
    p = []
    if "err" in st or st.get("at") != SLICES_RESUME:
        return check(name, [f"did not resume at {SLICES_RESUME:#x}: {st.get('err')}"])
    if st["page"] != [1]:
        p.append(f"PAGEOK args {st['page']}, expected [1]")
    if st["sp"] != sp0 - 4:
        p.append(f"sp {st['sp']:#x}, expected {sp0 - 4:#x} (pea 1 still stacked, as stock)")
    want = [] if aed_open else [reference(part, track, mtype, slots)]
    if st["pub"] != want:
        p.append(f"published {st['pub']}, expected {want}")
    if r32(uc, sp0 - 4) != 1:
        p.append("the pea 1 argument is not on the stack")
    p += kept(st, [k for k in R if k != "d0"])          # d0 = PAGEOK's result, by design
    if st["regs"]["d0"] != 1:
        p.append(f"d0 = {st['regs']['d0']:#x}, expected PAGEOK's result 1")
    check(name, p)


def case_part(name, site, part, track, mtype, slots, aed_open):
    uc = mk(part, track, mtype, slots, aed_open)
    sp0 = 0x41010000
    st = run(uc, site, {PART_NEXT}, sp0)
    p = []
    if "err" in st or st.get("at") != PART_NEXT:
        return check(name, [f"did not reach {PART_NEXT:#x}: {st.get('err')}"])
    if st["sp"] != sp0 - 4 or r32(uc, sp0 - 4) != site + 6:
        p.append(f"sp {st['sp']:#x} / ret {r32(uc, st['sp']):#x}, expected a call returning to {site + 6:#x}")
    want = [reference(part, track, mtype, slots)] if aed_open else []
    if st["pub"] != want:
        p.append(f"published {st['pub']}, expected {want}")
    p += kept(st)
    check(name, p)


# the HW case: bank part 0, track 5 (index 4), static, slot 28 (index 27) after the copy
case_toggle("AED key, closed, T5 static slot 28: publishes (0, 27) like track select, then opens",
            0, 4, 0, [27, 0, 0, 0, 0x84], 0)
case_toggle("AED key, open: closes, publishes nothing", 0, 4, 0, [27, 0, 0, 0, 0x84], 0x46100000)
case_toggle("AED key, closed, part 3 T8 flex slot 7", 3, 7, 1, [0, 6, 0, 0, 0x87], 0)
case_toggle("AED key, closed, high static slot 200 (dual-256)", 1, 2, 0, [199, 0, 0, 0, 0x82], 0)
case_toggle("AED key, closed, thru machine (type 2): same as stock", 0, 1, 2, [3, 4, 0, 0, 0x81], 0)
case_slices("slices shortcut, closed: publishes first, then the stock page check", 0, 4, 0, [27, 0, 0, 0, 0x84], 0)
case_slices("slices shortcut, open: no publish, stock flow", 0, 4, 0, [27, 0, 0, 0, 0x84], 0x46100000)
for site, what in zip(PART_SITES, ("pattern change", "part change")):
    case_part(f"{what}, AED open, part 2 T3 static slot 41: republishes (0, 40)", site,
              2, 2, 0, [40, 0, 0, 0, 0x83], 0x46100000)
    case_part(f"{what}, AED open, high static slot 200 (dual-256)", site, 1, 6, 0, [199, 0, 0, 0, 0x87], 0x46100000)
    case_part(f"{what}, AED open, flex slot 12", site, 3, 0, 1, [0, 11, 0, 0, 0x80], 0x46100000)
    case_part(f"{what}, AED closed: no publish, stock call", site, 2, 2, 0, [40, 0, 0, 0, 0x83], 0)
print("\nALL GREEN" if not FAILS else "FAILED: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
