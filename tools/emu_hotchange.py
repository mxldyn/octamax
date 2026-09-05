#!/usr/bin/env python3
"""
HOT CHANGE tracer harness — run the REAL patched ColdFire image under Unicorn and
log every operation that could SILENCE track 6 (voice index 6), together with the
live value of g_hot at that instant.

Why: on hardware, v16 (g_hot left armed the whole time) STILL cut track 6 after the
"all tracks -> static" reset. Since hot_vstop gates FUN_40006820 and g_hot was armed,
that cut must go through a DIFFERENT primitive. This harness finds it without hardware:
it traces the call sequence + the exact writes to track 6's voice-active byte and
machine-type, so we can see WHICH function silences the voice and whether a gate
would catch it.

Limits (honest): the DSP (0x20000000) is NOT emulated, so this proves CONTROL-path
logic (who sends the stop, when, with g_hot=?), not audio. The sequencer frame-ISR
does not free-run here, so post-load apply must be invoked explicitly.

Usage:  python3 tools/emu_hotchange.py [image.bin]   (default out/mainos_hot.bin)
"""
import subprocess, sys, pathlib, struct
from unicorn import *
from unicorn.m68k_const import *

BASE = 0x40000400
IMG = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "out/mainos_hot.bin").read_bytes()

# --- symbols from the assembled patch (g_hot lives in the cave) ---
def hc_syms():
    out = subprocess.run(["m68k-elf-nm", "out/hc.elf"], capture_output=True, text=True).stdout
    return {p[2]: int(p[0], 16) for p in (l.split() for l in out.splitlines()) if len(p) == 3}

SYM = hc_syms()
G_HOT = SYM["g_hot"]                       # 0x400d78bc

# --- track-6 observables ---
VOICE_BASE = 0x800049d8
VOICE_STRIDE = 0xA8
VOICE6 = VOICE_BASE + 6 * VOICE_STRIDE      # 0x80004dc8  byte0 = active
MTYPE_BASE = 0x46c80354
MTYPE6 = MTYPE_BASE + 6 * 4                  # 0x46c8036c

# --- functions of interest (entry -> label). PC hitting these = a call. ---
WATCH_FN = {
    0x40006820: "FUN_40006820 voice-stop(track)",
    0x4000672c: "FUN_4000672c DSP-noteoff(track)",
    0x40008f84: "FUN_40008f84 voice-cmd(track)",
    0x40008fe4: "FUN_40008fe4 voice-wrap(track)",
    0x40006890: "FUN_40006890 stop-ALL",
    0x40096ab0: "FUN_40096ab0 flex-assign(track)",
    0x4000db98: "FUN_4000db98 mtype-set?",
    0x4000e018: "FUN_4000e018 mtype-set?",
    0x40006760: "FUN_4000672c BODY (note-off ran!)",   # past the detour: only if NOT gated
    SYM.get("hot_vstop", 0): "hot_vstop (our gate)",
    SYM.get("hot_noteoff", 0): "hot_noteoff (our gate)",
    SYM.get("hot_vstop2", 0): "hot_vstop2 (f84 gate)",
}


def new_uc():
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    uc.mem_map(0x40000000, 0x200000)
    uc.mem_write(BASE, IMG[: 0x200000 - 0x400])
    uc.mem_map(0x46000000, 0x1000000)                # app data / project / metadata
    uc.mem_map(0x80000000, 0x20000)                  # hot RAM: voices, mailboxes
    uc.mem_map(0x10000000, 0x1000000)                # small globals + settings structs
    uc.mem_map(0x41000000, 0x20000)                  # stack
    # DSP / peripheral MMIO windows, pre-seeded "ready" so polls don't spin forever
    uc.mem_map(0x20000000, 0x1000)
    uc.mem_write(0x20000008, struct.pack(">I", 0x6))     # "DSP ready": (*0x08 & 6)!=0
    uc.mem_write(0x20000004, struct.pack(">I", 0x0))     # not busy (bit7 clear)
    uc.mem_map(0xFC000000, 0x100000)                     # ColdFire on-chip peripherals

    def on_unmapped(uc, access, address, size, value, user):
        uc.mem_map(address & ~0xFFF, 0x1000)             # zero RAM on demand
        return True
    uc.hook_add(UC_HOOK_MEM_UNMAPPED, on_unmapped)
    return uc


def rd(uc, addr, n=4):
    return int.from_bytes(uc.mem_read(addr, n), "big")


def run_fn(label, entry, args, g_hot, maxins=400000, verbose=True, seed=None):
    """Execute `entry(args...)` with g_hot pre-set; log stop-events touching track 6."""
    uc = new_uc()
    uc.mem_write(G_HOT, struct.pack(">I", g_hot & 0xffffffff))
    # plausible project base (some paths deref 0x46c82456)
    uc.mem_write(0x46c82456, struct.pack(">I", 0x46d00000))
    uc.mem_write(0x800000d8, struct.pack(">I", 1))       # LAZY TRANSITIONS on
    # --- runtime-context globals that are negative/idle in the static image but are
    #     set during a real load; seed them so the load's voice-stop path is reached ---
    uc.mem_write(0x400d7c48, struct.pack(">I", 0))       # "load ctx active" (>=0 => not blt-skip)
    uc.mem_write(0x400d7c4c, struct.pack(">I", 6))       # active/selected track = 6
    # seed ALL 8 voices ALIVE + machine=flex so we can spot bulk "reset all" clears
    for t in range(8):
        uc.mem_write(VOICE_BASE + t * VOICE_STRIDE, struct.pack(">B", 1))
        uc.mem_write(VOICE_BASE + t * VOICE_STRIDE + 0x14, struct.pack(">b", 4))  # type=4 so note-off body runs
        uc.mem_write(MTYPE_BASE + t * 4, struct.pack(">I", 0x40))
    uc.mem_write(0x461054ec, struct.pack(">I", 0xFF))    # DSP-active mask (note-off clears track's bit)
    uc.reg_write(UC_M68K_REG_SR, 0x2700)                 # supervisor (allow move-from/to SR)
    if seed:
        for addr, (val, sz) in seed.items():
            uc.mem_write(addr, val.to_bytes(sz, "big"))

    sp = 0x41010000
    RET = 0x401f0000
    for a in reversed(args):
        sp -= 4; uc.mem_write(sp, struct.pack(">I", a & 0xffffffff))
    sp -= 4; uc.mem_write(sp, struct.pack(">I", RET))
    uc.reg_write(UC_M68K_REG_A7, sp)

    events = []
    calls = []

    def on_code(uc, pc, size, u):
        fn = WATCH_FN.get(pc)
        if fn:
            a7 = uc.reg_read(UC_M68K_REG_A7)
            trk = rd(uc, a7 + 4)                          # arg0 at 4(sp) at entry
            gh = rd(uc, G_HOT)
            calls.append((pc, fn, trk, gh))

    def on_write(uc, access, address, size, value, u):
        pc = uc.reg_read(UC_M68K_REG_PC)
        gh = rd(uc, G_HOT)
        if VOICE6 <= address < VOICE6 + 1 or address == VOICE6:
            events.append(("VOICE6-active", pc, address, value, size, gh))
        elif MTYPE6 <= address < MTYPE6 + 4:
            events.append(("MTYPE6", pc, address, value, size, gh))
        elif address == 0x461054ec:
            events.append(("DSP-noteoff-fx", pc, address, value, size, gh))

    uc.hook_add(UC_HOOK_CODE, on_code)
    uc.hook_add(UC_HOOK_MEM_WRITE, on_write)
    err = None
    try:
        uc.emu_start(entry, RET, count=maxins)
    except UcError as e:
        err = "%s @ PC=0x%08x" % (e, uc.reg_read(UC_M68K_REG_PC))

    if verbose:
        print(f"\n=== {label}  (g_hot={g_hot})  entry=0x{entry:08x} args={args} ===")
        if err:
            print(f"   [stopped: {err}]")
        print(f"   calls to stop/assign primitives: {len(calls)}")
        for pc, fn, trk, gh in calls[:40]:
            mark = "  <== TRACK 6" if trk == 6 else ""
            print(f"     0x{pc:08x} {fn:34s} track={trk:<10} g_hot={gh}{mark}")
        after = [rd(uc, VOICE_BASE + t * VOICE_STRIDE, 1) for t in range(8)]
        cleared = [t for t in range(8) if after[t] == 0]
        print(f"   voices alive after: {after}   cleared: {cleared if cleared else 'NONE'}"
              + ("   <== TRACK 6 SILENCED" if 6 in cleared else ""))
        if events:
            print(f"   writes touching track6 voice/machine: {len(events)}")
            for kind, pc, addr, val, sz, gh in events[:20]:
                print(f"     {kind:14s} pc=0x{pc:08x} [0x{addr:08x}]={val:#x} ({sz}B) g_hot={gh}")
    return calls, events, (rd(uc, VOICE6, 1))


if __name__ == "__main__":
    print("g_hot @ 0x%08x   VOICE6 @ 0x%08x   MTYPE6 @ 0x%08x" % (G_HOT, VOICE6, MTYPE6))
    print("hot_vstop @ 0x%08x" % SYM.get("hot_vstop", 0))

    # --- validation A: flex-assign of track 6, DISARMED. Expect it to stop the voice
    #     (FUN_40096ab0 -> FUN_40006820(6) -> clears voice byte + DSP note-off). ---
    run_fn("A. flex-assign(6) DISARMED", 0x40096ab0, [6], g_hot=0)

    # --- validation B: same, ARMED. Expect hot_vstop to swallow the stop (voice alive). ---
    run_fn("B. flex-assign(6) ARMED", 0x40096ab0, [6], g_hot=1)

    # --- probe C/D: the machine-type setters — do THEY silence track 6? (static reset?) ---
    run_fn("C. FUN_4000db98(track=6) ARMED", 0x4000db98, [6, 0], g_hot=1)
    run_fn("D. FUN_4000e018(track=6) ARMED", 0x4000e018, [6, 0], g_hot=1)

    # --- probe E/F/G: the OTHER voice-stop primitives + the big voice-init/reset fn ---
    run_fn("E. FUN_40008f84(track=6) ARMED", 0x40008f84, [6], g_hot=1)
    run_fn("F. FUN_40008fe4(track=6) ARMED", 0x40008fe4, [6], g_hot=1)
    run_fn("G. FUN_400068e4 (voice-init/reset?) ARMED", 0x400068e4, [6, 0, 0], g_hot=1)

    # --- H: recorder voice (type 4) ARMED must be PROTECTED; normal voice (type 0) must NOT ---
    print("\n########## index-agnostic type-4 gate check ##########")
    run_fn("H1. flex-assign(6) ARMED, voice6 type=4 (recorder)", 0x40096ab0, [6], g_hot=1,
           seed={VOICE_BASE + 6*VOICE_STRIDE + 0x14: (4, 1)})
    run_fn("H2. flex-assign(6) ARMED, voice6 type=0 (normal)", 0x40096ab0, [6], g_hot=1,
           seed={VOICE_BASE + 6*VOICE_STRIDE + 0x14: (0, 1)})
