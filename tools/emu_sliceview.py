#!/usr/bin/env python3
"""
emu_sliceview.py -- Unicorn proof for the SLICE PLAYHEAD stubs, run against the BUILT image.

Loads out/mainos_sliceview.bin (override with argv[1]), executes each installed detour the
way the firmware would, and checks:

  render, flag OFF : replays `pea 0x400beafa`, resumes at 0x40044cf6, no register damage
  render, flag ON  : drops the 3 pushed blit args, clears POSTED, clears the grid area,
                     draws box+fill+marker+number with the right arguments, exits via
                     0x400453e2 with the caller's frame intact
  tick,  all paths : counts BLINKCTR always; posts sv_msg (event 78) to the UI queue only
                     when flag+view+modal allow and no post is outstanding; retries after
                     64 ticks; replays the displaced tstl and resumes at 0x40056c98
  menu             : getter returns the right glyph, setter toggles the flag

Draw/post firmware entries are replaced by `rts` and their stacked arguments recorded, so
the proof is about the stub's calls, not the primitives' pixels.
"""
import pathlib, struct, sys
from unicorn import *
from unicorn.m68k_const import *

IMG_PATH = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "out/mainos_sliceview.bin")
BASE = 0x40000400

F_FLAG   = 0x800000dc
BLINKCTR = 0x80006c68
POSTED   = 0x80006c6c
POSTTIME = 0x80006c70
VIEW     = 0x460d16f0
MODAL    = 0x460d1aec
UIQ      = 0x460d17ae
CURTRACK = 0x100b14cc
VOICES   = 0x800049d8

FILLRECT, VLINE, DRAWTEXT, DRAWFMT, POST = 0x40012254, 0x40011b94, 0x40012bd8, 0x40013904, 0x40000c3c
RENDER_SITE, RENDER_RESUME, ARM_EXIT = 0x40044cf0, 0x40044cf6, 0x400453e2
TICK_SITE, TICK_RESUME = 0x40056c92, 0x40056c98

SETTINGS_FAKE = 0x100d5b30          # any RAM address works; use the real STATIC base

IMG = IMG_PATH.read_bytes()

# symbol addresses out of the last assemble
NM = {}
import subprocess
for l in subprocess.run(["m68k-elf-nm", "out/patch_sliceview.elf"], capture_output=True,
                        text=True).stdout.splitlines():
    p = l.split()
    if len(p) == 3:
        NM[p[2]] = int(p[0], 16)


def mk():
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    uc.mem_map(0x40000000, 0x200000)
    uc.mem_write(BASE, IMG)
    uc.mem_map(0x80000000, 0x10000)
    uc.mem_map(0x10000000, 0x100000)     # CURTRACK + fake SETTINGS live in 0x100xxxxx
    uc.mem_map(0x46000000, 0x1100000)    # VIEW/MODAL/UIQ/dirty/0x46104ca8
    uc.mem_map(0x41000000, 0x20000)      # stack
    calls = []

    def hook(uc, addr, size, user):
        if addr in (FILLRECT, VLINE, DRAWTEXT, DRAWFMT, POST):
            sp = uc.reg_read(UC_M68K_REG_A7)
            args = [struct.unpack(">I", uc.mem_read(sp + 4 + i * 4, 4))[0] for i in range(10)]
            calls.append((addr, args))

    for fn in (FILLRECT, VLINE, DRAWTEXT, DRAWFMT, POST):
        uc.mem_write(fn, b"\x4e\x75")    # rts
    uc.hook_add(UC_HOOK_CODE, hook)
    return uc, calls


def w32(uc, a, v): uc.mem_write(a, struct.pack(">I", v & 0xFFFFFFFF))
def w8(uc, a, v): uc.mem_write(a, bytes([v & 0xFF]))
def r32(uc, a): return struct.unpack(">I", uc.mem_read(a, 4))[0]
def r8(uc, a): return uc.mem_read(a, 1)[0]


def run_to(uc, start, stops, count=20000):
    hit = {"pc": None}

    def stopper(uc, addr, size, user):
        if addr in stops:
            hit["pc"] = addr
            uc.emu_stop()
    uc.hook_add(UC_HOOK_CODE, stopper)
    try:
        uc.emu_start(start, 0, count=count)
    except UcError as e:
        if hit["pc"] is None:
            raise
    return hit["pc"]


FAILS = []


def check(name, cond, detail=""):
    tag = "ok " if cond else "FAIL"
    print(f"  {tag} {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def setup_voice(uc, track, active, slice_idx, pos, start, end, loop, settings=SETTINGS_FAKE):
    w8(uc, CURTRACK, track)
    v = VOICES + track * 0xA8
    w8(uc, v + 0, 0xFF if active else 0)
    w32(uc, v + 8, settings)
    w8(uc, v + 32, slice_idx & 0xFF)
    w32(uc, v + 68, pos)
    e = settings + 300 + (slice_idx + 1) * 12
    w32(uc, e + 0, start)
    w32(uc, e + 4, end)
    w32(uc, e + 8, loop)


# ---------------- render: flag OFF ----------------
print("render, flag OFF")
uc, calls = mk()
w32(uc, F_FLAG, 0)
sp0 = 0x41010000
uc.reg_write(UC_M68K_REG_A7, sp0 - 12)          # the 3 blit args are already pushed
uc.reg_write(UC_M68K_REG_D4, 0x1234)            # canaries: the off path must not touch regs
uc.reg_write(UC_M68K_REG_A2, 0x5678)
pc = run_to(uc, RENDER_SITE, {RENDER_RESUME, ARM_EXIT})
check("resumes into the stock arm", pc == RENDER_RESUME)
sp = uc.reg_read(UC_M68K_REG_A7)
check("pea replayed (sp-4, top = grid bitmap)",
      sp == sp0 - 16 and r32(uc, sp) == 0x400beafa, f"sp={sp:#x} top={r32(uc, sp):#x}")
check("registers untouched", uc.reg_read(UC_M68K_REG_D4) == 0x1234 and
      uc.reg_read(UC_M68K_REG_A2) == 0x5678)
check("no draw calls", not calls)

# ---------------- render: flag ON, slice playing, loop configured ----------------
print("render, flag ON: slice 11 of a sliced sample, halfway, loop at 1/4")
uc, calls = mk()
w32(uc, F_FLAG, 1)
w32(uc, BLINKCTR, 0)                            # bit 3 clear -> number visible
w8(uc, POSTED, 1)
setup_voice(uc, track=2, active=True, slice_idx=10, pos=1500, start=1000, end=2000, loop=1250)
uc.reg_write(UC_M68K_REG_A7, sp0 - 12)
pc = run_to(uc, RENDER_SITE, {RENDER_RESUME, ARM_EXIT})
check("exits via the arm tail", pc == ARM_EXIT)
check("blit args dropped (sp back to caller frame)", uc.reg_read(UC_M68K_REG_A7) == sp0)
check("POSTED consumed", r8(uc, POSTED) == 0)
fills = [a for f, a in calls if f == FILLRECT]
check("area clear is first", calls and calls[0][0] == FILLRECT and
      fills[0][1:6] == [61, 10, 117, 24, 0], str(calls[:1]))
check("bar box drawn", len(fills) >= 3 and fills[1][1:6] == [84, 13, 116, 21, 1]
      and fills[2][1:6] == [85, 14, 115, 20, 0], str(fills))
# pos 1500 in [1000,2000] -> w = 500*31/1000 = 15 -> fill 85..99
check("fill width matches position", len(fills) == 4 and fills[3][1:6] == [85, 14, 99, 20, 1],
      str(fills))
vl = [a for f, a in calls if f == VLINE]
# loop 1250 -> (250*30)/1000 = 7 -> x = 92, XOR, y 12..22
check("loop marker vline", len(vl) == 1 and vl[0][1:4] == [92, 12, 22] and
      vl[0][4] == 0xFFFFFFFF, str(vl))
fmt = [a for f, a in calls if f == DRAWFMT]
check("number drawn: font12 centred at (72,12), value 11",
      len(fmt) == 1 and fmt[0][0] == 0x400ba89e and fmt[0][2:6] == [72, 12, 1, 1]
      and fmt[0][8] == 11, str(fmt))
check("no dashes on the playing path", fmt[0][7] == NM["sv_fmt"])

# ---------------- render: number steady regardless of the tick counter ----------------
print("render, flag ON: number steady, no loop")
uc, calls = mk()
w32(uc, F_FLAG, 1)
w32(uc, BLINKCTR, 8)                            # any phase: the number no longer blinks
setup_voice(uc, track=0, active=True, slice_idx=3, pos=100, start=0, end=400, loop=0xFFFFFFFF)
uc.reg_write(UC_M68K_REG_A7, sp0 - 12)
pc = run_to(uc, RENDER_SITE, {RENDER_RESUME, ARM_EXIT})
check("exits via the arm tail", pc == ARM_EXIT)
fmt = [a for f, a in calls if f == DRAWFMT]
check("number drawn steady (value 4)", len(fmt) == 1 and fmt[0][8] == 4, str(fmt))
check("no loop marker when loop = -1", not any(f == VLINE for f, _ in calls))
# pos 100/400 -> 100*31/400 = 7 -> fill 85..91
fills = [a for f, a in calls if f == FILLRECT]
check("bar still fills", len(fills) == 4 and fills[3][1:6] == [85, 14, 91, 20, 1], str(fills))

# ---------------- render: idle voice ----------------
print("render, flag ON: idle voice")
uc, calls = mk()
w32(uc, F_FLAG, 1)
setup_voice(uc, track=5, active=False, slice_idx=0, pos=0, start=0, end=100, loop=-1 & 0xFFFFFFFF)
uc.reg_write(UC_M68K_REG_A7, sp0 - 12)
pc = run_to(uc, RENDER_SITE, {RENDER_RESUME, ARM_EXIT})
check("exits via the arm tail", pc == ARM_EXIT)
txt = [a for f, a in calls if f == DRAWFMT]
check("centred dashes", len(txt) == 1 and txt[0][0] == 0x400ba89e and txt[0][2:6] == [72, 12, 1, 1]
      and txt[0][7] == NM["sv_dash"], str(txt))
check("only the area clear otherwise", len([1 for f, _ in calls if f == FILLRECT]) == 1)

# ---------------- render: whole-sample (slice -1) uses the trim triple ----------------
print("render, flag ON: no slice selected (trim window)")
uc, calls = mk()
w32(uc, F_FLAG, 1)
w32(uc, BLINKCTR, 0)
setup_voice(uc, track=1, active=True, slice_idx=-1, pos=750, start=500, end=1500, loop=-1 & 0xFFFFFFFF)
uc.reg_write(UC_M68K_REG_A7, sp0 - 12)
pc = run_to(uc, RENDER_SITE, {RENDER_RESUME, ARM_EXIT})
check("exits via the arm tail", pc == ARM_EXIT)
fills = [a for f, a in calls if f == FILLRECT]
check("bar from the trim triple: 250*31/1000 = 7 -> 85..91",
      len(fills) == 4 and fills[3][1:6] == [85, 14, 91, 20, 1], str(fills))
txt = [a for f, a in calls if f == DRAWFMT]
check("dashes instead of a number", len(txt) == 1 and txt[0][7] == NM["sv_dash"], str(txt))

# ---------------- tick paths ----------------
def run_tick(flag, view, modal, posted, blink, posttime):
    uc, calls = mk()
    w32(uc, F_FLAG, flag); w32(uc, VIEW, view); w32(uc, MODAL, modal)
    w8(uc, POSTED, posted); w32(uc, BLINKCTR, blink); w32(uc, POSTTIME, posttime)
    uc.reg_write(UC_M68K_REG_A7, sp0)
    pc = run_to(uc, TICK_SITE, {TICK_RESUME})
    posts = [a for f, a in calls if f == POST]
    return uc, pc, posts

print("tick")
uc, pc, posts = run_tick(flag=0, view=3, modal=0, posted=0, blink=5, posttime=0)
check("flag off: resumes, counts, no post", pc == TICK_RESUME and r32(uc, BLINKCTR) == 6
      and not posts)
check("flag off: sp balanced", uc.reg_read(UC_M68K_REG_A7) == sp0)
uc, pc, posts = run_tick(flag=1, view=3, modal=0, posted=0, blink=0, posttime=0)
check("posts event 78 to the UI queue", len(posts) == 1 and posts[0][0] == UIQ
      and posts[0][1] == NM["sv_msg"], str(posts))
check("marks POSTED and stamps POSTTIME", r8(uc, POSTED) == 1 and r32(uc, POSTTIME) == 1)
uc, pc, posts = run_tick(flag=1, view=3, modal=0, posted=1, blink=10, posttime=9)
check("outstanding post: throttled", not posts)
uc, pc, posts = run_tick(flag=1, view=3, modal=0, posted=1, blink=100, posttime=10)
check("stale post: retried after 64 ticks", len(posts) == 1)
uc, pc, posts = run_tick(flag=1, view=2, modal=0, posted=0, blink=0, posttime=0)
check("other view: no post", not posts)
uc, pc, posts = run_tick(flag=1, view=3, modal=1, posted=0, blink=0, posttime=0)
check("modal open: no post", not posts)

# msg blob: event 78, 8 bytes
uc, _ = mk()
msg = uc.mem_read(NM["sv_msg"], 8)
check("sv_msg is event 78", msg[0] == 78 and all(b == 0 for b in msg[1:]))

# ---------------- menu getter/setter ----------------
print("menu")
for flag, want in ((0, 0x400b5e8e), (1, 0x400b5e90)):
    uc, _ = mk()
    w32(uc, F_FLAG, flag)
    uc.reg_write(UC_M68K_REG_A7, sp0 - 4)
    w32(uc, sp0 - 4, 0x400453f8)                 # fake return address: a real rts target
    pc = run_to(uc, NM["get_sliceview"], {0x400453f8})
    check(f"getter flag={flag}", uc.reg_read(UC_M68K_REG_D0) == want,
          hex(uc.reg_read(UC_M68K_REG_D0)))
uc, _ = mk()
w32(uc, F_FLAG, 0)
uc.reg_write(UC_M68K_REG_A7, sp0 - 8)
w32(uc, sp0 - 8, 0x400453f8)
w32(uc, sp0 - 4, 1)                              # delta +1
pc = run_to(uc, NM["set_sliceview"], {0x400453f8})
check("setter toggles 0 -> 1", r32(uc, F_FLAG) == 1)

print()
if FAILS:
    sys.exit(f"{len(FAILS)} FAILED: {FAILS}")
print(f"emu_sliceview: ALL GREEN on {IMG_PATH}")
