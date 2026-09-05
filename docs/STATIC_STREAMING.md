# STATIC Sample-Slot Playback / Streaming Machine — Decompilation & Structural Map

Octatrack MKII OS 1.40C, ColdFire MCF5445x (m68k big-endian). Disassembled from the stock MAIN OS
(VA 0x40000400 = file offset 0). Every structure offset is anchored to the instruction that reads/writes
it. Inferences are marked **[INFER]** with a falsifying test. Produced during the dual-256 STATIC-slot
extension work (make slots 128..255 loadable + playable). Companion: `NOTES.md`, memory
`dual256-setb-pool-clobber`.

---

## 0. Executive summary

A STATIC slot sounds through **two decoupled machines** joined by RAM buffers:

1. **Control path (track-indexed, 0..7 — slot-agnostic):** sequencer trig → `FUN_400977cc` →
   `FUN_40005178` (voice mailbox) → the DSP-frame-builder **ISR at 0x4000aad0** (the address 0x4000c8a4
   is mid-function) → DSP via MMIO 0x20000000 + audio DMA from fixed RAM 0x80005e60. **Nothing on this
   path is indexed by the sample-slot number; no #128 clamp exists here.** Slot 128..255 survives it.

2. **Streaming path (the previously-undocumented part):** a dedicated RTOS task (`FUN_4009203c`,
   dispatched from the task table at 0x40040cfc) resolves *slot → STATE → open file HANDLE*, computes the
   read window from SETTINGS, and refills a **per-voice ring buffer** from CompactFlash. The CF read
   machinery (file-object table, address map, ring pages) is entirely **handle-indexed (handles 1..511)
   and already 256-safe**. The DSP-frame ISR then DMAs from those voice rings.

**The only 128→256 blockers for STATIC playback are ~10 `cmpi #128` sites plus one SENTINEL and two
slot-count loops, all inside the streaming-voice cluster 0x40092xxx–0x40094xxx, and the machine-type
dispatch in the file-open path.** Each guards STATE-A (0x46c90a78, stride 44) or SETTINGS-A (0x100d5b30,
stride 1096). Fixing = relax the bound AND extend/migrate those two tables (reserved-region plan). The
ring/file-object/address-map layer needs **no** change.

---

## 1. End-to-end STATIC streaming data flow

```
sequencer trig (per track 0..7)
 └─ FUN_400977cc(track, action, arg2)          machine-state dispatch (FUN_40097168 → 0..5)
     └─ FUN_40005178(track, cmd, engage)        writes TRACK-indexed voice mailboxes [track*4]:
          0x46c7e9fa (fallback)  0x800018be (voice one-hot)  0x800018de (cmd word)

DSP-frame ISR  FUN@0x4000aad0 .. rte@0x4000d9ae   (control-rate, DSP-interrupt driven)
 ├─ latch ping-pong idx: read DSP MMIO 0x2000001c → 0x800000e0
 ├─ consume mailbox: read+clear 0x46c7e9fa[track*4] (0x4000c8be)
 ├─ per-voice ring bookkeeping in voice struct 0x800049d8 (@48 read,@52 write,@68 base,@36 dir)
 ├─ trigger CF-DMA refill: orl #1,0xfc048010
 ├─ assemble DSP param frame into ping-pong double buffer (bases f(0x800000e0))
 ├─ voice-bind via jump table 0x400d6454[machine_type] → FUN_4000f450 (STATIC types 0,1,4)
 └─ handshake: cmd 0x8C/0x89 → 0x20000004 ; frame ptr → 0x800000ec ; DMA src 0x80005e60 → 0xfc0450d0
         → DSP56xxx renders; audio pulled by DMA from the voice ring RAM

STREAMING TASK  FUN_4009203c (created via 0x40040cfc, blocking-dequeues cmd via 0x40000d00)
 └─ FUN_40094334  STREAM-VOICE ALLOCATOR
      slot(arg sp@72) --cmpi#128 @0x40094350--> STATE-A[slot] (0x46c90a78+slot*44)
      handle = STATE@36 (0x4009438a)
      read window from SETTINGS-A[slot] (0x100d5b30+slot*1096): trim@300, loop@304, slice@316, count@1092
      seek/prefetch: FUN_400180c8(handle, …, sector) ; FUN_40018e40 ; fill voice table 0x46aaa680
 └─ FUN_40093064  PER-FRAME REFILL/DECODE   (reads STATE@36 handle, seeks FUN_400180c8)
 └─ FUN_40093980  START/OPEN WAV            (opens file, writes STATE@36=handle, calls FUN_40016fe8)
 └─ FUN_40093814  STOP/RELEASE              (closes STATE@36 handle)

CF READ / RING  (handle-indexed, 256-safe)
 FUN_400180c8(handle,·,sector)  → file-object[handle] (0x46c8657e, stride 48): @4=pos<<9, @16=ringaddr, @20=pos&mask
 FUN_40017e0c(handle,pos)       → per-handle stream state 0x46947c56 (stride 24) → page# from ring table 0x46147b20
 FUN_40016fe8(handle,staging)   → OPEN/SETUP: allocate map entries in 0x46147b20, link handle
 FUN_40017e78(dest,pos,fmt)     → AUDIO FETCH: walk pages, reload on miss (called from 0x40091fae)
 *0x46c82426(handle,buf,lba)    → CF/ATA sector-read primitive (VFS vtable)
 ring RAM base 0x461079a0 ; page-size config byte 0x46107990 ; format flag 0x46107991
```

**Buffers:**
- **Ping-pong DSP parameter double buffer** — selector long 0x800000e0 (latched from DSP MMIO 0x2000001c);
  frame region 0x80000110 / 0x800010d4 / 0x80000510 (sel*384) / 0x80000cf4 (sel*96) / 0x80003c10;
  committed frame ptr 0x800000ec; frame counter 0x80004800 = (n+1)&3.
- **Audio-DMA source** — fixed RAM 0x80005e60 → DMA reg 0xfc0450d0 (DSP pulls PCM from here).
- **Per-voice streaming ring** — in voice struct 0x800049d8: @68 ring base, @48 read ptr, @52 write ptr, @36 dir.
- **CF streaming ring** — global page table 0x46147b20 (longs = page numbers), ring RAM 0x461079a0,
  page size from *0x46107990 (power-of-two sectors/page **[INFER]**; falsifier: the `subql #1;andl` mask
  at 0x40018154 would corrupt positions if non-power-of-two).
- **Loader scratch** — 0x4ecd3000 (buffered reader), 0x4ece3200/0x4eceb400 (ring staging/dir table).

---

## 2. Per-voice and per-stream STATE

### 2a. Voice struct — base 0x800049d8, stride 168 (0xA8), ×8 (end 0x80004f18)

The **sample-slot number is NOT stored in the voice struct.** The slot is resolved upstream into the
STATE/SETTINGS pointers (@4/@8) and a resolved buffer pointer (@64/@68/@72).

| off | sz | meaning | key R/W VAs |
|---|---|---|---|
| 0 | b | ACTIVE/VALID (0xFF live, 0 free) | R 0x40000eba; W 0xFF 0x4000f912, clr 0x4000685e |
| 1,2 | b | secondary/tertiary state flags | R 0x40000ebe/0x40000ec4 |
| 4 | l | **STATE ptr** (44-B struct) | W 0x4000f4dc (=a5) |
| 8 | l | **SETTINGS ptr** (1096-B struct) | W 0x4000f4e0 (=a4) |
| 12 | l | per-voice channel sub-struct ptr | R 0x4000f48a |
| 16 | l | cached STATE **generation token** (= STATE@20) — cache-validity key | W 0x4000f576; cmp 0x4000f526 |
| 20 | b | machine-type/selector byte (2/3/4) | W 0x4000f5b8/0x40004416 |
| 21 | b | voice-bind key (arg1 low byte = track/note id) | W 0x4000f5bc; R mvzb 0x4000f538 |
| 30 | b | mode byte (= STATE@3) | W 0x4000f5d0 |
| 32/33 | b | slice index / count (clamped to SETTINGS@1092-1) | W 0x4000f67c/0x4000f67e |
| 36 | w | direction/reverse sign flag | R tstw 0x4000ae4e |
| 40/44/56/60 | l | loop range ptrs (A/C start/end) | W 0x4000f794/0x4000f790/… |
| 48 | l | **ring read position ptr** | R 0x4000ae5c; W 0x4000f79c |
| 52 | l | **ring write/end ptr** | R 0x4000ae52; W 0x4000f798 |
| 64 | l | **resolved sample BUFFER ptr** (= from STATE@16) | W 0x4000f820 |
| 68 | l | **ring base ptr** / read-pos ptr | W 0x4000f824 |
| 72 | l | buffer ptr copy | W 0x4000f828 |
| 144 | l | **generation/change COUNTER** (bumped on bind & deactivate) | ++0x4000f834 / ++0x4000687c |
| 152 | l | last-resolved buffer ptr | W 0x4000f838 |

### 2b. STATIC STATE table — base 0x46c90a78, stride 44, per-slot (0..127 stock)

| off | sz | meaning | evidence |
|---|---|---|---|
| 0 | b | format/channel flag; bit0 = mono(→2)/stereo(→4) | `andl #1,a3@` 0x400945d4, 0x40093096 |
| 3 | b | mode (copied to voice@30) | 0x4000f5d0 |
| 5,6,7 | b | channel/voice geometry: `chans=(STATE@6+1)<<STATE@7` | 0x400945c6, 0x40093096 |
| 8 | l | status/busy (voice-bind requires ==0) | tstl a5@(8) 0x4000f4ea |
| 16 | l | length/window (voice-bind requires >0; source of voice@64 buffer) | tstl a5@(16) 0x4000f4e4; 0x40093082 |
| 20 | l | **generation token** (bumped on assign; cached to voice@16) | W 0x400869aa; R 0x4000f576 |
| 36 | l | **open file HANDLE** | R 0x4009438a, R→CF-open 0x400930d2 |
| 40 | l | stream read position / data byte-offset (read `&511`) | R 0x400945bc, 0x4008e850 |

FLEX counterpart: STATE 0x46c922c4, SETTINGS 0x100b14f0 (same strides, clamp #135 = 128 flex + 8 recorder).

### 2c. STATIC SETTINGS table — base 0x100d5b30, stride 0x448 (1096), per-slot

Playback params, per-slice sub-indexed (`lea a1@(0,slice*20)`): **trim/start @300**, **loop/end @304**,
**slice table @316/@312**, **slice count @1092**. Slot-indexed same as STATE.

### 2d. File-object table — base 0x46c8657e, stride 48, **HANDLE-indexed (1..511, 256-safe)**

@0 handle id (valid `cmpi #510` 0x4001657e) · @4 bytepos=`sector<<9` · @8 length/staging DMA ptr ·
@12 rolling cursor · @16 physical ring page addr (=FUN_40017e0c) · @20 `sector&(pagesize-1)` ·
@32 open flag bit0 · @36..46 packed WAV format/date bitfields.

### 2e. Per-handle stream state — base 0x46947c56, stride 24, handle-indexed
@0/@4 list links · @8 base index into 0x46147b20 · @12 span · @16 wrap threshold · @20 wrap increment.
(Note: this table is ALSO the "T24" table migrated per-slot elsewhere — but on the streaming path it is
reached HANDLE-indexed, so 256-safe there. Its per-slot use in FN-VIEW/FN-CLEAR is the migrated one.)

**Where the slot number lives as a full value:** STATE/SETTINGS index registers (slot*44, slot*1096) are
full 32-bit `mulsl` products — never byte-truncated — and the "currently-streaming slot" global
0x400d7c44 is a full long. The slot survives as 128..255 everywhere **except** the `cmpi #128` gates (§5).

---

## 3. Key function pseudocode (VA-cited)

### FUN_400977cc — trig processor (0x400977cc–0x40097920), track-indexed
Reads machine state `FUN_40097168`→0..5, then per (state,action) emits `FUN_40005178(track,cmd,1)` with
cmd flags: 0x80 start, 0xf010 stop, 0x8010|pitch oneshot, 0x10 hold. **No slot index, no #128.**

### FUN_40005178 — voice mailbox writer (0x40005178–0x40005202), track-indexed
Writes 32-bit `movel` to 0x46c7e9fa/0x800018be/0x800018de at `[track*4]`. **Slot never passes here.**

### DSP-frame-builder ISR — FUN@0x4000aad0 … rte@0x4000d9ae
Latch ping-pong 0x2000001c→0x800000e0 → DSP handshake 0x8C/0x89→0x20000004 → program audio DMA
(0x80005e60→0xfc0450d0) → per-voice ring monitor (voice@36/@48/@52/@68, refill via `orl #1,0xfc048010`)
→ mailbox consume 0x46c7e9fa[track*4] → assemble frame into 0x800000e0 double buffer → voice-bind via
jump table 0x400d6454[type] → finalize (0x800000ec, counter 0x80004800). **No #128 / slot handling.**
(0x80001828/29 it reads with `mvsb` is a bank×0x9B340 / pattern×0x18B2 selector, NOT the sample slot.)

### FUN_4000f450 — voice-bind resolver (0x4000f450–0x4000f92c)
```
d3=*0x800000e0; type=*(s8)(0x80000eb4 + d3*8 + voice);   // 0=STATIC
voice=&0x800049d8[arg0*168]; a0=voice@12;
if(type==0){ STATE=0x46c90a78+arg1*44; SETTINGS=0x100d5b30+arg1*1096; } // STATIC
else       { STATE=0x46c922c4+arg1*44; SETTINGS=0x100b14f0+arg1*1096; } // FLEX
voice@4=STATE; voice@8=SETTINGS;
if(!(STATE@16>0 && STATE@8==0 && STATE@20==STRIDE4[arg1])) FUN_40006820(arg0); // else RELEASE → SILENT
voice@16=STATE@20; voice@64=<buf from STATE@16>;
```
Index is the voice-bind key arg1 (slot). **No #128 clamp here** — bound applied by callers (§5).
STRIDE4 gen tables: 0x46c93a24 (STATIC) / 0x46c920a4 (FLEX), index arg1*4.

### FUN_40093980 — START/OPEN WAV (0x40093980–0x40093e68) — the ONLY file-open + handle writer
clamp #128 @0x4009398c; a4=SETTINGS[idx] (0x400939a2); a3=STATE[idx] (0x400939b6); STATE@20++ (0x400939ce);
`jsr 0x40093814` sets **STATE@36 handle**; STATE@8=2 then cleared to 0 on success (0x40093df4); sample-hdr
0x40098ce0 → SIZE. **Sole caller: 0x40084c1a (RELOAD/LOAD-to-slot type-1/case-1). NOT called by ASSIGN.**

### FUN_40094334 — stream-voice allocator (0x40094334–0x400946d6)
slot=sp@72, clamp #128 @0x40094350 → STATE/SETTINGS[slot]; handle=STATE@36 (bail ≤0); sector window from
SETTINGS (trim@300/loop@304/slice@316/count@1092); seek FUN_400180c8 + FUN_40018e40; commit voice entry.

### FUN_400180c8 / FUN_40017e0c / FUN_40016fe8 — CF seek/addr-map/open, all HANDLE-indexed, 256-safe.

---

## 4. Per-slot-indexed table accesses on the streaming path

| VA | base | stride | index src | R/W | role | class |
|---|---|---|---|---|---|---|
| 0x4009307c | 0x46c90a78 | 44 | slot sp@80 | R | STATE (refill) | per-slot |
| 0x400936ca | 0x100d5b30 | 1096 | slot sp@48 | R | SETTINGS slice@312 (play-trig) | per-slot |
| 0x40093832 | 0x46c90a78 | 44 | slot sp@24 | R/W | STATE (stop, close handle) | per-slot |
| 0x400939a2 / 0x400939b6 | 0x100d5b30 / 0x46c90a78 | 1096 / 44 | slot fp@8 | R/W | SETTINGS+STATE (open; writes STATE@36) | per-slot |
| 0x40093f86 | 0x100d5b30 | 1096 | global 0x400d7c44 | R | SETTINGS (finalize) | per-slot |
| 0x40094058 | 0x46c90a78 | 44 | global 0x400d7c44 | R/W | STATE (finalize; sets @8=1,@20++) | per-slot |
| 0x40094362 / 0x4009437e | 0x46c90a78 / 0x100d5b30 | 44 / 1096 | slot sp@72 | R | STATE+SETTINGS (allocator) | per-slot |
| 0x400946f6 | 0x46c90a78 | 44 | slot sp@12 | R | STATE (resolver, sel==0) | per-slot |
| 0x4008ea60 | 0x46c90a78 | 44 | machine idx d6 | R | file-open dispatch STATIC | per-slot |
| 0x400869cc | 0x100d5b30 | 1096 | global 0x400d1668 | R | file-open SETTINGS | per-slot |
| STATE@36 handle → §2d/2e | 0x46c8657e / 0x46947c56 / 0x46147b20 | 48 / 24 / — | **handle 1..511** | R/W | file-object / stream-state / page map | handle (256-safe) |
| 0x46aaa680 / 0x46aaa6e0 | — | 8 | voice 0..7/0..11 | R/W | stream-voice tables | voice (safe) |

---

## 5. What still mishandles idx=128 (given handle open + tables correct)

The CF ring, file-object, address-map, mailbox, frame-builder, voice-bind and render layers all already
handle idx≥128 (handle-/track-/voice-indexed). Remaining defects are in **slot→STATE/SETTINGS resolution**
in the streaming-voice cluster and the file-open dispatch:

**A. Slot-bound relaxation + table migration (`#128`→ceiling, and the guarded access must reach B):**
0x400936b2 (play-trig, SETTINGS), 0x40093820 (stop, STATE), 0x4009398c (open, SET+STATE),
0x40093f6e (finalize, SETTINGS), 0x40094044 (finalize, STATE), 0x40094350 (allocator, SET+STATE),
**0x400946e6 (slot→ptr resolver, STATE — SECOND clamp in 0x40094334, easy to miss)**,
0x40086956/0x400869bc (file-open dispatch), 0x4008ea54 (file-open dispatch STATIC).
Most of these are migrated by the dual-256 build's CORE set; **0x400946e6 must be added to the
slice_0x40094334 clamps** so idx 129..255 aren't NULLed (idx=128 already passes its `bhi`).

**B. Slot-count loop bounds (iterate all slots → must count to ceiling):**
0x4009137e (SETTINGS sweep, `d4 += 1096`, GUI enumerator) and 0x40093960 (`stop-all`, `d2=128→0`
calling FUN_40093814). Loop-bound fix + they touch the migrated tables.

**C. SENTINEL-VALUE conflict (control-flow, NOT a table) — the slot-128 landmine:**
0x40094028: `moveaw #128; cmpal 0x400d7c44` in the load finalize. The global "current streaming slot"
0x400d7c44 is compared `==128`; in stock (slots 0..127) this is DEAD code, but extending to idx=128
(UI slot 129) ACTIVATES it: it `stop(0x80)`s the slot and sets STATE[128]@8=1 (0x40094070) — and
voice-bind REQUIRES STATE@8==0 to sound → **silence for exactly slot 129**. Fix: move the sentinel above
the ceiling (e.g. `moveaw #256` / a value no valid slot takes). The 7 refs to 0x400d7c44 to audit after:
0x40093056, 0x40093eaa, 0x40093f6a, 0x4009402e, 0x4009403e, 0x40094078, 0x40094326. Note -1 (0xffffffff)
is the "no slot streaming" marker (written at 0x40094076); 128 is a distinct stale/max marker.

**D. NOT blockers (do not touch):** ring/file-object/addr-map/CF layer (handle-indexed, `cmpi #510`);
control path (track/voice-indexed); #135 sites (FLEX table 0x46c922c4, 128+8); #255 sites (MIDI/sysex).

---

## Method / confidence notes
- Voice base = 0x800049d8 (stride 168), confirmed `addal #0x800049d8` at 0x4000f484 / 0x4000ae40.
- 0x4000c8a4 is mid-ISR; true entry 0x4000aad0 (ends `rte`, a DSP exception handler).
- STATE@36 = handle confirmed by two reads (0x4009438a file id; 0x400930d2 to CF-open *0x46c82416);
  write on the open path FUN_40093980.
- ASSIGN never opens the file: interactive assign emits only type-43 (attrs→SETTINGS) and type-45
  (stream→STATE, reads empty STATE); only type-1/case-1 (RELOAD/import) runs FUN_40093980. Length shows
  because type-43 writes SETTINGS length independently.
