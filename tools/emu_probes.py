#!/usr/bin/env python3
"""emu_probes.py -- GATE for diagnostic (probe) builds. Runs every installed hook in Unicorn and checks
the three things a pure observer must guarantee: it lands on the right instruction, it leaves the stack
exactly as the replaced code would have, and it does not corrupt registers it promised to preserve.

This gate did not exist when P34 was flashed; P34 hung the unit and could not be bisected because four
hooks and a relocated code cave shipped in one build. Any probe build must pass this BEFORE packaging.

    python3 tools/emu_probes.py [--img out/mainos_diag_loaderr2.bin]
"""
import pathlib, sys
from unicorn import *
from unicorn.m68k_const import *

BASE = 0x40000400
_args = sys.argv[1:]
if "--img" in _args:
    IMG = _args[_args.index("--img") + 1]
    _rest = [a for a in _args if a != "--img" and a != IMG]
else:
    _pos = [a for a in _args if not a.startswith("-")]
    if len(_pos) > 1:
        sys.exit(f"REFUSING: more than one image argument: {_pos}")
    if not _pos:
        sys.exit("REFUSING: name the image to gate, e.g. "
                 "python3 tools/emu_probes.py out/mainos_diag_loaderr4.bin")
    IMG = _pos[0]
    _rest = [a for a in _args if a.startswith("-")]
if _rest:
    sys.exit(f"REFUSING: unrecognized arguments {_rest} -- a silently ignored arg means you gated the WRONG image.")
IMGB = pathlib.Path(IMG).read_bytes()
SP0 = 0x0000c000
RET = 0x00009000        # mapped landing pad (an rts must return somewhere decodable)


def run(entry, stack, regs=None, stop_at=(), maxins=4000, mem_pre=()):
    mu = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    for a, s in [(0x40000000, 0x2000000), (0x10000000, 0x400000),
                 (0x46000000, 0x1000000), (0x00008000, 0x8000)]:
        mu.mem_map(a, s)
    mu.mem_write(BASE, IMGB)
    mu.mem_write(RET, b"\x4e\x71" * 16)          # nop sled, so a real rts does not fetch unmapped
    for i, v in enumerate(stack):
        mu.mem_write(SP0 + i * 4, v.to_bytes(4, "big"))
    mu.reg_write(UC_M68K_REG_A7, SP0)
    for addr, val in mem_pre:
        mu.mem_write(addr, val.to_bytes(4, "big"))
    for r, v in (regs or {}).items():
        mu.reg_write(r, v)
    # Stopping ON the landing address is not enough: P35 landed correctly on 0x4009937c and still bricked
    # the unit, because the hook had clobbered the first half of THAT instruction and the illegal opcode
    # sat two bytes further in. So keep executing a few instructions PAST the landing and require that the
    # instruction stream still decodes.
    hit = {"pc": None, "sp": None, "left": -1, "d0": None, "d2": None, "a0": None}

    def hk(mu, addr, size, ud):
        if hit["pc"] is None and addr in stop_at:
            hit["pc"] = addr
            hit["sp"] = mu.reg_read(UC_M68K_REG_A7)   # capture SP AT the landing, before we run on
            hit["d0"] = mu.reg_read(UC_M68K_REG_D0)   # live-out values a replay must reproduce
            hit["d2"] = mu.reg_read(UC_M68K_REG_D2)
            hit["a0"] = mu.reg_read(UC_M68K_REG_A0)
            hit["left"] = 8                 # execute 8 more instructions past the landing
            return
        if hit["left"] > 0:
            hit["left"] -= 1
            if hit["left"] == 0:
                mu.emu_stop()
    mu.hook_add(UC_HOOK_CODE, hk)
    err = None
    try:
        mu.emu_start(entry, 0, count=maxins)
    except UcError as e:
        err = e
    # The post-landing instructions run with SYNTHETIC registers, so a DATA access through fp/a2 can
    # legitimately hit unmapped memory -- that says nothing about the probe. What must never happen is
    # a bad instruction stream: an illegal opcode or a fetch from nowhere (exactly the P35 brick). So
    # tolerate read/write-unmapped once the landing has been reached; never tolerate fetch or exception.
    if err is not None and hit["pc"] is not None and \
            err.errno in (UC_ERR_READ_UNMAPPED, UC_ERR_WRITE_UNMAPPED):
        err = None
    return hit, (hit["sp"] if hit["sp"] is not None else mu.reg_read(UC_M68K_REG_A7)), mu, err


def check(name, entry, stack, regs, expect_pc, expect_sp_delta, stop_at, mem_expect=(), mem_pre=(),
          reg_expect=()):
    hit, sp, mu, err = run(entry, stack, regs, stop_at, mem_pre=mem_pre)
    pc = hit["pc"]
    d = sp - SP0
    # the stack is read right after landing, before the post-landing instructions move it again

    ok = (pc == expect_pc) and (d == expect_sp_delta) and err is None
    # A probe that lands correctly but records nothing (or records at the wrong offset) is a wasted
    # flash. Assert the bytes it was supposed to write into the PROBE block.
    bad = []
    for addr, want in mem_expect:
        got = int.from_bytes(mu.mem_read(addr, 4), "big")
        if got != want:
            bad.append(f"[0x{addr:08x}]=0x{got:08x} want 0x{want:08x}")
            ok = False
    # a replay must also reproduce the values the replaced instructions left live in registers
    for rname, want in reg_expect:
        got = hit[rname]
        if got is None or (got - (1 << 32) if got >> 31 else got) != want:
            bad.append(f"{rname}={got if got is None else hex(got)} want {want}")
            ok = False
    print(f"  [{'OK ' if ok else 'FAIL'}] {name:28} landed={pc and hex(pc)} (want {hex(expect_pc)})  "
          f"sp{d:+d} (want {expect_sp_delta:+d})"
          f"{'  ERR=' + str(err) if err else ''}{'  BAD ' + '; '.join(bad) if bad else ''}")
    return ok


PROBE = 0x40ab65e0          # the diagnostic block (SETTINGS-B, dumped to project.256 on SAVE)
MAGIC = 0x10ade111
SCRATCH = 0x0000a000        # a mapped address probes can be handed as a non-NULL pointer


def installed(va):
    """Return the jmp target if a probe hook sits at va, else None. Lets one gate serve every diag
    build: each suite runs only if its hooks are actually present, so re-gating an OLD image still
    exercises (and can still fail) the probes that image claims to have."""
    o = va - BASE
    if IMGB[o:o + 2] != b"\x4e\xf9":
        return None
    return int.from_bytes(IMGB[o + 2:o + 6], "big")


def main():
    print(f"img={IMG}")
    allok = True
    ran = []
    # ---- paths that must behave exactly as stock whether or not they are hooked -------------------
    allok &= check("C ok-path  (d2=+5)", 0x40022be0, [RET], {UC_M68K_REG_D2: 5},
                   0x40022bfc, 0, (0x40022bfc, 0x40022bea, 0x40080844))
    allok &= check("C err-path (d2=-16)", 0x40022be0, [RET], {UC_M68K_REG_D2: 0xfffffff0},
                   0x40080844, -4, (0x40022bfc, 0x40022bea, 0x40080844))

    # ---- B: 0x40022b50. arg >= 0 -> 0x40022b6e (no record) ; arg < 0 -> 0x40022b56 (record) -------
    if installed(0x40022b50):
        ran.append("B")
        CNT_B, ARR_B = PROBE + 4, PROBE + 0x40
        allok &= check("B ok-path  (arg=+5)", 0x40022b50, [RET, 5], {}, 0x40022b6e, 0,
                       (0x40022b6e, 0x40022b56), [(CNT_B, 0)])
        allok &= check("B err-path (arg=-2)", 0x40022b50, [RET, 0xfffffffe], {UC_M68K_REG_A2: 0x46001234},
                       0x40022b56, 0, (0x40022b6e, 0x40022b56),
                       [(PROBE, MAGIC), (CNT_B, 1),
                        (ARR_B, 0xfffffffe), (ARR_B + 4, RET), (ARR_B + 8, 0x46001234)])

    # ---- S: sampleslice 0x40099374. sp@(4) is the TYPE, sp@(8) the SLOT. records only slot >= 136 --
    if installed(0x40099374):
        ran.append("S")
        CNT_S, ARR_S = PROBE + 8, PROBE + 0x80
        allok &= check("S slice low  (slot=57)", 0x40099374, [RET, 0, 57], {},
                       0x4009937c, -40, (0x4009937c,), [(CNT_S, 0)])
        allok &= check("S slice 129  (filtered)", 0x40099374, [RET, 0, 129], {},
                       0x4009937c, -40, (0x4009937c,), [(CNT_S, 0)])
        allok &= check("S slice high (slot=140)", 0x40099374, [RET, 0, 140], {},
                       0x4009937c, -40, (0x4009937c,),
                       [(CNT_S, 1), (ARR_S, 140), (ARR_S + 4, 0), (ARR_S + 8, RET)])

    # ---- N1/N2: the two direct `moveq #-2 ; rts` returns (loaderr4 only) --------------------------
    if installed(0x400148d4):
        ran.append("N1")
        CNT_N1, ARR_N1 = PROBE + 0xc, PROBE + 0xe0
        allok &= check("N1 NULL handle", 0x400148d4, [RET, 0], {},
                       0x400148f6, 0, (0x400148f6, 0x400148dc),
                       [(CNT_N1, 1), (ARR_N1, 0), (ARR_N1 + 4, RET)])
        allok &= check("N1 good id (*h=5)", 0x400148d4, [RET, SCRATCH], {},
                       0x400148dc, 0, (0x400148f6, 0x400148dc), [(CNT_N1, 0)], mem_pre=[(SCRATCH, 5)])
    if installed(0x4008fa68):
        ran.append("N2")
        CNT_N2, ARR_N2 = PROBE + 0x10, PROBE + 0x120
        allok &= check("N2 NULL path", 0x4008fa68, [RET, 0], {},
                       0x4008fa70, 0, (0x4008fa70, 0x4008fa74), [(CNT_N2, 1), (ARR_N2, RET)])
        allok &= check("N2 non-NULL path", 0x4008fa68, [RET, SCRATCH], {},
                       0x4008fa74, 0, (0x4008fa70, 0x4008fa74), [(CNT_N2, 0)])

    # ---- G1/G2: replace `jsr 0x40013db0` (strlen). sp@(0) = the string pointer at the hook site.
    #      The stub must record, still perform the call, and leave d0 = strlen(arg) and sp untouched.
    for tag, hook, cont, cnt_off, arr_off in (("G1", 0x40084a12, 0x40084a18, 0xc if False else 8, 0x80),
                                              ("G2", 0x40084ab8, 0x40084abe, 0xc, 0x140)):
        if not installed(hook):
            continue
        ran.append(tag)
        CNT, ARR = PROBE + cnt_off, PROBE + arr_off
        # "ab\0" at SCRATCH -> strlen 2, and the probe must copy the bytes verbatim
        allok &= check(f"{tag} non-empty ('ab')", hook, [SCRATCH], {UC_M68K_REG_A2: 0x46005678, UC_M68K_REG_A6: SP0},
                       cont, 0, (cont,),
                       [(PROBE, MAGIC), (CNT, 1), (ARR, SCRATCH), (ARR + 4, 0x46005678),
                        (ARR + 8, 0x61620000)],
                       mem_pre=[(SCRATCH, 0x61620000)])
        allok &= check(f"{tag} empty string", hook, [SCRATCH], {UC_M68K_REG_A2: 0x46005678, UC_M68K_REG_A6: SP0},
                       cont, 0, (cont,),
                       [(CNT, 1), (ARR, SCRATCH), (ARR + 8, 0)],
                       mem_pre=[(SCRATCH, 0)])
        # d0 must still be strlen(arg) when we land -- the whole point of a transparent probe
        hit, sp, mu, err = run(hook, [SCRATCH], {UC_M68K_REG_A6: SP0}, (cont,),
                               mem_pre=[(SCRATCH, 0x61620000)])
        d0 = mu.reg_read(UC_M68K_REG_D0)
        ok = (d0 == 2 and err is None)
        allok &= ok
        print(f"  [{'OK ' if ok else 'FAIL'}] {tag + ' strlen passthrough':28} d0={d0} (want 2)"
              f"{'  ERR=' + str(err) if err else ''}")

    # ---- E1..E4: the four `-2` exits of the loader state machine ---------------------------------
    CNT_E, ARR_E = PROBE + 8, PROBE + 0x80
    REC = 0x46005000                      # a mapped record to hand the probe
    RECBYTES = [(REC, 0x2E2E2F41), (REC + 4, 0x42430000)]     # "../AB" "C"
    FP = 0xc002                           # -470(fp) and -482(fp) both land 4-aligned and mapped
    for tag, hook, cont, site, sp_delta, regs, pre in (
            ("E1", 0x4008498c, 0x40084e70, 1, 0, {UC_M68K_REG_A2: REC}, RECBYTES),
            ("E2", 0x400849de, 0x400849ea, 2, -8, {UC_M68K_REG_A2: REC}, RECBYTES),
            ("E3", 0x40084a80, 0x40084a8a, 3, 0, {UC_M68K_REG_A6: FP},
             RECBYTES + [(FP - 470, REC)]),
            ("E4", 0x40084b20, 0x40084b2a, 4, 0, {UC_M68K_REG_A6: FP},
             RECBYTES + [(FP - 482, REC)])):
        if not installed(hook):
            continue
        ran.append(tag)
        # the replay must leave -2 in the register the replaced `moveq` targeted: d0 for E1/E2, d2 for E3/E4
        regname = "d0" if site <= 2 else "d2"
        allok &= check(f"{tag} -2 exit #{site}", hook, [RET], regs, cont, sp_delta, (cont,),
                       [(PROBE, MAGIC), (CNT_E, 1), (ARR_E, site), (ARR_E + 4, REC),
                        (ARR_E + 8, 0x2E2E2F41), (ARR_E + 12, 0x42430000)],
                       mem_pre=pre, reg_expect=[(regname, -2)])

    # ---- X: strlen, filtered to callers inside the loader. Replaces the four E probes, which were
    #      unhookable (each -2 site's second address is a branch target -- see tools/hookcheck.py).
    #      d0 and a0 are dead on entry, so the fast path saves nothing; the replay must still leave
    #      a0 = the argument and d0 = 0, exactly as `moveal sp@(4),a0 ; clrl d0` did.
    if installed(0x40013db0):
        ran.append("X")
        CNT_X, ARR_X = PROBE + 8, PROBE + 0x80
        SP_ = 0x0000a100
        PB = [(SP_, 0x2E2E2F79), (SP_ + 4, 0x2E616966)]        # "../y" ".aif"
        allok &= check("X caller in loader", 0x40013db0, [0x40084a18, SP_], {},
                       0x40013db6, 0, (0x40013db6,),
                       [(PROBE, MAGIC), (CNT_X, 1), (ARR_X, 0x40084a18), (ARR_X + 4, SP_),
                        (ARR_X + 8, 0x2E2E2F79), (ARR_X + 12, 0x2E616966)],
                       mem_pre=PB, reg_expect=[("d0", 0), ("a0", SP_)])
        allok &= check("X caller elsewhere", 0x40013db0, [0x40012345, SP_], {},
                       0x40013db6, 0, (0x40013db6,), [(CNT_X, 0)],
                       mem_pre=PB, reg_expect=[("d0", 0), ("a0", SP_)])
        allok &= check("X boundary lo-1", 0x40013db0, [0x400847fe, SP_], {},
                       0x40013db6, 0, (0x40013db6,), [(CNT_X, 0)], mem_pre=PB)
        allok &= check("X boundary hi", 0x40013db0, [0x40084c00, SP_], {},
                       0x40013db6, 0, (0x40013db6,), [(CNT_X, 0)], mem_pre=PB)

    # ---- L: bulk load-loop outcome. RUNS AT PROJECT LOAD -- a fault here hangs the boot. ---------
    if installed(0x400908ac):
        ran.append("L")
        CNT_L, ARR_L, CNT_LALL = PROBE + 0xc, PROBE + 0xa0, PROBE + 0x18
        PATH = 0x46006000
        PB = [(PATH, 0x2E2E2F78), (PATH + 4, 0x2E616966)]      # "../x" ".aif"
        # low slot -> filtered out, but the unfiltered counter must still tick
        allok &= check("L low slot (filtered)", 0x400908ac, [RET],
                       {UC_M68K_REG_D3: 57, UC_M68K_REG_D0: 1, UC_M68K_REG_A2: PATH},
                       0x400908d8, +8, (0x400908d8, 0x400908b2),
                       [(CNT_L, 0), (CNT_LALL, 1), (PROBE, MAGIC)], mem_pre=PB,
                       reg_expect=[("d2", 1)])
        # high slot, success -> recorded, and the >=0 branch must still be taken
        allok &= check("L high slot ok (140)", 0x400908ac, [RET],
                       {UC_M68K_REG_D3: 140, UC_M68K_REG_D0: 1, UC_M68K_REG_A2: PATH},
                       0x400908d8, +8, (0x400908d8, 0x400908b2),
                       [(CNT_L, 1), (CNT_LALL, 1), (ARR_L, 140), (ARR_L + 4, 1),
                        (ARR_L + 8, PATH), (ARR_L + 12, 0x2E2E2F78)], mem_pre=PB,
                       reg_expect=[("d2", 1)])
        # high slot, failure -> the negative branch must still be taken and d2 must carry the error
        allok &= check("L high slot err (-2)", 0x400908ac, [RET],
                       {UC_M68K_REG_D3: 140, UC_M68K_REG_D0: 0xfffffffe, UC_M68K_REG_A2: PATH},
                       0x400908b2, +8, (0x400908d8, 0x400908b2),
                       [(CNT_L, 1), (ARR_L + 4, 0xfffffffe)], mem_pre=PB,
                       reg_expect=[("d2", -2)])

    # ---- P / S1 / E: the .ot sidecar parser FUN_40089940(handle, type, slot) ---------------------
    SETB = 0x40a955e0
    HI = SETB + 15 * 0x448          # SET-B[15] = UI slot 144
    if installed(0x40089940):
        ran.append("P")
        CNT_P, ARR_P = PROBE + 0x1c, PROBE + 0x180
        allok &= check("P high slot (144)", 0x40089940, [RET, 0x1234, 0, 143], {},
                       0x40089948, -20, (0x40089948,),
                       [(PROBE, MAGIC), (CNT_P, 1), (ARR_P, 143), (ARR_P + 4, 0), (ARR_P + 8, 0x1234)])
        allok &= check("P low slot (filtered)", 0x40089940, [RET, 0x1234, 0, 57], {},
                       0x40089948, -20, (0x40089948,), [(CNT_P, 0), (PROBE + 0x20, 1)])
        # the UNFILTERED total must tick for a low slot too -- otherwise "cntPall == 0" on hardware
        # would prove nothing about whether the parser ran.
        allok &= check("P unfiltered total", 0x40089940, [RET, 0x1234, 0, 143], {},
                       0x40089948, -20, (0x40089948,), [(CNT_P, 1), (PROBE + 0x20, 1)])
    if installed(0x40070cd2):
        ran.append("AED")
        CNT_AED, ARR_AED, CNT_AEDALL = PROBE + 0x24, PROBE + 0x1e0, PROBE + 0x2c
        LOW = 0x100d5b30 + 5 * 0x448          # SET-A[5]
        HI = 0x40a955e0 + 15 * 0x448          # SET-B[15] = UI slot 144
        # d3 must end up holding the slice count -- it is what the drawing code goes on to use
        allok &= check("AED low slot, count=11", 0x40070cd2, [RET], {UC_M68K_REG_A3: LOW},
                       0x40070cdc, 0, (0x40070cdc,),
                       [(PROBE, MAGIC), (CNT_AED, 1), (CNT_AEDALL, 1),
                        (ARR_AED, LOW), (ARR_AED + 4, 11), (ARR_AED + 8, 0xcafe0001)],
                       mem_pre=[(LOW + 1092, 11), (LOW + 312, 0xcafe0001)])
        allok &= check("AED high slot, count=0", 0x40070cd2, [RET], {UC_M68K_REG_A3: HI},
                       0x40070cdc, 0, (0x40070cdc,),
                       [(CNT_AED, 1), (ARR_AED, HI), (ARR_AED + 4, 0)],
                       mem_pre=[(HI + 1092, 0)])

    if installed(0x40089d16):
        ran.append("S1")
        CNT_S1, ARR_S1 = PROBE + 0x10, PROBE + 0x230
        # the replay must leave a2 = d3 + 1092, exactly as `moveal d3,a2 ; lea a2@(1092),a2` did
        allok &= check("S1 slice loop done (hi)", 0x40089d16, [RET], {UC_M68K_REG_D3: HI},
                       0x40089d1c, 0, (0x40089d1c,), [(CNT_S1, 1), (ARR_S1, HI)])
        allok &= check("S1 low slot (filtered)", 0x40089d16, [RET], {UC_M68K_REG_D3: 0x100d5b30},
                       0x40089d1c, 0, (0x40089d1c,), [(CNT_S1, 0)])
    if installed(0x40089d7a):
        ran.append("E")
        CNT_E2, ARR_E2 = PROBE + 0x14, PROBE + 0x270
        # d0 is the parser's RETURN VALUE -- the probe must not disturb it
        allok &= check("E exit ok (d0=1)", 0x40089d7a, [RET],
                       {UC_M68K_REG_D0: 1, UC_M68K_REG_D3: HI},
                       0x40089d82, +20, (0x40089d82,),
                       [(CNT_E2, 1), (ARR_E2, 1), (ARR_E2 + 4, HI)], reg_expect=[("d0", 1)])
        allok &= check("E exit fail (d0=0)", 0x40089d7a, [RET],
                       {UC_M68K_REG_D0: 0, UC_M68K_REG_D3: HI},
                       0x40089d82, +20, (0x40089d82,),
                       [(CNT_E2, 1), (ARR_E2, 0), (ARR_E2 + 4, HI)], reg_expect=[("d0", 0)])
        allok &= check("E low slot (filtered)", 0x40089d7a, [RET],
                       {UC_M68K_REG_D0: 1, UC_M68K_REG_D3: 0x100d5b30},
                       0x40089d82, +20, (0x40089d82,), [(CNT_E2, 0)], reg_expect=[("d0", 1)])

    # ---- C: slice-fn decision point. @8 == 0 proceeds to 0x400993f2, anything else to 0x400993de -
    if installed(0x400993d8):
        ran.append("C")
        CNT_C, ARR_C = PROBE + 0x10, PROBE + 0x2f0
        ST = 0x46007000
        allok &= check("C high slot, @8=0", 0x400993d8, [RET],
                       {UC_M68K_REG_A4: 0, UC_M68K_REG_D7: 139, UC_M68K_REG_A0: ST},
                       0x400993f2, 0, (0x400993f2, 0x400993de),
                       [(CNT_C, 1), (ARR_C, 0), (ARR_C + 4, 139), (ARR_C + 8, 0),
                        (ARR_C + 12, 0x1234abcd)],
                       mem_pre=[(ST + 8, 0), (ST + 20, 0x1234abcd)])
        allok &= check("C high slot, @8=2", 0x400993d8, [RET],
                       {UC_M68K_REG_A4: 0, UC_M68K_REG_D7: 139, UC_M68K_REG_A0: ST},
                       0x400993de, 0, (0x400993f2, 0x400993de),
                       [(CNT_C, 1), (ARR_C + 8, 2)],
                       mem_pre=[(ST + 8, 2), (ST + 20, 0x1234abcd)])
        allok &= check("C FLEX type (filtered)", 0x400993d8, [RET],
                       {UC_M68K_REG_A4: 1, UC_M68K_REG_D7: 139, UC_M68K_REG_A0: ST},
                       0x400993de, 0, (0x400993f2, 0x400993de), [(CNT_C, 0)],
                       mem_pre=[(ST + 8, 2)])
        allok &= check("C low slot (filtered)", 0x400993d8, [RET],
                       {UC_M68K_REG_A4: 0, UC_M68K_REG_D7: 57, UC_M68K_REG_A0: ST},
                       0x400993f2, 0, (0x400993f2, 0x400993de), [(CNT_C, 0)],
                       mem_pre=[(ST + 8, 0)])

    # ---- A: AED has-content predicate. Z from the @8 load must survive for the `seq` at 0x4006db3e
    if installed(0x4006db38):
        ran.append("A")
        CNT_A, ARR_A = PROBE + 0x14, PROBE + 0x370
        ST, IDX_G, TYPE_G = 0x46007000, 0x46c8d19c, 0x46c8d1a0
        allok &= check("A high slot (139)", 0x4006db38, [RET], {UC_M68K_REG_A0: ST},
                       0x4006db3e, +8, (0x4006db3e,),
                       [(CNT_A, 1), (ARR_A, 139), (ARR_A + 4, 7), (ARR_A + 8, 0)],
                       mem_pre=[(ST + 8, 7), (IDX_G, 139), (TYPE_G, 0)])
        allok &= check("A low slot (filtered)", 0x4006db38, [RET], {UC_M68K_REG_A0: ST},
                       0x4006db3e, +8, (0x4006db3e,), [(CNT_A, 0)],
                       mem_pre=[(ST + 8, 7), (IDX_G, 57), (TYPE_G, 0)])

    print(f"\nsuites run: {', '.join(ran) if ran else 'NONE (no probe hooks found)'}")
    if not ran:
        allok = False
    print(("ALL GREEN -- every probe lands correctly, balances the stack, and records what it "
           "was supposed to record."
           if allok else ">>> A PROBE IS BROKEN -- DO NOT FLASH <<<"))
    sys.exit(0 if allok else 1)


if __name__ == "__main__":
    main()
