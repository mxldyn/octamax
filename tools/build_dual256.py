#!/usr/bin/env python3
"""
build_dual256.py — DUAL-TABLE 256-slot image generator (Wave 0: read/display de-risk).

Builds on pristine stock (DSP never touched). Installs the emu-verified redirect helper family
(tools/patch_dual256.s), boot-initialises the four B-tables in the verified-free DDR hole (zero +
FILL by copying slots 0..127 so redirected reads see valid data, not zeros), then migrates a chosen
SET of accessor functions:
   * RAISE each function's static clamp `cmpi.l #128` so idx 128..255 reach the add instead of NULL
     (respecting bhi/bhs so OOR/sentinel indices still bail to A/NULL = stock-safe),
   * REDIRECT each per-slot table add (`add #base,reg`) -> `jsr helper` (same 6 bytes).

Incremental safety: any function NOT in SET keeps its #128 clamp -> NULLs idx>=128 -> stock behaviour,
so every intermediate flash boots. This Wave migrates the READ path only (no audio-engine sites).

    python3 tools/build_dual256.py            # -> out/mainos_dual256.bin  (+ emu-gate reminder)
"""
import pathlib, sys, subprocess

BASE = 0x40000400
SRC = pathlib.Path("out/stock_mainos.bin")
OUT = pathlib.Path("out/mainos_dual256.bin")

# WAVE-0 hardware result [2026-08-12]: getter-only WITH boot-init booted fine but left static slots
# empty + reset the clock -> the boot-zero of [0x46c96000,0x46cb9e00) clobbers a RUNTIME-LIVE DDR
# region (register-relative-accessed; invisible to the static scan). So BOOTINIT is a diagnostic
# toggle: with it OFF, only the getter is migrated (idx<128 byte-identical to stock) -> isolates
# whether the getter mechanism itself is harmless. The real fix (a genuinely-free B-region) is next.
BOOTINIT = True
# Diagnostic 2: keep the getter clamp at #128 (do NOT open to #255). With RAISE_CLAMPS=False the
# migrated getter is BEHAVIOURALLY STOCK-EQUIVALENT (idx<128 -> A via helper == stock add; idx>=128
# -> NULL via the unchanged clamp, before the jsr). Isolates whether OPENING the clamp (a sentinel
# collision: many things encode "no static slot" as an idx>127 that stock NULLs) is what emptied the
# static slots -- vs the jsr-to-helper plumbing on this specific function.
RAISE_CLAMPS = True

# ---- B-table layout INSIDE the pool-reclaimed reserve [0x40a955e0, 0x40af55e0) ----
# 0x47700000 (the previous home) is in the sample-pool/heap tail, which the OS OVERWRITES at
# runtime ("unreferenced != free", NOTES: canary showed 0x47800000 & 0x10020000 both clobbered).
# That silently wiped SETTINGS-B after every project load -> empty slot 129. The ONLY reliable home
# is the 384 KB reserve carved below the pool by moving its physical base up (POOL_RECLAIM below;
# build_ramdump.py Step 1, hardware-confirmed safe). B-tables laid out contiguously from the base:
#   SETTINGS-B [0x40a955e0, 0x40ab79e0)  0x448*128 = 0x22400
#   STATE-B    [0x40ab79e0, 0x40ab8fe0)  44*128    = 0x1600
#   STRIDE4-B1 [0x40ab8fe0, 0x40ab91e0)  4*128     = 0x200
#   STRIDE4-B2 [0x40ab91e0, 0x40ab93e0)  4*128     = 0x200   (ends well below pool@0x40af55e0)
ST_A, ST_B, ST_STRIDE, ST_N = 0x46c90a78, 0x40ab79e0, 44, 128          # STATE
S41_A, S41_B = 0x46c920a4, 0x40ab8fe0                                   # stride4 #1
S42_A, S42_B = 0x46c93a24, 0x40ab91e0                                   # stride4 #2
SET_A, SET_B, SET_STRIDE = 0x100d5b30, 0x40a955e0, 0x448                # SETTINGS
T24_A, T24_B, T24_STRIDE = 0x46947c56, 0x40ab93e0, 24                   # Wave 8 streaming table
# HOLE extended to cover T24-B (0x40ab93e0 + 128*24 = 0x40ab9fe0) so it is boot-zeroed. SLICE_SCRATCH
# moved to 0x40aba000 (after T24-B) in patch_dual256.s. Reserve layout now:
#   SETTINGS-B 0x40a955e0 | STATE-B 0x40ab79e0 | S4B1 0x40ab8fe0 | S4B2 0x40ab91e0 |
#   T24-B 0x40ab93e0 (0xC00) -> 0x40ab9fe0 [=HOLE_HI] | SLICE_SCRATCH 0x40aba000 (0x3000) -> 0x40abd000
HOLE_LO, HOLE_HI = 0x40a955e0, 0x40ab9fe0

# ---- POOL RECLAIM (build_ramdump.py Step 1): move the flex-pool physical base up so
# [OLD_POOL, NEW_POOL) becomes a fixed unreferenced reserve that the pool never reuses. ----
POOL_RECLAIM = True
OLD_POOL, NEW_POOL = 0x40a955e0, 0x40af55e0
POOL_COUNT_AT, POOL_OLD_COUNT, POOL_NEW_COUNT = 0x40096f82, 0x390A, 0x38CA

# --- Wave 8: PROJECT-LOAD bulk sample-loader loop 0x4009083c ("Couldn't load STATIC[%d]"). This is
# the loop that RELOAD runs to actually OPEN+associate every STATIC slot's sample (calls FN-VIEW via
# d6=0x40093980 for each slot with a non-empty path). It is a POINTER-WALK: a2 starts at SET-A[0] and
# each iteration does `lea a2@(1096),a2` then `cmpi #128,d3; bne loop` -> it processes ONLY idx 0..127
# and STOPS at 128, so slot 129 is NEVER loaded on RELOAD (root cause of "no audio / empty slot 129" --
# found by tracing FN-VIEW's callers: the 0x40084c1a jsr is the on-select path; THIS d6 loop is RELOAD).
# The a2 walk bypasses the settings helper, so we detour the tail: at the A->B boundary (d3==128) reset
# a2 to SET_B[0], keep walking contiguously for 129..255, and raise the bound to 256.
MIGRATE_LOADLOOP = True
LOADLOOP_HOOK = 0x400908f4     # 14 B: lea a2@(1096),a2 ; cmpi.l #128,d3 ; bnew 0x4009087a
LOADLOOP_BODY = 0x4009087a     # loop head (body start)
LOADLOOP_EXIT = 0x40090902     # after the loop (FLEX loop follows)
LOADLOOP_STUB = 0x400d77c0     # free cave after the (Wave-10-extended) helper family; before 0x400d7c00
# --- Wave 19 (frontier): extended STATIC allocator -- walk STATE-B after STATE-A so a NEW sample can be
# assigned to a high slot on-device. Detour replaces the 16-byte loop tail [0x400240ac,0x400240bc).
MIGRATE_ALLOC = True
STATEB_FREEINIT = False       # P32 DIAGNOSTIC (2026-08-20): it marks all 128 B slots @8=1 (=FREE, the
                              # value the allocator FUN_40024098 tests at 0x400240a2). Nothing ever clears
                              # @8 back to 0 when a sample is loaded into a high slot, and the AED's
                              # "has content?" predicate (0x4006db32: STATE@8 -> seq) is TRUE only when
                              # @8 == 0 -> every high slot reads as empty and the AED draws nothing.
                              # Trade-off while False: the extended allocator can no longer see B slots as
                              # free, so "assign to a free high slot" on-device is expected to stop finding
                              # them; explicit AED FILE->LOAD into slot 129 is unaffected.         # boot-init STATE-B[i].status@8 = 1 (free) so the allocator sees empty B slots
ALLOC_STUB = 0x400d7000        # free cave [0x400d7000,0x400d7400) between GAP_STUBS and the helper family
ALLOC_HOOK = 0x400240ac        # 16 B: addq/lea/cmpi #128/bne/bra -> jmp alloc_adv + nops
ALLOC_LOOP = 0x400240a2        # loop head (status check)
ALLOC_NOTFOUND = 0x400240d2    # "no free slot" path

HELP_AT = 0x400d7400          # helper family base (matches patch_dual256.s .text)
BOOT_STUB = 0x400d64e0        # boot-init stub (in the 0x400d64da.. free cave)
BOOT_HOOK = 0x4001fa64        # detour point: `lea 0x10000000,a0` (6 bytes) in the boot mem-clear

# --- Wave 4: SIDECAR persistence of SETTINGS-B (128-255) to <projectdir>/project.256 ---
SIDECAR = True
# TRACE mode: instrument memcpy 0x40020898 to capture the caller PC of whatever writes the paste's
# dest slot (dst == 0x100f7f30 = SETTINGS-A[128]). The capture lands at 0x47701a00 (SETTINGS-B[0]),
# which the sidecar already dumps to project.256[0:16]. Needs zero-init boot so the capture slot
# starts empty. Read project.256[0:16] after COPY 57 -> PASTE 129 -> SAVE to get the paste function.
TRACE = False                 # working build: no memcpy hook (TRACE builds set this True)
TRACE_STUB = 0x400d6900       # trace stub (after the sidecar, before the helper cave)
COPYFILL_SET = True           # copy-fill SETTINGS-B at boot. MUST be False for the persist256 build:
                              # the extended serializer reads SETTINGS-B, so copy-filled B would emit
                              # 128 PHANTOM STATIC slots (129..256 duplicating 1..128) on every save.
COPYFILL_STATE = False        # copy-fill STATE-B + stride4-B at boot. MUST be False once FN-VIEW is
                              # migrated (Wave 7): FN-VIEW's entry FN-CLEAR (0x40093814) reads STATE@36
                              # (old handle) and, if >0, CLOSEs it via 0x46c82422 -> 0x46c8657e[handle]
                              # (stride 48). Copy-fill puts UNINITIALISED-DDR garbage in STATE-B[0]@36
                              # (STATE-A is copied at boot BEFORE the OS zeroes it) -> a huge + handle ->
                              # wild OOB close -> slot 129 breaks (P7 regression, name vanishes). STATE-B
                              # + stride4-B live inside the HOLE [0x40a955e0,0x40ab93e0) which the boot
                              # stub already zeroes; leaving them out of the copy-fill = clean empty
                              # (@8=0, @36=0 -> FN-CLEAR's bles skips the close). reset-slot does NOT
                              # close @36 (verified), and copy/paste/parser overwrite the full struct,
                              # so nothing needs the pre-filled slot-(idx-128) data (that was a bug:
                              # empty high slots displayed low-slot data). Zero = correct "empty".
TRACE_CAP = 0x40a955e0        # capture: [caller_PC][dst][src][len] at SETTINGS-B[0] -> project.256[0:16]
MEMCPY = 0x40020898
SIDECAR_AT = 0x400d6600       # sidecar code+data (between boot stub and helper cave)
SETB_LO, SETB_HI = 0x40a955e0, 0x40ab79e0     # SETTINGS-B extent = 128*0x448 = 140288 B
# skip-empty sidecar restore: read project.256 into this temp (free reserve above SLICE_SCRATCH, below
# the moved pool -> referenced by nothing), then copy per-slot to SET-B ONLY when the file slot's path[0]
# != 0. Prevents an empty/stale project.256 from clobbering parser-written SET-B (the name-blank bug).
SIDE_TEMP = 0x40abd000                        # 0x22400 B temp, ends 0x40adf400 < pool 0x40af55e0
# verified CF I/O primitives + project-dir composer (from the save/load recon):
IO_OPEN, IO_READ, IO_WRITE, IO_CLOSE = 0x40016864, 0x40016564, 0x400166b8, 0x4001677c
IO_SPRINTF, DIR_OF = 0x40013a08, 0x40025230
IO_BUF, IO_BUFSZ = 0x460a8f60, 0x10000
MODE_W, MODE_R = 0x400b328b, 0x400b3289       # "w" / "r" C strings
SAVE_HOOK = 0x4008ff44        # 6B: tstl a3(4a8b) beqs+2(6702) jsr a3@(4e93) -> replicate after write
LOAD_HOOK = 0x4009021a        # 6B: moveml fp@(-576),d2-d6/a2-a4 (4cee1c7cfdc0) -> replicate after read

# helper VAs are resolved from the assembled ELF symbol table (name -> VA).

# ---- migration set: function -> {clamps:[(va,)], sites:[(imm_va, helper_name)]} ----
# imm_va is the census site (offset of the 4-byte immediate); the instruction to replace starts at
# imm_va-2. Clamp va points at the `cmpi.l #128,dN` (0c8N 00000080) whose branch gates the sites.
#
# WAVE 0 = GETTER ONLY. The canonical (type,idx)->settings-pointer getter is a clean leaf: ONE static
# clamp (#128) + ONE settings add, no STATE/stride4/flex adds to co-migrate. Migrating exactly it
# proves the ENTIRE foundation is boot-safe (helpers installed, 4 B-tables zeroed+filled at boot, boot
# detour intact, a real redirect site live) with zero risk of the "opened-clamp + missed-add -> OOB"
# hazard that multi-table functions carry. Later waves add multi-add functions behind an OOB emu-gate.
# Each entry: entry/end (TRUE extent, next-prologue), clamps to open, and EVERY per-slot add in the
# function (settings+state+stride4). The OOB gate asserts no per-slot base-add remains in [entry,end)
# after redirect -- a missed one would OOB-write the working region at runtime = project corruption.
CORE = {
    "getter_0x4006da78": {
        "entry": 0x4006da78, "end": 0x4006decc, "clamps": [0x4006da88],
        "sites": [(0x4006da9a, "h_set_d0")],
    },
    "activation_0x4009367c": {
        "entry": 0x4009367c, "end": 0x400937d4, "clamps": [0x400936b2],
        "sites": [(0x400936cc, "h_set_a3")],
    },
    "trackenable_0x40093e9c": {
        "entry": 0x40093e9c, "end": 0x400940ac, "clamps": [0x40093f6e, 0x40094044],
        "sites": [(0x40093f88, "h_set_a2"), (0x4009405a, "h_st_a0")],
    },
    "slice_0x40094334": {
        # 0x400946e6 is a SECOND #128 clamp gating the slot->STATE resolver at 0x400946f6 (site 0x400946f8,
        # already migrated to h_st_d0). idx=128 passes its `bhi` so slot 129 worked, but 129..255 were NULLed
        # -- open it so the whole high range resolves to STATE-B. (Found via the streaming decompilation.)
        "entry": 0x40094334, "end": 0x400947c0, "clamps": [0x40094350, 0x400946e6],
        "sites": [(0x40094364, "h_st_a3"), (0x40094380, "h_set_a1"), (0x400946f8, "h_st_d0")],
    },
    # --- popup static-slot browser (render + apply): makes 128-255 browsable/selectable ---
    "ui_render_0x40077b04": {
        "entry": 0x40077b04, "end": 0x40078850,
        "clamps": [0x40077dee, 0x40077f62, 0x400787c8],
        "sites": [(0x40077e0a, "h_set_a3"), (0x40077e18, "h_st_a2"),
                  (0x40077f76, "h_st_d0"), (0x4007809c, "h_st_d0")],
    },
    "ui_apply_0x40079428": {
        "entry": 0x40079428, "end": 0x400796a0, "clamps": [0x4007943a, 0x400794e8],
        "sites": [(0x40079450, "h_set_d0"), (0x400794fc, "h_st_d0")],
    },
    "ui_0x400796a4": {
        "entry": 0x400796a4, "end": 0x40079920, "clamps": [0x400797aa],
        "sites": [(0x400797ba, "h_st_d0")],
    },
    # --- Wave 5: SLOT COPY/PASTE (FUNC+COPY / FUNC+PASTE). HW confirmed the user's "copy sample to
    # slot 128" is a slot COPY/PASTE (not a pool-assign) -> function 0x40024f00 moves a full slot
    # (settings + STATE + stride4 pointer entries) between two slot indices. Migrating it makes PASTE
    # into idx>=128 write SETTINGS-B/STATE-B/stride4-B (so project.256 gets real data). 16 sites.
    "copypaste_0x40024f00": {
        "entry": 0x40024f00, "end": 0x40025288,
        "clamps": [0x40024f14, 0x40024f60, 0x40024fa8, 0x40024fea],
        "sites": [(0x40024f24, "h_st_d5"), (0x40024f72, "h_st_d4"),
                  (0x40024fbc, "h_set_d3"), (0x40025000, "h_set_d2"),
                  (0x4002504e, "h_s42_a0"), (0x40025058, "h_s41_a0"),
                  (0x4002506a, "h_s42_a0"), (0x40025074, "h_s41_a0"),
                  (0x40025086, "h_s42_a0"), (0x40025090, "h_s41_a0"),
                  (0x400250a2, "h_s42_a0"), (0x400250ac, "h_s41_a0"),
                  (0x40025118, "h_s42_a0"), (0x40025122, "h_s41_a0"),
                  (0x40025134, "h_s42_a0"), (0x4002513e, "h_s41_a0")],
    },
    # --- Wave 5c: the [/SAMPLE] serializer/parser 0x40086800 -- the strongest arbitrary-filename ->
    # slot-offset-0 writer (loads slots from project.work text AND likely the route the slot COPY/PASTE
    # uses to write the dest slot). Migrating it makes PASTE to idx>=128 write SETTINGS-B (offset-0
    # filename) + STATE-B. Only 2 slot sites in the whole 5KB fn. ---
    "sampleparser_0x40086800": {
        "entry": 0x40086800, "end": 0x40086a80, "clamps": [0x40086956, 0x400869bc],
        "sites": [(0x40086968, "h_st_d1"), (0x400869ce, "h_set_d0")],
    },
    # --- Wave 6d: reset-slot 0x40099148 -- the parser's REAL-pass slot INITIALISER (jsr'd @0x40086940
    # before the settings/PATH write). It has its OWN un-migrated base-adds, so for idx>=128 it inits
    # the OOB SET-A[128]/STATE-A[128] structure while the parser writes PATH to SET-B -> the slot ends
    # up SPLIT across A and B and shows EMPTY. Migrating it makes reset-slot init SET-B/STATE-B for
    # idx>=128, consistent with the parser. (Found via full-parser Unicorn trace: parser writes SET-B[0]
    # only when reset-slot is skipped; on HW reset-slot mis-inits A.) 4 sites, 2 STATIC #128 clamps. ---
    "resetslot_0x40099148": {
        "entry": 0x40099148, "end": 0x40099372, "clamps": [0x4009915c, 0x400991c4],
        "sites": [(0x40099170, "h_st_a0"), (0x400991dc, "h_set_a2"),
                  (0x40099352, "h_s42_a0"), (0x4009935c, "h_s41_a0")],
    },
    # --- Wave 6e: sample-loader 0x4008445c ("Couldn't load STATIC[%d]" @0x400b7... / FLEX[%d]). Loads
    # the actual sample FILE into a slot after the parser sets PATH; calls reset-slot. Its STATIC
    # SETTINGS base-adds (0x40084c6e/0x40084cb4) were un-migrated -> for idx>=128 it loaded the sample
    # into OOB SET-A[128]. Only the 2 STATIC settings sites + their #128 clamps need migration (FLEX
    # paths use 0x100b14f0 / #135, left stock). Completes the STATIC LOAD path (parser + reset-slot +
    # this). Found via reset-slot caller scan. ---
    "sampleloader_0x4008445c": {
        "entry": 0x4008445c, "end": 0x4008565c, "clamps": [0x40084c56, 0x40084c9c],
        "sites": [(0x40084c6e, "h_set_d0"), (0x40084cb4, "h_set_d1")],
    },
    # --- Wave 7: on-SELECT sample-open chain. With STATE now ALIGNED (idx=128->B[0], the bls->blo fix),
    # the earlier "INVALID FILENAME" blocker on 0x40093980 is gone (STATE + SETTINGS both resolve to B).
    # These 4 functions run when a STATIC slot is opened/viewed: they open the sample file, validate
    # WAVE/AIFF, compute length->TRIM, read the .ot header, and load slices. Un-migrated, they read the
    # OOB A[128] for idx=128 -> file open/validate/slice-read fail -> slot 129 shows NAME but no
    # waveform / no slices / TRIM=0. (Mapped by the sample-load-path agent.) ---
    "sampleview_0x40093980": {        # open+associate: validate magic, length->TRIM, build slice grid
        "entry": 0x40093980, "end": 0x40093e6a, "clamps": [0x4009398c],
        "sites": [(0x400939a4, "h_set_a4"), (0x400939b8, "h_st_a3"),
                  (0x40093de2, "h_slice_d0")],   # slice-display buffer -> shared reserve scratch for idx>=128
    },
    "sampleclear_0x40093814": {       # reset slot STATE + clear slice bitmap on select (called by VIEW)
        "entry": 0x40093814, "end": 0x4009395a, "clamps": [0x40093820],
        "sites": [(0x40093834, "h_st_a2")],
    },
    "samplehdr_0x40098ce0": {         # read sample-file header/type into STATE record
        "entry": 0x40098ce0, "end": 0x40098ebe, "clamps": [0x40098cf4],
        "sites": [(0x40098d0a, "h_set_d2"), (0x40098d1a, "h_st_a2")],
    },
    "sampleslice_0x40099374": {       # load slice table for a slot (reads SETTINGS@300 + STATE@20)
        "entry": 0x40099374, "end": 0x40099680, "clamps": [0x40099388, 0x400993fa],
        "sites": [(0x4009939c, "h_st_a0"), (0x40099412, "h_set_a2"),
                  (0x40099648, "h_s42_d0"), (0x40099658, "h_s41_d0")],
    },
    # --- Wave 9: INTERACTIVE ASSIGN-UI path (the "INVALID FILENAME" on assign-to-slot-129, idx=128).
    # RELOAD loads the slot fine (migrated parser + sampleloader), but the interactive browser ASSIGN
    # uses TWO un-migrated (type,idx)->SETTINGS/STATE-pointer resolvers. For STATIC idx=128 they pass
    # the #128 clamp (bhi: 128 not >128) and compute SET_A/STATE_A + idx*stride = OOB A[128] -> the
    # filename gets written to SET-A[128], so FN-VIEW(128) reads the empty SET-B[0] path -> strrchr('.')
    # =0 -> errcode -16 "INVALID FILENAME". Migrating them makes assign write SET-B[0]/STATE-B[0].
    #  * 0x40021d94: 8 callers, several in the popup slot browser / ui_apply (0x40078b1a/6a, 0x400791be,
    #    0x40079678/8a). Resolves the slot ptr + sprintf's the name into it. 3 STATIC sites (2 STATE + 1
    #    SET), 3 STATIC #128 clamps; the 3 FLEX adds (0x46c922c4 / 0x100b14f0, #135) stay stock (not in
    #    SLOT_BASES -> invisible to the OOB gate). block3 clamp is `bls` (->256); blocks 1/2 `bhi` (->255).
    #  * 0x40022614: the name-writer leaf (sprintf "%s" into the slot settings ptr). 1 STATIC site + clamp.
    "assign_getter_0x40021d94": {
        "entry": 0x40021d94, "end": 0x400221c0,
        "clamps": [0x40021dbe, 0x40021e2a, 0x40021ede],
        "sites": [(0x40021dce, "h_st_d0"), (0x40021e3e, "h_set_d2"), (0x40021ef2, "h_st_d0")],
    },
    "assign_writer_0x40022614": {
        "entry": 0x40022614, "end": 0x400226f2, "clamps": [0x40022628],
        "sites": [(0x4002263e, "h_set_d2")],
    },
    # --- Wave 10: make the assigned HIGH slot actually LOAD (attrs/slices) and PLAY. Three findings from
    # the playback + assign-load transitive maps (agents), all un-migrated STATIC per-slot tables:
    #
    #  (a) VOICE-BIND resolver 0x4000f450 -- the sound blocker. Called from the DSP voice-render loop
    #      (0x4000400c -> jsr 0x4000f450, slot idx in a3@(16)); caches the slot's STATE+SETTINGS pointers
    #      into the voice struct (a2@(4)/a2@(8)) that drive streaming. UNCLAMPED (no #128) -> idx>=128
    #      read OOB A[128] = garbage pointers -> no sound. The two adda sites self-bound via the helpers
    #      (no clamp to open). PLUS two STRIDE4 lea-base sites (generation/validity check that else
    #      spuriously fails -> re-binds every audio cycle): redirected below via VOICE_S4_LEA_SITES.
    "voicebind_0x4000f450": {
        "entry": 0x4000f450, "end": 0x4000f97c, "clamps": [],
        "sites": [(0x4000f4a6, "h_st_a5"), (0x4000f4b6, "h_set_a4")],
    },
    #  (b) ASSIGN .ot-attribute parser 0x40089940 -- the "name-but-no-waveform/slices/length" cause. The
    #      interactive assign runs a background worker (type-43 msg) that reads the sample's .ot sidecar
    #      and WRITES trim/loop/length/tempo/gain/quantize + the 64-entry slice table into SETTINGS[idx].
    #      Clamped #128 but idx=128 passes (bhi) -> writes OOB A[128] -> B[0] stays empty. Migrate -> B.
    "assign_otparse_0x40089940": {
        "entry": 0x40089940, "end": 0x40089d84, "clamps": [0x40089958],
        "sites": [(0x4008996e, "h_set_d3")],
    },
    #  (c) ASSIGN audio/PCM streamer 0x4008ea38 -- companion worker (type-45 msg) that reads STATE[idx]
    #      (@16 buffer count / handle) to drive playback streaming. Same #128-passes-at-128 OOB. product
    #      is built in d1 (moveq #44,d1; mulsl d6,d1) -> h_st_d1.
    "assign_stream_0x4008ea38": {
        "entry": 0x4008ea38, "end": 0x4008ec4c, "clamps": [0x4008ea54],
        "sites": [(0x4008ea66, "h_st_d1")],
    },
    #  (d) audio-engine per-track PARAM resolver 0x40005034 -- reads a slot playback param at SETTINGS@297.
    #      Clamped (safe, no OOB) but idx>=128 bailed -> B param never read. Migrate for param correctness.
    "trackparam_0x40005034": {
        "entry": 0x40005030, "end": 0x40005178, "clamps": [0x400050be],
        "sites": [(0x400050d0, "h_set_d0")],
    },
    # --- Wave 12: the two OFF-realtime-path STATE readers the streaming decomp flagged (assign-audition /
    # buffered decode + bulk/waveform reader). Un-migrated STATE-A reads -> for idx>=128 they hit the dead
    # gap past STATE-A[127] (pool). Not single-slot playback blockers, but they corrupt assign-preview /
    # waveform / analysis for high slots. Both are STATE-only (no SETTINGS/stride4).
    #  0x40093064 buffered decode/refill helper: ONE unclamped STATE-A read (product in a3) -> h_st_a3.
    "refill_0x40093064": {
        "entry": 0x40093064, "end": 0x400932e8, "clamps": [],
        "sites": [(0x4009307e, "h_st_a3")],
    },
    #  0x400774e0 bulk sample reader (calls 0x40093064): clamped STATE-A read (product in d2) -> h_st_d2.
    "bulkread_0x400774e0": {
        "entry": 0x400774a8, "end": 0x40077848, "clamps": [0x400774fc],
        "sites": [(0x4007750c, "h_st_d2")],
    },
    # --- Wave 14: TRACK-HEADER sample-NAME draw 0x40023d90 (the "slot 129 name blank on the track" bug).
    # The main-track header re-resolves the name live from the assigned-slot number every draw (NO per-track
    # name cache) via an INLINE un-migrated SETTINGS resolver -- distinct from the migrated getter
    # 0x4006da78 and from the popup browser render (which works). For idx=128 the `bhi #128` passes and it
    # computes SET-A[128] = empty -> tst.b path[0]==0 -> falls to the slot-number placeholder = blank name.
    # Callers 0x40076ce2/0x40076d60 pass the assigned-slot globals ui_apply writes (idx 0x46c8d19c,
    # type 0x46c8d1a0). One STATIC add + clamp; the FLEX add 0x40023e5a (0x100b14f0/#135) stays stock.
    # (Found via full-image per-slot-immediate census tools/census_unmigrated.py; verified by disasm.)
    "namedraw_0x40023d90": {
        "entry": 0x40023d90, "end": 0x40023f1c, "clamps": [0x40023e22],
        "sites": [(0x40023e36, "h_set_d0")],
    },
    # --- Wave 15: AED (Audio Editor) WAVEFORM-STREAM readers -- the "no waveform in AED for slot 129" bug.
    # Two identical functions stream the slot's overview to the LCD/DMA (0x80006924 + slot*8 -> 0x80006964).
    # Each takes a slot descriptor (idx@21, type@20); STATIC branch reads STATE[idx] (@base 0x46c90a78, d2)
    # to locate the stream source. Clamped #128 but bhi passes idx=128 -> reads STATE-A[128] = OOB template
    # end -> no stream -> blank waveform. Migrate the STATE add -> h_st_d2 and raise the clamp. The FLEX add
    # (0x46c922c4/#135) stays stock. (Found via census + AED render agent; verified by disasm.)
    "wavestream1_0x400985ac": {
        "entry": 0x400985ac, "end": 0x400986c8, "clamps": [0x400985c4],
        "sites": [(0x400985d4, "h_st_d2")],
    },
    "wavestream2_0x4009871c": {
        "entry": 0x4009871c, "end": 0x40098a5c, "clamps": [0x40098734],
        "sites": [(0x40098744, "h_st_d2")],
    },
    # --- Wave 16: AED (Audio Editor) tab-body STATE resolvers -- the "AED shows no waveform / slices /
    # attrs for slot 129" bug. The AED (entry 0x4006e160) resolves SETTINGS via the migrated getter
    # 0x4006da78 (numeric params render), but each of the 4 tab bodies (TRIM/SLICE/EDIT/ATTR) ALSO resolves
    # the slot's STATE record INLINE (`cmpi #128,d1; bhi null; moveq #44,d0; muls d1,d0; addi #0x46c90a78,d0`)
    # to read STATE@8 (the descriptor ptr that feeds the waveform/slice/attr canvas). Un-migrated -> for
    # idx=128 they read STATE-A[128] OOB -> garbage descriptor -> blank canvas. Each fn has exactly ONE
    # STATE add (census-confirmed); the recorder-STATE branch (0x46c922c4/#135) stays stock. STATE-B[0] is
    # populated at runtime (the sample plays), so these reads render correctly once migrated.
    # (Found via the complete AED render-map agent; verified by disasm.)
    "aed_trim_0x4006f0a4": {
        "entry": 0x4006f0a4, "end": 0x4006f8a4, "clamps": [0x4006f1b6],
        "sites": [(0x4006f1c6, "h_st_d0")],
    },
    "aed_slice_0x40070db8": {
        "entry": 0x40070db8, "end": 0x400715b8, "clamps": [0x40070ec8],
        "sites": [(0x40070ed8, "h_st_d0")],
    },
    "aed_edit_0x40073b30": {
        "entry": 0x40073b30, "end": 0x4007409c, "clamps": [0x40073bb8],
        "sites": [(0x40073bc8, "h_st_d0")],
    },
    "aed_attr_0x4006e450": {
        "entry": 0x4006e450, "end": 0x4006eb6c, "clamps": [0x4006e4c4],
        "sites": [(0x4006e4d6, "h_st_d0")],
    },
    # --- Wave 17: AED "load sample to slot" WRITE path (0x40024510 + its sibling 0x40024854). This is the
    # command-menu action (thunk 0x40076d70, AED cmd table 0x400b2d9e) that loads/associates a sample into
    # the CURRENT slot: it resolves SETTINGS[idx] (write path @0) + STATE[idx] and stores into them.
    # Un-migrated -> loading a sample into a HIGH slot wrote OOB SET-A[128]/STATE-A[128], so SET-B[0] stayed
    # empty and a subsequent SAVE captured an empty project.256 (the persistence half of the name blank).
    # FUNC A (idx in d3): SET add 0x40024574 -> h_set_d2, STATE add 0x40024580 -> h_st_d0, clamp 0x4002455e.
    # FUNC B (idx in d2): STATE add 0x40024932 -> h_st_d0, clamp 0x40024922. FLEX adds (#135) stay stock.
    # Migrated so loading into slot 129..256 writes SET-B/STATE-B -> a clean SAVE then persists real data.
    "aed_loadsample_a_0x40024510": {
        "entry": 0x40024510, "end": 0x40024854, "clamps": [0x4002455e],
        "sites": [(0x40024574, "h_set_d2"), (0x40024580, "h_st_d0")],
    },
    "aed_loadsample_b_0x40024854": {
        "entry": 0x40024854, "end": 0x40024c68, "clamps": [0x40024922],
        "sites": [(0x40024932, "h_st_d0")],
    },
    # --- Wave 18 (completeness sweep): LATENT OOB fix. The assign type-1 (open-file) emitter resolver
    # FUN_40023f1c had its STATIC clamp 0x40023f34 already RAISED to #256 by SENTINEL_FIX (so idx>=128
    # reaches the type-1 emission), but its SETTINGS add 0x40023f4a was left UN-migrated -> for idx=128..255
    # it computed SET-A[128..255] = OOB. Migrate the add (product in d2) to close the OOB. Clamp already
    # open (do NOT re-raise: clamps=[]). FLEX add (0x100b14f0/#135) stays stock. (Found via census sweep.)
    "assign_type1_0x40023f1c": {
        "entry": 0x40023f1c, "end": 0x40024098, "clamps": [],
        "sites": [(0x40023f4c, "h_set_d2")],
    },
    # --- Wave 19: the .OT SIDECAR READER 0x4008b8d0 -- the "slices never appear on a high slot" bug AND
    # (almost certainly) the spurious "SAMPLE LOAD ERRORS!" -2 popup. This is the ONLY function that
    # unmarshals a .ot file (validates FORM/DPS1/SMPA @0x400d1670/74/7e, then reads loopmode/trim/
    # 64x12 slices/count into SETTINGS[idx]); its one caller 0x4008fb?? builds "<sample>.ot", returns 2
    # if absent, else opens "r" and passes (stream, type d5, slot d4) straight through. Both its
    # follow-ups (sanitizer 0x40099374, post 0x40004f9c) were ALREADY migrated -- only this prologue
    # blocked the chain: STATIC branch `cmpi #128,d4; bhiw 0x4008be16` where the bail returns
    # **moveq #-2** (the popup!), then resolves SETTINGS-A + STRIDE4#2-A hardcoded. idx>128 -> -2 popup
    # + no slices; idx==128 passed bhi -> OOB A[128] (same CHECK1 off-by-one class). NOTE: the earlier
    # census filed site 0x4008b904 as "CLASS-B bank serializer, writes a file, held back on purpose" --
    # that classification was WRONG (it READS a file and WRITES SETTINGS). FLEX branch (#135 clamp,
    # 0x100b14f0) stays stock. FLEX flag add 0x4008b950 (S41) migrated to match the copypaste/resetslot
    # convention. (Found by xref'ing the SMPA magic const after the P43 probe proved +1092 is the field
    # the AED slice tab draws and markers.work only covers A.)
    "otreader_0x4008b8d0": {
        "entry": 0x4008b8d0, "end": 0x4008be2a, "clamps": [0x4008b8ee],
        "sites": [(0x4008b906, "h_set_a3"),
                  (0x4008b948, "h_s42_a0"),
                  (0x4008b952, "h_s41_a0")],
    },
}

# --- Wave 14: the OFF-BY-ONE class (audit CHECK 1, 2026-08-20) -------------------------------------
# Every site the earlier census filed as "SAFE/leave (clamp closed)" is in fact NOT closed for idx=128:
# the guard is `cmpi.l #128,dN` + **bhi**, which bails only on idx > 128. So idx == 128 (UI slot 129 --
# precisely the slot under test) falls through into the stock add and resolves SETTINGS-A[128] /
# STATE-A[128], one full stride past the end of table A. Invisible in stock (slot 128 is unreachable
# there), reachable in this build. Closing the guards instead of migrating would be the smaller change
# but would REGRESS the working case: two of these are the DSP per-voice readers on the audio path for
# the currently-playing high slot, so NULLing them risks re-introducing the P29 silence. Migrating keeps
# idx<128 byte-identical (helpers proven by verify_dual256) and gives idx>=128 the real B record.
MIGRATE_OFFBYONE = True        # set False to drop this wave wholesale if it regresses on HW
OFFBYONE_CORE = {
    "slotclear_0x40025288": {
        "entry": 0x40025288, "end": 0x400253d0, "clamps": [0x4002529c],
        "sites": [(0x400252b4, "h_set_a3")],
    },
    "unresolved_0x400276fa": {
        "entry": 0x400276fa, "end": 0x40027784, "clamps": [0x40027716],
        "sites": [(0x40027728, "h_set_d0")],
    },
    "unresolved2_0x40027772": {
        "entry": 0x40027772, "end": 0x40027848, "clamps": [0x400277e6],
        "sites": [(0x400277f8, "h_set_d0")],
    },
    "cfmount_0x40028fec": {
        "entry": 0x40028fec, "end": 0x4002913a, "clamps": [0x40029004],
        "sites": [(0x40029016, "h_st_d0"), (0x40029026, "h_set_d2")],
    },
    "plockdesc_0x4003193c": {
        "entry": 0x4003193c, "end": 0x40031d6e, "clamps": [0x40031d26],
        "sites": [(0x40031d38, "h_st_d0")],
    },
    "trigdisp_0x40044050": {
        "entry": 0x40044050, "end": 0x40044582, "clamps": [0x40044108],
        "sites": [(0x4004411a, "h_set_d2")],
    },
    "dspcount_0x40044d88": {
        "entry": 0x40044d88, "end": 0x40045400, "clamps": [0x40044de4],
        "sites": [(0x40044df8, "h_set_d0")],
    },
    "dspcount2_0x4004fe00": {
        "entry": 0x4004fe00, "end": 0x4004ffc2, "clamps": [0x4004ff1a],
        "sites": [(0x4004ff2e, "h_set_d0")],
    },
    "renamed_0x4006da16": {
        "entry": 0x4006da16, "end": 0x4006da76, "clamps": [0x4006da2e],
        "sites": [(0x4006da40, "h_st_d0")],
    },
}
# NOT included, deliberately:
#   0x4008b904 -- WAS held back here under a WRONG classification ("bank/arrangement serializer, writes a
#     file"). Disproven 2026-09-01: it is the .OT SIDECAR READER (magic DPS1SMPA, opened "r", writes
#     SETTINGS) -- now migrated as CORE wave 19 "otreader_0x4008b8d0".
#   0x4008e638 (clamp 0x4008e620) -- guard is `bls`, whose branch polarity here is not the bail-idiom;
#     audit reports it as REVIEW rather than assuming.
# --- Wave 15: the `bls` NULL-and-dereference pair (found 2026-08-20 after P31 HW) ------------------
# Same family as wave 14 but the guard is `cmpi.l #128,dN` + **bls**, whose ELSE arm builds a NULL
# pointer (`subal aN,aN`) that is then dereferenced with no test. idx<=128 takes the compute path, so
# UI slot 129 survives and UI slot 130 (idx=129) reads a low absolute address -> bus error. This is the
# exception seen on HW at slot 130, in BOTH the load and the AED, because it is one function.
#   0x4008e608: reads STATE@36 (the file handle) and passes it to an indirect I/O call.
# (0x40094044 has the same shape but was ALREADY covered by fnview 0x40093e9c -- clamp raised to #256,
#  add 0x4009405a -> h_st_a0. It only looks unfixed if you scan the STOCK image instead of the build.)
MIGRATE_BLS_NULL = True
BLS_NULL_CORE = {
    "loadhandle_0x4008e608": {
        "entry": 0x4008e608, "end": 0x4008ea36, "clamps": [0x4008e620],
        "sites": [(0x4008e63a, "h_st_a3")],
    },
}
if MIGRATE_BLS_NULL:
    CORE.update(BLS_NULL_CORE)

if MIGRATE_OFFBYONE:
    CORE.update(OFFBYONE_CORE)

# Wave 10 STRIDE4 lea-base sites in the voice-bind resolver 0x4000f450 (see spec (a)). Each `lea #base,a0`
# (41f9 + base) is replaced by `jsr h_s4Nbase_a0` which sets a0 to the A or (B-512) ADJ base per d1=idx,
# so the following `lea a0@(0,idx:l:4),a0` lands in STRIDE4-B[idx-128]. (base, helper) per site.
VOICE_S4_LEA_SITES = [
    (0x4000f4f4, 0x46c93a24, "h_s42base_a0"),   # lea #STRIDE4#2-A,a0
    (0x4000f4fc, 0x46c920a4, "h_s41base_a0"),   # lea #STRIDE4#1-A,a0
]

# Wave 14: FOLDED +0x10e per-slot playback-param sites -- read SETTINGS[slot]+0x10e (a 16-bit param) and
# push it to DSP registers (0x80000110+voice*2 / 0x80001850 / frame a0@(5952)). THREE copies of the same
# per-voice fetch; UNCLAMPED (STATIC branch entered by a type check, not an index bound) -> for idx=128
# they read SET-A[128]+0x10e = OOB garbage -> the DSP renders the high slot with a bad param (silence,
# even though P28 proved the CF fetch delivers real PCM). One is INSIDE the frame-builder ISR (0x4000c6b6).
# Redirect the `addi.l #0x100d5c3e,d0` (product=idx*0x448 in d0) -> jsr h_setf_d0 (folded, self-bounding:
# idx<128 -> A+0x10e byte-identical to stock; 128..255 -> SETTINGS-B+0x10e; >=256 -> A). NO clamp to raise
# (helper self-bounds, exactly like the T24 sites). imm_va = instr_va + 2.
# (Found via tools/census_unmigrated.py; NOTES lists these as the CORE-playback folded trio, never wired.)
SETF_SITES = [0x40004f52, 0x40004ff2, 0x4000c6b6]      # instr VAs of `addi.l #0x100d5c3e,d0`
SETF_A_IMM = 0x100d5c3e

# UI LIST-LENGTH caps (pea #len) that limit how far the slot cursor can scroll. Not clamps -- raw
# immediates. popup static-slot browser: pea 0x80 (128) -> pea 0x100 (256). (found via UI-cap agent)
CAPS = {
    0x40079238: (b"\x48\x78\x00\x80", b"\x48\x78\x01\x00"),   # popup browser static list length 128->256
}

# --- Wave 11: the SLOT-128 SENTINEL landmine (found via the streaming decompilation). In the load/stream
# finalize (0x40093e9c family), the "current streaming slot" global 0x400d7c44 is compared `== 128`; in
# stock (slots 0..127) that block is DEAD, but extending to idx=128 (UI slot 129) ACTIVATES it: it stops
# the slot (jsr 0x40093814 with 0x80) and sets STATE[128]@8 = 1 (0x40094070). The voice-bind resolver
# 0x4000f450 REQUIRES STATE@8 == 0 to sound, so slot 129 is silenced by ANY path (RELOAD or ASSIGN).
# Fix: bump the sentinel above the new ceiling so no valid slot (0..255) matches -> the block stays dead.
#   0x40094028  moveaw #128,a0  (307c 0080)  ->  moveaw #256,a0  (307c 0100)
# (0x400d7c44's real values are 0..255 and -1=none; 256 is never a valid slot.) The 7 other refs
# (0x40093056 uses -1, allocator 0x40094324 writes the real slot, finalize 0x40094076 writes -1) are
# unaffected -- none compares against the literal 128.
SENTINEL_FIX = {
    # (imm_va): (old, new, desc) -- in-place immediate rewrites (not table migrations)
    0x4009402a: (b"\x00\x80", b"\x01\x00", "sentinel moveaw #128->#256 @0x40094028 (STATE[128]@8=1 landmine)"),
    # Wave 12: stop-all loop 0x40093960 `movel #128,d2` counts d2=128..0 calling stop 0x40093814 (migrated).
    # Raise start to 255 so it also stops high slots 129..255. imm at 0x40093960+2.
    0x40093962: (b"\x00\x00\x00\x80", b"\x00\x00\x00\xff", "stop-all loop start #128->#255 @0x40093960"),
    # Wave 13 (assign type-1): open the emitter 0x40023f1c STATIC clamp `cmpa.l #128,a2; bhi` @0x40023f34
    # so idx>=128 reaches the type-1 (open-file) emission instead of bailing. imm at 0x40023f34+2.
    0x40023f36: (b"\x00\x00\x00\x80", b"\x00\x00\x01\x00", "assign type-1 emitter clamp #128->#256 @0x40023f34"),
    # --- Wave 20: p-lock (sample-lock) AUTHORING caps. Playback of high-slot locks already works
    # (mvsb reload + migrated resolver, see emu_seq_plock); only the WRITE caps rejected values >=128.
    # All three are `moveq #127,dN ; cmpl %d3,dN ; bcs/blt <bail>` on the value-to-lock in d3, rewritten
    # in place (same byte count, branch stays at its address with its displacement) to
    # `cmpi.w #254,%d3 ; bhi <same bail>`. Cap is 254, NOT 255: byte 0xff is the no-lock sentinel in the
    # p-lock table 0x46c7dff9, so slot 255 (idx 255 = UI slot 256) is inherently un-lockable -- it can
    # only be a track default. d3 here is the raw value (0..max) so the word compare is safe; -1 aborts
    # via bhi exactly as it did via bcs. hookcheck'd: no branch lands inside any window. The display
    # resolvers the authoring UI needs (FUN_40031d18, FUN_4004ff14) were ALREADY migrated by the
    # descriptor/dspcount waves. NOTE (live-rec fn): the third cap's original left d5=127 loaded, but
    # d5 is dead there (overwritten at 0x400436b6 before any read).
    0x4004fa64: (b"\x72\x7f\xb2\x83\x65\x00\x01\x24", b"\x0c\x43\x00\xfe\x62\x00\x01\x24",
                 "p-lock setter FUN_4004f8dc write cap #127->#254 @0x4004fa64"),
    0x40043682: (b"\x72\x7f\xb2\x83\x65\x00\x00\x94", b"\x0c\x43\x00\xfe\x62\x00\x00\x94",
                 "live-rec p-lock FUN_40043664 cap #1 #127->#254 @0x40043682"),
    0x400436a2: (b"\x7a\x7f\xba\x83\x6d\x74", b"\x0c\x43\x00\xfe\x62\x74",
                 "live-rec p-lock FUN_40043664 cap #2 #127->#254 @0x400436a2 (spec missed this one)"),
}

# --- Wave 12/13: extra code stubs in the free cave [0x400d6b00, 0x400d7000) ---
MIGRATE_GAPS = True                 # GUI enumerators (GAP A) + waveform reader (GAP B) + assign type-1 (GAP C)
GAP_STUBS = 0x400d6b00              # combined blob base (assign_tramp, enum_f1, enum_f2, h_slice_rd)
# hooks: (instr_va, n_bytes_replaced, kind) -- 'jmp14' = jmp stub + 4 nops (14B loop tails);
#   'jmp6' = jmp stub (6B); 'jsr6' = jsr helper (6B).
ENUM_F1_HOOK = 0x40091140          # 14B: addi #1096,d3 ; cmpi #128,d2 ; bne head
ENUM_F2_HOOK = 0x40091378          # 14B: addi #1096,d4 ; cmpi #128,d2 ; bne head
WAVE_RD_HOOK = 0x4009338c          # 6B:  addi #0x46aaa980,d0  (waveform display reader)
ASSIGN_HOOK  = 0x4002426c          # 6B:  jsr pc@(0x40022a28) ; clrl -(sp)   (type-43 send site)

# --- Wave 8: streaming-table 0x46947c56 (stride 24) redirect sites. NOT clamp-gated functions (no idx
# bound in stock -> the helper's own two-sided bound is the guard). Two shapes:
#   ADDA: `adda #base,aN` at instr-VA -> jsr h_t24_aN (product aN=idx*24).  imm_va = instr_va + 2.
#   LEA : `lea base,a0`  at instr-VA -> jsr h_t24off_a0 (d0=idx*24+field).   imm_va = instr_va + 2.
T24_ADDA_SITES = [(0x40016ffe, "h_t24_a1"), (0x40017e3c, "h_t24_a0"),
                  (0x40017ecc, "h_t24_a0"), (0x40017fb6, "h_t24_a0")]
T24_LEA_SITES = [0x40017e56, 0x40017ee6]     # -> h_t24off_a0

# per-slot table base immediates (exact + folded) used by the OOB completeness gate
SLOT_BASES = {0x100d5b30, 0x100d5c3e, 0x100d5c59, 0x46c90a78, 0x46c920a4, 0x46c93a24}


def scan_slot_adds(img, lo, hi):
    """every per-slot BASE-ADD (addi.l/adda.l of a SLOT_BASES immediate, muls-scaled) in [lo,hi)."""
    hits = []
    for k in range(off(lo) + 2, off(hi) - 3):
        v = int.from_bytes(img[k:k + 4], "big")
        if v not in SLOT_BASES:
            continue
        b0, b1 = img[k - 2], img[k - 1]
        is_addi = (b0 == 0x06 and 0x80 <= b1 <= 0x87)
        is_adda = (b1 == 0xfc and b0 in (0xd1, 0xd3, 0xd5, 0xd7, 0xd9, 0xdb, 0xdd, 0xdf))
        if is_addi or is_adda:
            hits.append(BASE + k)
    return hits


def off(a):
    return a - BASE


def assemble_helpers():
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", "out/_d256.o", "tools/patch_dual256.s"],
                   check=True)
    subprocess.run(["m68k-elf-ld", "-Ttext=0x%x" % HELP_AT, "-o", "out/_d256.elf", "out/_d256.o"],
                   capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/_d256.elf", "out/_d256.bin"], check=True)
    nm = subprocess.run(["m68k-elf-nm", "out/_d256.elf"], capture_output=True, text=True).stdout
    sym = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    blob = pathlib.Path("out/_d256.bin").read_bytes()
    for f in ("out/_d256.o", "out/_d256.elf", "out/_d256.bin"):
        pathlib.Path(f).unlink(missing_ok=True)
    return blob, sym


def build_boot_stub():
    """Zero [HOLE_LO,HOLE_HI); then copy each A-table's 128 slots into its B-table (placeholder
    fill so redirected reads see valid data). Ends by running the displaced original instruction
    (lea 0x10000000,a0) and jmp back to BOOT_HOOK+6. Assembled (NOT hand-encoded — a hand-encoded
    bne.s displacement bug that spun the loops was caught by the boot-stub emu-gate)."""
    import subprocess, pathlib
    nz = (HOLE_HI - HOLE_LO) // 4
    # REGISTER-TRANSPARENT: the detour point 0x4001fa64 sits between `d0 = a0+514` (0x4001fa5c) and
    # `cmpl 0x100fff00,d0` (0x4001fa6a) -- the boot code USES d0 (and a1) after the detour. Clobbering
    # them broke system init -> clock reset + empty boot state (seen on w0 AND hiregion). So save every
    # register the stub touches and restore before the displaced instruction. (a0 is overwritten by the
    # displaced `lea` anyway, but we save/restore it too for cleanliness.)
    # ColdFire movem has no predecrement mode -> save d0/a1 (the regs the boot code uses after the
    # detour) with individual pushes. a0 is overwritten by the displaced `lea`, so it needs no save.
    asm = f"""    .cpu 5407
    .text
    move.l  %d0,-(%sp)
    move.l  %a1,-(%sp)
    movea.l #0x{HOLE_LO:x},%a0
    move.l  #0x{nz:x},%d0
1:  clr.l   (%a0)+
    subq.l  #1,%d0
    bne.s   1b
"""
    # STATE-B free-flag init: mark all 128 B slots FREE (status@8 == 1) so the extended allocator
    # (build_alloc_stub) can hand out high slots. The hole zero above left status@8 = 0 (= "used, no
    # handle"); the allocator's free test is `status == 1`. Set only the low byte of the long @8 (rest
    # already zeroed) and leave @36 handle = 0, so FN-CLEAR sees no handle to close (avoids the
    # COPYFILL_STATE garbage-handle OOB). A project load sets loaded B slots back to status 0 (used).
    if not TRACE and STATEB_FREEINIT:
        asm += f"""    movea.l #0x{ST_B:x},%a0
    move.l  #0x{ST_N:x},%d0
5:  move.b  #1,11(%a0)
    lea     44(%a0),%a0
    subq.l  #1,%d0
    bne.s   5b
"""
    # COPY-FILL 0..127 into each B-table (as wave2, which had a working assign-to-128). Zero-init was
    # tried but reverted alongside the load-zeroing: the assign path wants a valid-ish slot struct in
    # SETTINGS-B to overwrite. The sidecar overwrites SETTINGS-B on load when a project.256 exists.
    # TRACE mode skips the copy-fill so the capture slot SETTINGS-B[0] starts zero.
    _fill = []
    if not TRACE and COPYFILL_STATE:                     # STATE/stride4-B: zero-init (default) vs copy-fill
        _fill += [(ST_A, ST_B, ST_STRIDE * ST_N), (S41_A, S41_B, 4 * ST_N), (S42_A, S42_B, 4 * ST_N)]
    if not TRACE and COPYFILL_SET:                       # SETTINGS-B fill only when NOT the persist build
        _fill.append((SET_A, SET_B, SET_STRIDE * ST_N))
    for src, dst, nb in _fill:
        asm += f"""    movea.l #0x{src:x},%a0
    movea.l #0x{dst:x},%a1
    move.l  #0x{nb//4:x},%d0
2:  move.l  (%a0)+,(%a1)+
    subq.l  #1,%d0
    bne.s   2b
"""
    asm += f"""    move.l  (%sp)+,%a1
    move.l  (%sp)+,%d0
    lea     0x10000000,%a0
    jmp     0x{BOOT_HOOK + 6:x}
"""
    pathlib.Path("out/_bs.s").write_text(asm)
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", "out/_bs.o", "out/_bs.s"], check=True)
    subprocess.run(["m68k-elf-ld", "-Ttext=0x%x" % BOOT_STUB, "-o", "out/_bs.elf", "out/_bs.o"],
                   capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/_bs.elf", "out/_bs.bin"], check=True)
    blob = pathlib.Path("out/_bs.bin").read_bytes()
    for f in ("out/_bs.s", "out/_bs.o", "out/_bs.elf", "out/_bs.bin"):
        pathlib.Path(f).unlink(missing_ok=True)
    return blob


def build_alloc_stub():
    """Extended STATIC allocator loop-tail (replaces 16 B at ALLOC_HOOK). At entry d1 = slot index just
    tested (not free), a0 = its STATE ptr. Advance: d1++, then a0 += 44 -- EXCEPT at the A->B boundary
    (d1 hits 128) where a0 is switched to STATE-B base so the walk continues into STATE-B[0..127] (idx
    128..255). Stop at 256 -> NOTFOUND. Byte-identical to stock for idx 0..127."""
    import subprocess, pathlib
    asm = f"""    .cpu 5407
    .text
alloc_adv:
    addq.l  #1,%d1
    cmpi.l  #128,%d1
    bne.b   1f
    lea     0x{ST_B:x},%a0          | boundary: switch to STATE-B base
    bra.b   2f
1:  lea     %a0@(44),%a0            | normal advance (A segment or B segment)
2:  cmpi.l  #256,%d1
    beq.b   3f
    jmp     0x{ALLOC_LOOP:x}        | continue: test next slot's status
3:  jmp     0x{ALLOC_NOTFOUND:x}    | no free slot in 0..255
"""
    pathlib.Path("out/_al.s").write_text(asm)
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", "out/_al.o", "out/_al.s"], check=True)
    subprocess.run(["m68k-elf-ld", "-Ttext=0x%x" % ALLOC_STUB, "-o", "out/_al.elf", "out/_al.o"],
                   capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/_al.elf", "out/_al.bin"], check=True)
    blob = pathlib.Path("out/_al.bin").read_bytes()
    for f in ("out/_al.s", "out/_al.o", "out/_al.elf", "out/_al.bin"):
        pathlib.Path(f).unlink(missing_ok=True)
    return blob


def build_loadloop_stub():
    """Assemble the project-load bulk-loader tail (replaces the 14-byte a2-walk + #128 bound). At entry
    d3 = idx (already incremented for the NEXT slot), a2 = current SETTINGS ptr. Redirect a2 across the
    A->B boundary and extend the bound to 256, then branch back to the loop head or out to the FLEX
    loop. Only reads d3 / writes a2 (the loop body re-sets CC via `tstb a2@`)."""
    import subprocess, pathlib
    asm = f"""    .cpu 5407
    .text
loadloop_walk:
    cmpi.l  #128,%d3
    bne.b   1f
    movea.l #0x{SET_B:x},%a2         | A->B boundary: SETTINGS for idx 128 = SET_B[0]
    bra.b   2f
1:  lea     %a2@(0x448),%a2          | normal walk (SET-A <128 ; SET-B contiguous 129..255)
2:  cmpi.l  #256,%d3
    beq.b   3f
    jmp     0x{LOADLOOP_BODY:x}      | loop back to body
3:  moveq   #0,%d3                   | CRITICAL: the following FLEX loop does `clrb d3` (0x4009090e),
    |                                  which clears only the LOW byte. Stock STATIC exits at d3=128
    |                                  (0x80 -> clrb -> 0); OUR loop exits at d3=256 (0x100), whose
    |                                  bit-8 SURVIVES clrb -> FLEX loop would start at index 256 ->
    |                                  OOB / infinite loop -> hang near end of load. Reset d3<256.
    jmp     0x{LOADLOOP_EXIT:x}      | done -> FLEX loop
"""
    pathlib.Path("out/_ll.s").write_text(asm)
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", "out/_ll.o", "out/_ll.s"], check=True)
    subprocess.run(["m68k-elf-ld", "-Ttext=0x%x" % LOADLOOP_STUB, "-o", "out/_ll.elf", "out/_ll.o"],
                   capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/_ll.elf", "out/_ll.bin"], check=True)
    blob = pathlib.Path("out/_ll.bin").read_bytes()
    for f in ("out/_ll.s", "out/_ll.o", "out/_ll.elf", "out/_ll.bin"):
        pathlib.Path(f).unlink(missing_ok=True)
    return blob


def build_gap_stubs():
    """Assemble the combined Wave-12/13 cave blob at GAP_STUBS: the assign type-1 injection trampoline,
    the two GUI-enumerator A->B boundary redirects, and the waveform-display reader redirect. Returns
    (blob, {name:VA}). Each is register-safe and replicates any displaced bytes."""
    import subprocess, pathlib
    asm = f"""    .cpu 5407
    .text
| --- GAP C: assign type-1 injection. Replaces `jsr pc@(0x40022a28) ; clrl -(sp)` at 0x4002426c; re-emits
| the displaced type-43 send, then emits a type-1 (open-file) via the ready-made emitter 0x40024148, then
| the displaced clrl, then returns. Ordering 43->1 guarantees the file opens from the path type-43 wrote.
assign_tramp:
    jsr     0x40022a28              | displaced: SEND type-43 (was pc-rel; re-emit absolute)
    jsr     0x40024148              | NEW: emit type-1 (open WAV + build slices) for the assigned slot
    clr.l   -(%sp)                  | displaced 0x40024270
    jmp     0x40024272              | return
| --- GAP A: GUI slot-list enumerator F1 (walk ptr d3 += 1096, count d2). At the A->B boundary reset d3
| to SET_B; extend bound to 256; d2 is dead after the loop (return value in d4) so no clrb reset needed.
enum_f1:
    cmpi.l  #128,%d2
    bne.b   1f
    move.l  #0x{SET_B:x},%d3
    bra.b   2f
1:  addi.l  #1096,%d3
2:  cmpi.l  #256,%d2
    beq.b   3f
    jmp     0x40091104
3:  jmp     0x4009114e
| --- GAP A: enumerator F2 (walk ptr d4 += 1096, count d2). Exit MUST `moveq #0,d2` (the following
| 0x40091386 `clrb d2` only clears the low byte; our exit d2=256/0x100 would survive -> corrupt a 3rd loop).
enum_f2:
    cmpi.l  #128,%d2
    bne.b   4f
    move.l  #0x{SET_B:x},%d4
    bra.b   5f
4:  addi.l  #1096,%d4
5:  cmpi.l  #256,%d2
    beq.b   6f
    jmp     0x4009134a
6:  moveq   #0,%d2
    jmp     0x40091386
| --- GAP B: waveform DISPLAY reader. Stock composes d0 = slot*0x3000 + intra, then adds base 0x46aaa980.
| For 128<=slot<256 the writer maps every high slot to the single SLICE_SCRATCH 0x40aba000 (dropping the
| per-slot offset), so the reader must subtract slot*0x3000 and use SLICE_SCRATCH + intra. slot = a2@(21).
h_slice_rd:
    mvz.b   %a2@(21),%d1
    cmpi.l  #128,%d1
    blo.b   8f
    cmpi.l  #256,%d1
    bhs.b   8f
    move.l  %d2,-(%sp)
    move.l  %d1,%d2
    add.l   %d2,%d1
    add.l   %d2,%d1                 | d1 = 3*slot
    moveq   #12,%d2
    lsl.l   %d2,%d1                 | d1 = slot*0x3000
    sub.l   %d1,%d0                 | d0 = intra (drop per-slot offset)
    move.l  (%sp)+,%d2
    addi.l  #0x40aba000,%d0         | SLICE_SCRATCH + intra
    rts
8:  addi.l  #0x46aaa980,%d0         | stock A path (<128)
    rts
"""
    pathlib.Path("out/_gp.s").write_text(asm)
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", "out/_gp.o", "out/_gp.s"], check=True)
    subprocess.run(["m68k-elf-ld", "-Ttext=0x%x" % GAP_STUBS, "-o", "out/_gp.elf", "out/_gp.o"],
                   capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/_gp.elf", "out/_gp.bin"], check=True)
    nm = subprocess.run(["m68k-elf-nm", "out/_gp.elf"], capture_output=True, text=True).stdout
    sym = {q[2]: int(q[0], 16) for q in (l.split() for l in nm.splitlines()) if len(q) == 3}
    blob = pathlib.Path("out/_gp.bin").read_bytes()
    for f in ("out/_gp.s", "out/_gp.o", "out/_gp.elf", "out/_gp.bin"):
        pathlib.Path(f).unlink(missing_ok=True)
    return blob, sym


def build_sidecar():
    """Assemble the sidecar save+load routines (persist SETTINGS-B to <projectdir>/project.256).
    Register-safe: saves the caller-saved regs it uses and REPLICATES the displaced hook bytes.
    Returns (blob, {name:VA}). Save hook replaces 6 bytes at SAVE_HOOK (tstl a3;beqs;jsr a3@) and
    the routine re-runs that logic; load hook replaces the 6-byte moveml at LOAD_HOOK and the routine
    re-emits it verbatim (raw bytes) so register restore is byte-identical."""
    import subprocess, pathlib
    ln = SETB_HI - SETB_LO
    # --- BUG B fix (wave 21): prime STATE-B[idx] for each restored HIGH slot so its voice binds
    # from a trig WITHOUT first opening the AED. On RELOAD, SET-B is repopulated by this raw copy
    # and the per-slot loader never runs for idx>=128, so STATE-B[idx]@16 (buffer/window count) stays
    # 0 and the voice-bind resolver FUN_4000f450 bails (@16<=0 -> per-voice reset = silence). The AED's
    # sampleview FUN_40093980 sets @16 (0x40093c92) + streaming setup, which is why opening the AED once
    # makes the slot sound. We call the SAME sampleview here, only for POPULATED slots (we are already
    # inside the path[0]!=0 branch), with the SAME (slot, 1) args the bulk STATIC loader uses at
    # 0x400908a2. sampleview saves d2-d7/a2-a4, so the loop's d2 (counter)/a2 (TEMP)/a3 (SET-B) survive;
    # it links its own frame so the load fn's fp is preserved. File I/O is live at this hook (the sidecar
    # already opens+reads project.256 here). Toggle PRIME_STATEB_ON_RESTORE=False if it regresses on HW.
    PRIME_STATEB_ON_RESTORE = True
    PRIME_ASM = (f"""move.l  #256,%d0
    sub.l   %d2,%d0                    | idx = 256 - d2  (d2:128->idx128 .. 1->idx255)
    pea     0x1                        | arg2 = 1 (match bulk loader's sampleview call @0x400908a2)
    move.l  %d0,-(%sp)                 | arg1 = slot idx
    jsr     0x40093980                 | sampleview: sets STATE-B @8/@16/@36 + streaming so the voice binds
    addq.l  #8,%sp""" if PRIME_STATEB_ON_RESTORE else "")
    asm = f"""    .cpu 5407
    .text
sidecar_save:
    move.l  %d0,-(%sp)
    move.l  %d1,-(%sp)
    move.l  %d2,-(%sp)
    move.l  %a0,-(%sp)
    move.l  %a1,-(%sp)
    move.l  %a3,-(%sp)
    lea     stream,%a0
    move.l  #16,%d1
1:  clr.l   (%a0)+
    subq.l  #1,%d1
    bne.b   1b
    clr.l   -(%sp)
    clr.l   -(%sp)
    jsr     0x{DIR_OF:x}
    addq.l  #8,%sp
    move.l  %d0,-(%sp)
    pea     fmt256
    pea     pathbuf
    jsr     0x{IO_SPRINTF:x}
    lea     12(%sp),%sp
    move.l  #0x{IO_BUFSZ:x},-(%sp)
    move.l  #0x{IO_BUF:x},-(%sp)
    pea     0x{MODE_W:x}
    pea     pathbuf
    pea     stream
    jsr     0x{IO_OPEN:x}
    lea     20(%sp),%sp
    tst.l   %d0
    bmi.b   2f
    move.l  #0x{ln:x},-(%sp)
    move.l  #0x{SETB_LO:x},-(%sp)
    pea     stream
    jsr     0x{IO_WRITE:x}
    lea     12(%sp),%sp
    pea     stream
    jsr     0x{IO_CLOSE:x}
    addq.l  #4,%sp
2:  move.l  (%sp)+,%a3
    move.l  (%sp)+,%a1
    move.l  (%sp)+,%a0
    move.l  (%sp)+,%d2
    move.l  (%sp)+,%d1
    move.l  (%sp)+,%d0
    tst.l   %a3
    beq.b   3f
    jsr     (%a3)
3:  jmp     0x{SAVE_HOOK + 6:x}

sidecar_load:
    move.l  %d0,-(%sp)
    move.l  %d1,-(%sp)
    move.l  %a0,-(%sp)
    move.l  %a1,-(%sp)
    | (No B-zeroing on load: keep the boot copy-fill so assign-to-128 sees a valid slot struct. A
    | project WITHOUT a project.256 keeps the boot placeholder; the read below overwrites SETTINGS-B
    | when the sidecar exists. Stale-on-project-switch is a known minor follow-up.)
    lea     stream,%a0
    move.l  #16,%d1
4:  clr.l   (%a0)+
    subq.l  #1,%d1
    bne.b   4b
    clr.l   -(%sp)
    clr.l   -(%sp)
    jsr     0x{DIR_OF:x}
    addq.l  #8,%sp
    move.l  %d0,-(%sp)
    pea     fmt256
    pea     pathbuf
    jsr     0x{IO_SPRINTF:x}
    lea     12(%sp),%sp
    move.l  #0x{IO_BUFSZ:x},-(%sp)
    move.l  #0x{IO_BUF:x},-(%sp)
    pea     0x{MODE_R:x}
    pea     pathbuf
    pea     stream
    jsr     0x{IO_OPEN:x}
    lea     20(%sp),%sp
    tst.l   %d0
    bmi.b   5f
    move.l  #0x{ln:x},-(%sp)
    move.l  #0x{SIDE_TEMP:x},-(%sp)   | read the whole file into TEMP (not directly into SET-B)
    pea     stream
    jsr     0x{IO_READ:x}
    lea     12(%sp),%sp
    pea     stream
    jsr     0x{IO_CLOSE:x}
    addq.l  #4,%sp
    | skip-empty copy TEMP -> SET-B: overwrite a slot ONLY when the file slot's path[0] != 0, so an
    | empty/stale project.256 entry does NOT clobber parser-written SET-B. (d2/a2/a3 scratch are
    | restored by the terminal moveml fp@(-576),d2-d6/a2-a4; d0/d1/a0/a1 by the pops at label 5.)
    lea     0x{SIDE_TEMP:x},%a2
    lea     0x{SETB_LO:x},%a3
    move.l  #128,%d2
6:  tst.b   (%a2)
    beq.b   8f
    move.l  %a2,%a0
    move.l  %a3,%a1
    move.l  #274,%d1
7:  move.l  (%a0)+,(%a1)+
    subq.l  #1,%d1
    bne.b   7b
    {PRIME_ASM}
8:  lea     0x448(%a2),%a2
    lea     0x448(%a3),%a3
    subq.l  #1,%d2
    bne.b   6b
5:  move.l  (%sp)+,%a1
    move.l  (%sp)+,%a0
    move.l  (%sp)+,%d1
    move.l  (%sp)+,%d0
    .byte   0x4c,0xee,0x1c,0x7c,0xfd,0xc0     | moveml %fp@(-576),%d2-%d6/%a2-%a4 (verbatim)
    jmp     0x{LOAD_HOOK + 6:x}

    .align 2
fmt256:
    .asciz  "%s/project.256"
    .align 2
pathbuf:
    .space  320
    .align 2
stream:
    .space  64
"""
    pathlib.Path("out/_sc.s").write_text(asm)
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", "out/_sc.o", "out/_sc.s"], check=True)
    subprocess.run(["m68k-elf-ld", "-Ttext=0x%x" % SIDECAR_AT, "-o", "out/_sc.elf", "out/_sc.o"],
                   capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/_sc.elf", "out/_sc.bin"], check=True)
    nm = subprocess.run(["m68k-elf-nm", "out/_sc.elf"], capture_output=True, text=True).stdout
    sym = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    blob = pathlib.Path("out/_sc.bin").read_bytes()
    for f in ("out/_sc.s", "out/_sc.o", "out/_sc.elf", "out/_sc.bin"):
        pathlib.Path(f).unlink(missing_ok=True)
    return blob, sym


def build_trace_stub():
    """Hook memcpy 0x40020898 (movel d2,-(sp); moveal sp@(8),a1 = 6 bytes displaced). ASSUMPTION-FREE:
    record ANY memcpy (any length) whose src OR dst touches the SETTINGS region -- SET-A slots 0..255
    [0x100d5b30,0x1011a330) or SET-B [0x47701a00,0x47723e00) -- into a circular ring of 64 entries
    [caller_PC][dst][src][len]. Header: long[0]=TOTAL memcpy calls (proves the hook fires at all),
    long[1]=count of recorded settings-touching copies; entries at +16, slot=(cnt-1)&63.
    The prior len==0x448 filter recorded 0 -> the paste does NOT copy a whole 0x448 slot via this
    memcpy. This build tells us decisively: if TOTAL>0 but count==0, the paste bypasses 0x40020898
    (need another primitive); if count>0, the last entries before SAVE ARE the copy(src=SET-A[57])
    and the paste (dst=high slot / SET-B), and each carries its caller_PC = the function to migrate.
    Needs zero-init boot. Register-safe; replicates the displaced insns. Read project.256[0:1040]."""
    import subprocess, pathlib
    SA_LO, SA_HI = 0x100d5b30, 0x100d5b30 + 256 * SET_STRIDE   # SET-A slots 0..255
    SB_LO, SB_HI = SETB_LO, SETB_HI
    asm = f"""    .cpu 5407
    .text
trace_mc:
    move.l  %d0,-(%sp)
    move.l  %d1,-(%sp)
    move.l  %d2,-(%sp)
    move.l  %a0,-(%sp)
    movea.l #0x{TRACE_CAP:x},%a0
    move.l  (%a0),%d2
    addq.l  #1,%d2
    move.l  %d2,(%a0)              | header[0] = TOTAL memcpy calls
    move.l  %sp@(20),%d0           | dst (caller sp@(4), +16)
    move.l  %sp@(24),%d1           | src (caller sp@(8), +16)
    cmpi.l  #0x{SA_LO:x},%d0
    blo.b   1f
    cmpi.l  #0x{SA_HI:x},%d0
    blo.b   3f                     | dst in SET-A[0..255]
1:  cmpi.l  #0x{SB_LO:x},%d0
    blo.b   2f
    cmpi.l  #0x{SB_HI:x},%d0
    blo.b   3f                     | dst in SET-B
2:  cmpi.l  #0x{SA_LO:x},%d1
    blo.b   9f
    cmpi.l  #0x{SA_HI:x},%d1
    bhs.b   9f                     | src not in SET-A -> not interesting
3:  movea.l #0x{TRACE_CAP + 4:x},%a0
    move.l  (%a0),%d2             | recorded count
    addq.l  #1,%d2
    move.l  %d2,(%a0)             | header[1] = count++
    subq.l  #1,%d2
    andi.l  #63,%d2
    lsl.l   #4,%d2
    movea.l #0x{TRACE_CAP + 16:x},%a0
    adda.l  %d2,%a0               | -> entry
    move.l  %sp@(16),(%a0)+       | caller_PC (caller sp@(0), +16)
    move.l  %d0,(%a0)+            | dst
    move.l  %d1,(%a0)+            | src
    move.l  %sp@(28),(%a0)        | len (caller sp@(12), +16)
9:  move.l  %sp@+,%a0
    move.l  %sp@+,%d2
    move.l  %sp@+,%d1
    move.l  %sp@+,%d0
    move.l  %d2,-(%sp)
    movea.l %sp@(8),%a1
    jmp     0x{MEMCPY + 6:x}
"""
    pathlib.Path("out/_tr.s").write_text(asm)
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", "out/_tr.o", "out/_tr.s"], check=True)
    subprocess.run(["m68k-elf-ld", "-Ttext=0x%x" % TRACE_STUB, "-o", "out/_tr.elf", "out/_tr.o"],
                   capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/_tr.elf", "out/_tr.bin"], check=True)
    blob = pathlib.Path("out/_tr.bin").read_bytes()
    for f in ("out/_tr.s", "out/_tr.o", "out/_tr.elf", "out/_tr.bin"):
        pathlib.Path(f).unlink(missing_ok=True)
    return blob


def raise_clamp(img, va):
    """cmpi.l #128,dN (0c8N 00000080) -> raise bound so idx..255 pass but OOR still bails.
    bhi(>128,0x62) -> #255 ; bhs/bcc(>=128,0x64) -> #256. Returns the new bound used."""
    o = off(va)
    is_cmpi = img[o] == 0x0c and 0x80 <= img[o + 1] <= 0x87                 # cmpi.l #imm,dN
    is_cmpa = img[o] in (0xb1, 0xb3, 0xb5, 0xb7, 0xb9, 0xbb, 0xbd, 0xbf) and img[o + 1] == 0xfc  # cmpa.l #imm,aN
    assert is_cmpi or is_cmpa, f"not cmpi/cmpa #imm @0x{va:x}: {img[o]:02x}{img[o+1]:02x}"
    imm = int.from_bytes(img[o + 2:o + 6], "big")
    assert imm == 128, f"clamp @0x{va:x} imm={imm} != 128"
    br = img[o + 6]                                          # branch opcode byte after the cmp
    if br == 0x62:            # bhi.s  (idx > 128 bails)   -> allow up to 255
        newbound = 255
    elif br in (0x64, 0x63):  # bcc/bhs / bls variants     -> allow up to 256 (>=256 bails)
        newbound = 256
    else:
        # long branch forms 0x6000.. or others: default to 255 (safe: OOR>=256 still bails via helper->A)
        newbound = 255
    img[o + 2:o + 6] = newbound.to_bytes(4, "big")
    return newbound


def redirect_site(img, imm_va, helper_va):
    """replace the 6-byte add-instruction (starts imm_va-2) with `jsr helper` (4eb9 + addr)."""
    o = off(imm_va - 2)
    b0 = img[o]
    # sanity: opcode is addi.l #imm,dN (06 8N), adda.l #imm,aN (dN fc), or folded addi
    ok = (b0 == 0x06) or (img[o] & 0x01 == 0x01 and img[o + 1] == 0xfc) or (b0 in (0xd1, 0xd3, 0xd5, 0xd7, 0xd9, 0xdb, 0xdd, 0xdf))
    assert ok, f"unexpected opcode @0x{imm_va-2:x}: {img[o]:02x}{img[o+1]:02x}"
    img[o:o + 6] = b"\x4e\xb9" + helper_va.to_bytes(4, "big")


def redirect_lea_site(img, instr_va, helper_va):
    """replace `lea 0x46947c56,a0` (41f9 + addr, 6 bytes) with `jsr helper` (4eb9 + addr). The helper
    reads d0 (idx*24 + field) and sets a0 = A- or B-base so the following `a0@(0,d0)` hits the right
    table. Preserves d0 (only writes a0)."""
    o = off(instr_va)
    assert bytes(img[o:o + 6]) == b"\x41\xf9\x46\x94\x7c\x56", f"not lea 0x46947c56,a0 @0x{instr_va:x}: {img[o:o+6].hex()}"
    img[o:o + 6] = b"\x4e\xb9" + helper_va.to_bytes(4, "big")


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC}")
    img = bytearray(SRC.read_bytes())

    # 0) POOL RECLAIM (build_ramdump.py Step 1) -- MUST run on the clean base BEFORE any B-table
    # code (sidecar/boot literals of 0x40a955e0) is inserted, else the blanket replace clobbers them.
    if POOL_RECLAIM:
        n = img.count(OLD_POOL.to_bytes(4, "big"))
        assert 18 <= n <= 30, f"pool-base count {n} unexpected"
        img = bytearray(img.replace(OLD_POOL.to_bytes(4, "big"), NEW_POOL.to_bytes(4, "big")))
        o = off(POOL_COUNT_AT)
        assert int.from_bytes(img[o:o + 4], "big") == POOL_OLD_COUNT, img[o:o + 4].hex()
        img[o:o + 4] = POOL_NEW_COUNT.to_bytes(4, "big")
        assert img.count(OLD_POOL.to_bytes(4, "big")) == 0, "old pool refs remain"
        print(f"pool-reclaim: base 0x{OLD_POOL:08x}->0x{NEW_POOL:08x} ({n} refs), count "
              f"0x{POOL_OLD_COUNT:x}->0x{POOL_NEW_COUNT:x}; reserve [0x{OLD_POOL:08x},0x{NEW_POOL:08x}) (384 KB)")

    blob, sym = assemble_helpers()

    # 1) install helper family
    assert not any(img[off(HELP_AT):off(HELP_AT) + len(blob)]), "helper cave not empty"
    img[off(HELP_AT):off(HELP_AT) + len(blob)] = blob
    print(f"helpers: {len(blob)} B @0x{HELP_AT:08x} ({len(sym)} syms)")

    # 2) boot-init stub + detour  (toggled: OFF isolates the getter from the boot-zero regression)
    if BOOTINIT:
        stub = build_boot_stub()
        assert not any(img[off(BOOT_STUB):off(BOOT_STUB) + len(stub)]), "boot-stub cave not empty"
        img[off(BOOT_STUB):off(BOOT_STUB) + len(stub)] = stub
        o = off(BOOT_HOOK)
        assert bytes(img[o:o + 6]) == b"\x41\xf9\x10\x00\x00\x00", img[o:o + 6].hex()
        img[o:o + 6] = b"\x4e\xf9" + BOOT_STUB.to_bytes(4, "big")   # jmp stub
        print(f"boot-init: {len(stub)} B @0x{BOOT_STUB:08x}; detour @0x{BOOT_HOOK:08x}; "
              f"zero+fill [0x{HOLE_LO:08x},0x{HOLE_HI:08x})")
    else:
        print("boot-init: DISABLED (diagnostic) — no boot-zero, B-tables uninitialised "
              "(Wave-0 getter path never reads them)")

    # 2b) sidecar: persist SETTINGS-B to <projectdir>/project.256 (save + load hooks)
    if SIDECAR:
        sc, scsym = build_sidecar()
        assert not any(img[off(SIDECAR_AT):off(SIDECAR_AT) + len(sc)]), "sidecar cave not empty"
        assert SIDECAR_AT + len(sc) <= HELP_AT, "sidecar overruns into helper cave"
        img[off(SIDECAR_AT):off(SIDECAR_AT) + len(sc)] = sc
        # SAVE hook: 6 bytes tstl a3(4a8b) beqs+2(6702) jsr a3@(4e93) -> jmp sidecar_save
        o = off(SAVE_HOOK)
        assert bytes(img[o:o + 6]) == b"\x4a\x8b\x67\x02\x4e\x93", img[o:o + 6].hex()
        img[o:o + 6] = b"\x4e\xf9" + scsym["sidecar_save"].to_bytes(4, "big")
        # LOAD hook: 6 bytes moveml fp@(-576),d2-d6/a2-a4 (4cee 1c7c fdc0) -> jmp sidecar_load
        o = off(LOAD_HOOK)
        assert bytes(img[o:o + 6]) == b"\x4c\xee\x1c\x7c\xfd\xc0", img[o:o + 6].hex()
        img[o:o + 6] = b"\x4e\xf9" + scsym["sidecar_load"].to_bytes(4, "big")
        print(f"sidecar: {len(sc)} B @0x{SIDECAR_AT:08x}; save-hook 0x{SAVE_HOOK:08x}->0x{scsym['sidecar_save']:08x}"
              f"; load-hook 0x{LOAD_HOOK:08x}->0x{scsym['sidecar_load']:08x}; persists [0x{SETB_LO:08x},0x{SETB_HI:08x})")

    # 2c) TRACE: hook memcpy to capture the paste's writer PC (dst == SETTINGS-A[128] 0x100f7f30)
    if TRACE:
        tr = build_trace_stub()
        assert not any(img[off(TRACE_STUB):off(TRACE_STUB) + len(tr)]), "trace cave not empty"
        img[off(TRACE_STUB):off(TRACE_STUB) + len(tr)] = tr
        o = off(MEMCPY)
        assert bytes(img[o:o + 6]) == b"\x2f\x02\x22\x6f\x00\x08", img[o:o + 6].hex()  # movel d2,-(sp); moveal sp@(8),a1
        img[o:o + 6] = b"\x4e\xf9" + TRACE_STUB.to_bytes(4, "big")
        print(f"TRACE: {len(tr)} B @0x{TRACE_STUB:08x}; memcpy hook 0x{MEMCPY:08x}->0x{TRACE_STUB:08x}; "
              f"ring64(SET-region, any len) @0x{TRACE_CAP:08x} hdr[total,count] -> project.256[0:1040]")

    # 2d) Wave 8: migrate the PROJECT-LOAD bulk sample-loader loop (pointer-walk -> B at idx 128)
    if MIGRATE_LOADLOOP:
        ll = build_loadloop_stub()
        assert not any(img[off(LOADLOOP_STUB):off(LOADLOOP_STUB) + len(ll)]), "loadloop cave not empty"
        assert LOADLOOP_STUB + len(ll) <= 0x400d7c00, "loadloop overruns cave"
        img[off(LOADLOOP_STUB):off(LOADLOOP_STUB) + len(ll)] = ll
        o = off(LOADLOOP_HOOK)
        assert bytes(img[o:o + 14]) == b"\x45\xea\x04\x48\x0c\x83\x00\x00\x00\x80\x66\x00\xff\x7a", img[o:o + 14].hex()
        img[o:o + 6] = b"\x4e\xf9" + LOADLOOP_STUB.to_bytes(4, "big")   # jmp stub
        img[o + 6:o + 14] = b"\x4e\x71" * 4                              # nop padding
        print(f"loadloop: {len(ll)} B @0x{LOADLOOP_STUB:08x}; hook 0x{LOADLOOP_HOOK:08x} (a2 walk+bound "
              f"-> B@idx128, bound 256); RELOAD now loads STATIC 129..256")

    # 2d2) Wave 19: extended STATIC allocator -- walk STATE-B after STATE-A (on-device high-slot assign)
    if MIGRATE_ALLOC:
        al = build_alloc_stub()
        assert not any(img[off(ALLOC_STUB):off(ALLOC_STUB) + len(al)]), "alloc cave not empty"
        assert ALLOC_STUB + len(al) <= 0x400d7400, "alloc overruns cave"
        img[off(ALLOC_STUB):off(ALLOC_STUB) + len(al)] = al
        o = off(ALLOC_HOOK)
        assert bytes(img[o:o + 16]) == b"\x52\x81\x41\xe8\x00\x2c\x0c\x81\x00\x00\x00\x80\x66\xe8\x60\x16", img[o:o + 16].hex()
        img[o:o + 6] = b"\x4e\xf9" + ALLOC_STUB.to_bytes(4, "big")        # jmp alloc_adv
        img[o + 6:o + 16] = b"\x4e\x71" * 5                                # nop padding
        print(f"alloc: {len(al)} B @0x{ALLOC_STUB:08x}; hook 0x{ALLOC_HOOK:08x} (walk A then STATE-B); "
              f"STATE-B free-init {'ON' if STATEB_FREEINIT else 'OFF'} -> assign to high slot finds a free B slot")

    # 2e) Wave 12/13: install the combined cave blob + its hooks (GUI enumerators, waveform reader,
    # assign type-1 injection). Each hook byte-asserts the stock instruction before rewriting.
    if MIGRATE_GAPS:
        gb, gsym = build_gap_stubs()
        assert not any(img[off(GAP_STUBS):off(GAP_STUBS) + len(gb)]), "gap-stub cave not empty"
        assert GAP_STUBS + len(gb) <= 0x400d7000, "gap stubs overrun cave"
        img[off(GAP_STUBS):off(GAP_STUBS) + len(gb)] = gb
        print(f"gap-stubs: {len(gb)} B @0x{GAP_STUBS:08x} (assign_tramp/enum_f1/enum_f2/h_slice_rd)")
        # GAP A: two 14-byte enumerator loop tails -> jmp stub + 4 nops
        for hook, stub, orig in ((ENUM_F1_HOOK, "enum_f1", b"\x06\x83\x00\x00\x04\x48\x0c\x82\x00\x00\x00\x80\x66\xb6"),
                                 (ENUM_F2_HOOK, "enum_f2", b"\x06\x84\x00\x00\x04\x48\x0c\x82\x00\x00\x00\x80\x66\xc4")):
            o = off(hook)
            assert bytes(img[o:o + 14]) == orig, f"enum hook 0x{hook:x} = {img[o:o+14].hex()}"
            img[o:o + 6] = b"\x4e\xf9" + gsym[stub].to_bytes(4, "big")
            img[o + 6:o + 14] = b"\x4e\x71" * 4
            print(f"  gapA  0x{hook:08x} loop tail -> jmp {stub}(0x{gsym[stub]:08x}) (enum 129..255)")
        # GAP B: waveform reader add -> jsr h_slice_rd
        o = off(WAVE_RD_HOOK)
        assert bytes(img[o:o + 6]) == b"\x06\x80\x46\xaa\xa9\x80", img[o:o + 6].hex()
        img[o:o + 6] = b"\x4e\xb9" + gsym["h_slice_rd"].to_bytes(4, "big")
        print(f"  gapB  0x{WAVE_RD_HOOK:08x} wavebuf read -> jsr h_slice_rd(0x{gsym['h_slice_rd']:08x}) (shared scratch)")
        # GAP C: assign type-1 injection at the type-43 send site
        o = off(ASSIGN_HOOK)
        assert bytes(img[o:o + 6]) == b"\x4e\xba\xe7\xba\x42\xa7", img[o:o + 6].hex()
        img[o:o + 6] = b"\x4e\xf9" + gsym["assign_tramp"].to_bytes(4, "big")
        print(f"  gapC  0x{ASSIGN_HOOK:08x} assign -> jmp assign_tramp(0x{gsym['assign_tramp']:08x}) (emit type-1 open)")

    # 3) migrate the core set
    nsite = nclamp = 0
    for fn, spec in CORE.items():
        for imm_va, hn in spec["sites"]:
            assert hn in sym, f"helper {hn} missing"
            redirect_site(img, imm_va, sym[hn])
            print(f"  site  0x{imm_va-2:08x} add -> jsr {hn}(0x{sym[hn]:08x})   [{fn}]")
            nsite += 1
        if RAISE_CLAMPS:
            for cva in spec["clamps"]:
                nb = raise_clamp(img, cva); nclamp += 1
                print(f"  clamp 0x{cva:08x} #128 -> #{nb}   [{fn}]")
        else:
            print(f"  clamps KEPT at #128 (diagnostic, stock-equivalent)   [{fn}]")
    print(f"migrated: {nsite} sites, {nclamp} clamps")

    # 3a2) Wave 8: redirect the stride-24 streaming-table sites (not clamp-gated; helper self-bounds)
    for instr_va, hn in T24_ADDA_SITES:
        assert hn in sym, f"helper {hn} missing"
        redirect_site(img, instr_va + 2, sym[hn])       # imm_va = instr_va + 2
        print(f"  t24   0x{instr_va:08x} adda #0x{T24_A:08x} -> jsr {hn}(0x{sym[hn]:08x})")
    for instr_va in T24_LEA_SITES:
        redirect_lea_site(img, instr_va, sym["h_t24off_a0"])
        print(f"  t24   0x{instr_va:08x} lea #0x{T24_A:08x},a0 -> jsr h_t24off_a0(0x{sym['h_t24off_a0']:08x})")
    # completeness: no raw 0x46947c56 reference may remain (adda/addi/lea/movea) OUTSIDE the helper
    # family itself (whose A-fallback arms legitimately embed T24_A).
    tb = T24_A.to_bytes(4, "big")
    help_lo, help_hi = off(HELP_AT), off(HELP_AT) + len(blob)
    rem = [BASE + k - 2 for k in range(2, len(img) - 4)
           if img[k:k + 4] == tb and not (help_lo <= k - 2 < help_hi)
           and (img[k - 1] == 0xfc or (img[k - 2] & 0xf1) == 0x41 or img[k - 2] == 0x06)]
    assert not rem, f"un-redirected 0x{T24_A:08x} refs remain: {[hex(x) for x in rem]}"
    print(f"  t24   all {len(T24_ADDA_SITES) + len(T24_LEA_SITES)} sites redirected; 0 raw 0x{T24_A:08x} refs remain")

    # 3a3) Wave 10: voice-bind STRIDE4 lea-base sites -> jsr base-select helper (a0 = A/ADJ base per d1)
    for instr_va, base, hn in VOICE_S4_LEA_SITES:
        assert hn in sym, f"helper {hn} missing"
        o = off(instr_va)
        want = b"\x41\xf9" + base.to_bytes(4, "big")
        assert bytes(img[o:o + 6]) == want, f"not lea #0x{base:08x},a0 @0x{instr_va:x}: {img[o:o+6].hex()}"
        img[o:o + 6] = b"\x4e\xb9" + sym[hn].to_bytes(4, "big")
        print(f"  vbind 0x{instr_va:08x} lea #0x{base:08x},a0 -> jsr {hn}(0x{sym[hn]:08x})")

    # 3a4) Wave 14: folded +0x10e playback-param sites -> jsr h_setf_d0 (self-bounding, no clamp).
    assert "h_setf_d0" in sym, "helper h_setf_d0 missing"
    for instr_va in SETF_SITES:
        o = off(instr_va)
        want = b"\x06\x80" + SETF_A_IMM.to_bytes(4, "big")     # addi.l #0x100d5c3e,d0
        assert bytes(img[o:o + 6]) == want, f"not addi.l #0x{SETF_A_IMM:08x},d0 @0x{instr_va:x}: {img[o:o+6].hex()}"
        img[o:o + 6] = b"\x4e\xb9" + sym["h_setf_d0"].to_bytes(4, "big")
        print(f"  setf  0x{instr_va:08x} addi.l #0x{SETF_A_IMM:08x},d0 -> jsr h_setf_d0(0x{sym['h_setf_d0']:08x})")
    # completeness: no raw folded-A immediate may remain outside the helper blob itself.
    fb = SETF_A_IMM.to_bytes(4, "big")
    help_lo2, help_hi2 = off(HELP_AT), off(HELP_AT) + len(blob)
    rem_f = [BASE + k - 2 for k in range(2, len(img) - 4)
             if img[k:k + 4] == fb and not (help_lo2 <= k - 2 < help_hi2) and img[k - 2] == 0x06]
    assert not rem_f, f"un-redirected folded 0x{SETF_A_IMM:08x} adds remain: {[hex(x) for x in rem_f]}"
    print(f"  setf  all {len(SETF_SITES)} folded sites redirected; 0 raw 0x{SETF_A_IMM:08x} adds remain")

    # 3b) OOB completeness gate: no un-redirected per-slot base-add may remain in ANY opened-clamp
    # function -- else idx 128..255 would flow to a stock add and OOB-write the working region.
    if RAISE_CLAMPS:
        bad = []
        for fn, spec in CORE.items():
            rem = scan_slot_adds(img, spec["entry"], spec["end"])
            if rem:
                bad += [(fn, va) for va in rem]
        if bad:
            for fn, va in bad:
                print(f"  OOB-GATE FAIL: un-redirected per-slot add 0x{va:08x} in opened fn [{fn}]")
            sys.exit("OOB GATE FAILED — a per-slot add is still stock in an opened function; DO NOT FLASH")
        print("OOB-gate: every opened function has 0 remaining per-slot base-adds OK")

    # 3c) UI list-length caps (only meaningful when clamps are open)
    if RAISE_CLAMPS:
        for va, (old, new) in CAPS.items():
            o = off(va)
            assert bytes(img[o:o + 4]) == old, f"cap @0x{va:x} = {img[o:o+4].hex()} != {old.hex()}"
            img[o:o + 4] = new
            print(f"  cap   0x{va:08x} {old.hex()} -> {new.hex()} (list length ->256)")

    # 3c2) Wave 11/12: in-place immediate rewrites (sentinel + slot-count loop bounds)
    if RAISE_CLAMPS:
        for va, (old, new, desc) in SENTINEL_FIX.items():
            o = off(va)
            assert bytes(img[o:o + len(old)]) == old, f"imm @0x{va:x} = {img[o:o+len(old)].hex()} != {old.hex()}"
            img[o:o + len(new)] = new
            print(f"  imm   0x{va-2:08x} {desc}")

    OUT.write_bytes(bytes(img))
    print(f"\n{OUT}: {len(img):,} bytes")
    print("NEXT: emu-gate ->  python3 tools/emu_check.py out/mainos_dual256.bin")


if __name__ == "__main__":
    main()
