# RE Log — Octatrack

Record of findings. Each run of `analyze.sh` leaves evidence in `out/`.

## ★ DUAL-TABLE 256-SLOT ARCHITECTURE — precise plan  [2026-08-12]
Decision (user, firm): implement 256 static slots via DUAL-TABLE + a parallel/sidecar project file
for the new slots 128-255 (existing 128-slot format untouched -> retrocompatible). Relocation is
abandoned (proven dead-end: settings are populated by a path the 166 rebased refs don't cover, and
the serializer is structurally 128-slot). This section is the authoritative implementation map.

### MEMORY LAYOUT (verified safe — boot cannot be corrupted)
- Table A (stock, unchanged): STATE 0x46c90a78 (44B*128, ends 0x46c92078=template); static SETTINGS
  0x100d5b30 (0x448*128, ends exactly 0x100f7f30). Flex settings 0x100b14f0 (0x448*136).
- Table B (NEW, in the verified-free DDR hole):
    STATE-B    [0x46c96000, 0x46c97600)   44 * 128   = 5,632 B
    SETTINGS-B [0x46c97600, 0x46cb9a00)   0x448 * 128 = 140,288 B
  198 KB slack above (record array caps hole at 0x46ceb400); 16 KB margin below (state tables end
  0x46c92078). Matches the emu_ddr_free GREEN window [0x46c96000, 0x46cb9a00).
- HOLE IS FREE — proven three ways: scan_hole.py (0 operand-literal refs in [0x46c94074,0x46ceb400));
  emu_ddr_free.py (traced scanners/record-init never write the window); clean-empty relocation
  failure signature. NOT a runtime collision.
- BOOT MEMORY: the boot SRAM clear loop @0x4001fa64 zeroes [0x10000000, 0x100fff00) — includes the
  SRAM settings (boot-zero then project-load populates). It does NOT touch DDR. => Table B in DDR is
  NOT boot-cleared; WE own its init (a boot-zero hook pointed at [0x46c96000,0x46cb9a00) ONLY — never
  the DSP, never SRAM; that mistake was Phase 1). Nothing at boot reads/writes the hole.

### THE ACCESSOR SURFACE (complete census — tools/census_accessors.py + site_facts.py)
Static base 0x100d5b30 is referenced from 47 operand-position sites (43 exact + 3 folded base+0x10e
+ 1 folded lea base+0x129). Flex base 0x100b14f0 has 106 sites — FLEX STAYS IN SRAM, context only.
Split by mnemonic (0x448 is not a power of two, so index scaling is ALWAYS a `muls` -> discriminator):
  * 33 REDIRECT targets: `addi.l/adda.l #base,reg` preceded by muls (base + idx*0x448). 9 helper
    variants cover them: reg in {d0,d1,d2,d3,a1,a2,a3,a4} + one folded {d0,+0x10e}.
      d0x10 d1x1 d2x8 d3x2 a1x1 a2x3 a3x3 a4x2 ; folded d0+0x10e x3.
  * 14 LEAVE: `cmpa/cmpi/lea/move.l# #base` (loop bounds, walk starts, serializer literals) — no mul.

### PER-SITE PATCH (two same-size in-place edits; NEVER changes byte count)
At each CLASS-A static site the stock shape is:  cmpi #128,idx ; bhi NULL ; muls #1096 ; addi #base.
  (1) OPEN THE CLAMP:  `cmpi.l #128,dN` (0c8N 00000080) -> `#256` (…00000100). Same 6 bytes. Only the
      STATIC clamp (#128); LEAVE the flex clamp (#135 / 0x87) alone.
  (2) REDIRECT THE ADD: `addi.l #base,dN` (068N …) / `adda.l #base,aN` (dNfc …) -> `jsr helper_reg`
      (4eb9 <cave>). Same 6 bytes.
Helper (per reg/const), flag-preserving so it is byte-behaviour-identical to the original add for
idx<128:
    add.l  #base,REG              ; (or base+0x10e for the folded trio) — flags as stock add
    move.w %ccr,-(sp)             ; preserve caller-visible flags
    cmp.l  #0x100f7f30,REG        ; idx>=128  <=>  ptr>=static_end
    blo.s  .done
    add.l  #(TABLE_B-0x100f7f30),REG   ; linear remap; preserves folded field offset too
  .done: move.w (sp)+,%ccr ; rts
Why uniform+linear is safe: for idx<128 the helper reproduces the stock pointer AND flags exactly;
for idx>=128 it lands in SETTINGS-B. The folded +0x10e sites remap correctly because the transform
is linear (TABLE_B + (idx-128)*0x448 + 0x10e). Threshold 0x100f7f30 is a COMPARE immediate (not a
relocated pointer), and it is the double-duty static-end/global-base value — fine as a constant.

### ★ INCREMENTAL SAFETY (the key property — every intermediate flash boots)
A site that is NOT yet migrated keeps its `#128` clamp -> NULLs idx>=128 -> EXACT stock behaviour.
So migrate in waves, flashing between:
  Wave 0 (de-risk, no file loader yet): boot-fill SETTINGS-B/STATE-B with a synthetic pattern (e.g.
    copy slots 0..127) and migrate ONLY the core PLAYBACK path; flash; verify slots 128-255 PLAY.
  Wave 1: build the sidecar loader (load 128-255 from the parallel file into table B).
  Wave 2+: migrate UI/display/dialog/serial sites so 128-255 are visible/editable.
Un-migrated sites are always stock-safe. This is how we avoid the slow sysex-recover cycle.

### SITE CLASSIFICATION (from 5 parallel disasm passes; A=redirect, B=leave/serializer)
CLASS A (playback/UI/audio random-access — migrate):
  0x400050d0 0x4000f4b6 0x40021e3e 0x4002263e 0x40023e36 0x40023f4c 0x40024574 0x40024fbc 0x40025000
  0x400252b4 0x40044df8 0x4004ff2e 0x4006da9a(canonical getter) 0x40077e0a 0x40079450 0x400869ce
  0x400936cc 0x40093f88 0x40094380 0x40098d0a 0x400991dc 0x40099412 0x40004f54 0x40004ff4 0x4000c6b8
CLASS B (128-slot serializer / load-save — LEAVE clamped, sidecar handles 128-255):
  0x40084c6e 0x40084cb4 (project serializer, explicit NULL>=128) ; 0x4008996e (save) ; 0x4008b906
  (load+magic) ; 0x400939a4 (sample-load path build). Plus the 14 walk/compare/literal sites.
UNRESOLVED A/B (batch-2 agent wrongly called RTOS; VERIFIED they ARE real dual-table accessors
  `muls; addi #base; cmp type; cmpi #135`): 0x40027728 0x400277f8 0x40029026 0x4004411a (fn ~0x400256b8).
  SAFE DEFAULT = leave (B) for now; promote to A only if that op is needed for 128-255. Leaving them
  cannot break anything (they just NULL>=128).

### CORE PLAYBACK PATH (Wave-0 minimal migration set — from the role analysis)
  0x4006da9a  canonical (type,idx)->slot-settings getter (clamp #128 here is THE one to open first)
  0x400936cc / 0x40093f88 / 0x40094380  audio-engine track activation + slice/loop reader
    (copy slot fields a?@(312)/a?@(1092) into live recorder struct 0x460ba8a4 under interrupt mask)
  0x400991dc / 0x40099412  loop start/length/window setters (interrupt-masked)
  0x40004f54 / 0x40004ff4 / 0x4000c6b8  slot+0x10e playback param -> live DSP regs 0x80000110/1850
Companion tables that travel with settings (may need their own B-table if indexed by slot 128-255):
  STATE 44-byte 0x46c90a78 (status@8 / refcount@20 / handle@36) -> STATE-B already reserved.
  stride-4 tables 0x46c920a4 / 0x46c93a24 — CHECK whether playback indexes these by slot idx>=128.

### ★ FOUR TABLES TRAVEL PER-SLOT (RESOLVED — all indexed in the playback path)
census of the companion bases (same byte-scan) confirms slots use FOUR parallel per-slot tables,
and the CORE PLAYBACK functions index all of them by slot number -> all need a B-table in lockstep
(settings-B alone would leave 128-255 reading garbage runtime state):
  SETTINGS  0x100d5b30  stride 0x448  47 refs (33 redirect)      -> SETTINGS-B 0x46c97600
  STATE     0x46c90a78  stride 44     36 refs                    -> STATE-B    0x46c96000
  stride4#1 0x46c920a4  stride 4      10 refs                    -> B1 (512 B)  [place above SET-B]
  stride4#2 0x46c93a24  stride 4      10 refs                    -> B2 (512 B)
  (flexstate 0x46c922c4 stride44 48refs and tbl 0x46c93c28 are FLEX/other -> untouched, SRAM/A.)
Evidence the playback path indexes STATE-44: refs 0x40093834/0x400939b8 (activation 0x400936cc),
0x4009405a/0x40094364 (slice/loop 0x40094380), 0x40098d1a/0x40099170/0x4009939c (loop setters),
0x4006da40 (getter). stride-4 refs 0x4009935c/0x40099352 sit in the same loop-setter family.
NUANCE (STATE): stock uses INDEX 128 as the TEMPLATE (0x46c92078). So STATE redirect is idx>=129 ->
STATE-B (127 new slots) with template preserved at A[128] — exactly patch_state_helpers_b.s
(ADJ_B=0x46c94a00, LO=0x1600, HI=0x2bf4). => "255 usable" (idx128=template) is the accepted target.
Revised B-table layout (all in the free hole, record array caps at 0x46ceb400):
  STATE-B    [0x46c96000, 0x46c97600)   44*128
  stride4-B1 [0x46c97600, 0x46c97800)   4*128
  stride4-B2 [0x46c97800, 0x46c97a00)   4*128
  SETTINGS-B [0x46c97a00, 0x46cb9e00)   0x448*128    (198 KB slack remains)

### CONFIRMED FACTS for the patch generator  [2026-08-12 cont.]
- TEMPLATE: literal 0x46c92078 appears 0x in the image => the STATE template is reached ONLY via
  idx==128 (getter clamp `cmpil #128,d0; bhi NULL` lets idx==128 through to base+128*44). Therefore:
    SETTINGS redirect threshold = idx>=128  (settings A has no template; A[128]=0x100f7f30 is OOB)
    STATE    redirect threshold = idx>=129  (keep template at A[128]); slot 128 reserved => 255 usable.
  Per-table B index formula: SETTINGS-B[idx-128], STATE-B[idx-129], stride4-B[idx-129 or idx-128 —
  match STATE since they share the same clamp/index d6).
- stride-4 tables ARE slot-indexed (NOT track): in fn 0x40099148, arg d6=slot, `cmpil #128,d6; bhi
  bail` guards STATE-44 (d6*44), stride4#1 (d6*4) AND stride4#2 (d6*4) — ALL three share ONE clamp
  and the SAME index d6. They cache a per-slot POINTER (store `movel a3,a0@`). => opening that clamp
  REQUIRES redirecting all three adds together or d6=255 writes 0x46c920a4+255*4 into flexstate
  (0x46c922c4) = corruption. 4 B-tables stand.
- STATE-44 core-playback redirect sites (addal/addil #0x46c90a78, muls=Y, guard 128):
    0x40077e18(a2) 0x400794fc(d0) 0x40093834(a2) 0x400939b8(a3) 0x4009405a(a0) 0x40094364(a3)
    0x40098d1a(a2,guard135) 0x40099170(a0) 0x4009939c(a0)
- stride-4 core sites (addal, lsl#2 scaled, share clamp): #1 0x4009935c(a0) 0x40099658(d0);
    #2 0x40099352(a0) 0x40099648(d0).
- Companion NOTE: flexstate 0x46c922c4 (stride44, 136) and tbl 0x46c93c28 are flex/other — stay on A.

### OPEN QUESTIONS before Wave 0 (remaining)
1. Sidecar file: format + WHERE to hook load/save (CLASS B serializer region 0x40084xxx is the anchor).
   For Wave 0 (playback de-risk) NOT needed — boot-fill B-tables by copying slots 0..127 (incl the
   stride-4 pointer caches, just to prove plumbing; real per-slot pointers come with the sidecar).
2. Full clamp census: each migrated function has ONE upstream `cmpi #128` (bhi/bhs NULL) that gates
   ALL its per-slot table adds — census these clamp instructions (one per fn) to open them 128->255.
3. UI caps (AUDIO pool list length, per-track SLOT param max) — Wave 2, not needed to prove playback.

### TOOLS (this session)
  tools/scan_hole.py        — occupancy map of a DDR window by operand-position pointer literals
  tools/census_accessors.py — all static/flex base refs, exact + folded, grouped by function
  tools/classify_sites.py   — muls-discriminator: random-access vs walk per site
  tools/site_facts.py       — deterministic reg/const/guard per site -> mechanical patch generation

## Phase 0 — Static recon of the public OS  [COMPLETED ✓ 2026-07-26]

Goal: decide whether the payload is **compressed** (feasible) or **strongly encrypted** (blocking),
and identify where the real ColdFire code lives. **Result: compressed. Firmware obtained.**

Checklist:
- [x] Download official OS 1.40C + record sha256
- [x] Entropy of `.bin` and `.syx`
- [x] elektron-firmware-tool on `.syx` → extracts the raw section, checksums OK
- [x] Confirm container: Octatrack uses **ELEK** (within the supported family)
- [x] Save the decompressed raw as a candidate for disassembly
- [ ] binwalk on the `ELUP` `.bin` (optional; the `.syx` already yielded the raw)

### Results

- **Artifacts** (`OCTATRACK_OS1.40C_dist.zip`, sha256 `370c55a3…73ff0`):
  - `.bin` (459 KB): magic `ELUP`, entropy **uniform ~8.0** (compressed end to end).
  - `.syx` (641 KB): `F0 00 20 3C` (SysEx + Elektron ID) wrapping the **`ELEK`** container.
- **elektron-firmware-tool `-i`**: `device: Octatrack (0x05)`, `version 1.40C`,
  container `ELEK` 469834 B, **section id 3 "MAIN OS" → 1,112,560 B decompressed**, checksums OK.
- **Decompressed raw** `out/raw/section_3_MAIN_OS.bin` (1,112,560 B):
  - Mean entropy **5.5** (real code+data, NOT encrypted); only 3.8% of windows are high.
  - **2908 readable strings**: UI menus, error codes, `/octatrack_factory_os.bin`.
  - m68k big-endian disassembly OK: prologue `lea -0x1c(a7),a7` + `movem.l d2-d7/a2,(a7)`.

### Memory-map clues (from absolute refs in the code)

- **Data/BSS in SDRAM base `0x40000000`** (refs to `0x400b9650`, `0x400b9654`, `0x400dea48`).
- Initial stack loaded from ~`0x48000000`.
- **Code load** base: still to be determined (the raw starts in code, not in a vector table).
  Strategy: locate where the code references its own strings to fix the base address.

## Phase 1 — Static disassembly  [IN PROGRESS]

- Target: **ColdFire / m68k, big-endian**.
  - radare2: `./disasm.sh` (already configured with base and arch).
  - Ghidra: processor `68000`, big-endian, base `0x40000400`; then run
    `tools/ghidra_import.py` to define strings/pointers and populate xrefs.

### BASE ADDRESS DETERMINED ✓  =  `0x40000400`

Empirical method (`tools/find_base.py`, not an assumption): correlate the offsets of
the 2607 strings in the file against the absolute 32-bit pointers (high byte 0x40).
The sweep of candidate bases gave an unambiguous peak:

| candidate base | strings with a direct pointer |
|---|---|
| **0x40000400** | **1441** |
| 0x400003dc | 291 |
| 0x40000424 | 290 |

- Peak 5× over the second → solid base. Image in SDRAM `0x40000000` + `0x400` of
  header/vectors; the decompressed MAIN OS section maps at `0x40000400`.
- Data/BSS at `~0x400bxxxx` (consistent: `0x400b9650 - 0x40000400 = 0xb9250`, inside the image).
- Verified in r2: at `0x40000400` the prologue `lea -0x1c(a7),a7` + `movem.l` appears,
  and there is code `move.l #0x400b3349,d0` loading pointers to strings as immediates.
- Artifacts: `out/base.txt`, `out/pointers_to_strings.csv` (**1993 sites** ptr→string).

### Function → UI-strings map ✓  (`tools/string_func_map.py` → `out/string_function_map.txt`)

Detects string-pointer loads in the code (`pea`/`lea`/`move.l #imm`) and walks back
to the function prologue (`LINK`/`lea -n(a7),a7`). **619 functions** anchored to strings,
1060 refs in code. Key functions already identified by name:

| Function | What it is (by its strings) |
|---|---|
| `0x40086d7a` | **Serializes project settings** — 58 keys (`MIDI_CLOCK_SEND`, `MASTER_TRACK`, `MAIN_LEVEL`…) |
| `0x4001fc1e` | **Error handler** — 49 strings (`WAV/AIFF PARSE ERROR`, `SAMPLE NOT UNLOADED`…) |
| `0x400867e0` | Writes the `[SAMPLE]` section of the project file (OctaLib format) |
| `0x40069424` | `FORMAT CARD` handler |
| `0x400645ce` | `SAVE PROJECT` handler |
| `0x40022fdc` | `COLLECT SAMPLES` handler |

This **connects the firmware to the already-documented file format**: the settings
function emits exactly the project-file keys in plain text.

### Decompilation in Ghidra ✓  (12.1.2, language `68000:BE:32:Coldfire`, base 0x40000400)

Project in `out/ghidra_proj`. Scripts: `tools/GhidraDecompile*.java` (Ghidra 12 doesn't ship
Jython → use Java). Logs: `out/ghidra_decompile*.log`.

**Finding: shared dialog constructor `FUN_4006d57c`**
Reconstructed signature: `(title, num_options, char **options, default, confirm_callback)`.
Creates a popup (measures text with the font at `DAT_400ba876`, window via `FUN_4005829c`) and
stores the confirmation callback. Every action menu calls it with its label.

**OS UPGRADE flow traced end to end** (`FUN_400636bc`):
```c
if (FUN_400448dc() == 0)   FUN_40063660(0);          // no playback -> direct upgrade
else {                                                // with playback:
    opts = {"PLAYBACK WILL BE", "STOPPED. CONTINUE?"};
    FUN_4006d57c("OS UPGRADE", 2, opts, 3, FUN_40063660);  // dialog; on confirm -> FUN_40063660
}
```
→ **`FUN_40063660` = the actual OS update routine** (next target to decompile).

**ColdFire hardware registers identified** (in the init/main function `~0x4001fc1e`):
- `0x20000008` — status register polled at boot (`while ((*0x20000008 & 6)==0)`).
- `0xfc04xxxx` — on-chip peripheral space (MBAR) of the ColdFire (init writes).
- App data/BSS at `0x460exxxx` and `0x46c8xxxx` (in addition to the `0x400bxxxx` of the image).

**Known limitation**: the ColdFire decompiler fails ("Cannot properly adjust input
varnodes") on large functions with complex frames (e.g. `project_settings_serialize`
5388 B, `project_sample_section` 1434 B). The disassembly does work; analyze them at the ASM level.

### Complete OS UPGRADE chain (decompiled) ✓  — logs `out/ghidra_{osupgrade,flashwriter,apply,program}.log`

```
OS UPGRADE menu
  └─ FUN_400636bc   confirms "PLAYBACK WILL BE / STOPPED. CONTINUE?" (via FUN_4006d57c)
      └─ FUN_40063660 (os_upgrade)  stops audio, "WORKING PLEASE WAIT", QUEUES a deferred task:
          └─ FUN_4006370c  scans the CF, picks the OS file, validates existence
              └─ FUN_40080434 (os_apply_flash)  critical section + calls the loader and maps errors
                  └─ FUN_4007f748 (os_file_program)  << THE CORE: parses/deobfuscates/verifies >>
```

**`FUN_4007f748(path, mode)` — OS file format (`.bin`, magic ELUP):**
- `fopen`; if it fails → `-1 IO_ERROR`. Reads size; `payload = filesize - 0xC` (12 B header).
- `payload > 0x100000` (1 MiB) → `-3 LENGTH_ERROR`.
- Header (words): `[0]`=magic (`== DAT_400a966c`), `[1]`=feedback seed,
  `[3]`=flags (bit `0x800000` selects variant) + checksum, `[4]`=version material. Payload from `[2]`.
- **Obfuscation = XOR cipher with feedback** (not compression, not real crypto):
  each word: `p ^= 0x9E3B16A2` (or `0x764E28CA` if flag) → rotate/byteswap → `k ^= prev_cipher ^ x`.
  Constants **fixed and embedded** → the `.bin` is fully decodable offline. (This explains the
  uniform ~8.0 entropy of Phase 0: it's this XOR stream, not compression.)
- **Integrity = additive checksum** (sum of deobfuscated words) compared with the stored value;
  mismatch → `-4 CHECKSUM_ERROR`. **There is NO cryptographic signature** (confirms Phase 0: modifiable firmware).
- **Model/version gating**: `< "0156"` (0x30313536) → `-5 MK1_OS_NOT_ALLOWED`;
  `< "0178"` (0x30313738) → `-6 CAN_NOT_DOWNGRADE`. Version = packed ASCII.
- `mode=1` → only returns the version (for the pre-scan). `mode=0` → deobfuscate+verify (commit).
- On successful completion: `FUN_4007fe80(0xffffffff,...)` finalizes/reboots into the new OS.

### Offline `.bin` decoder ✓✓✓  (`tools/bin_decode.py` + `tools/decode_elek.c`)

Reimplementation of `FUN_4007f748`. Constants extracted from the OS image:
`magic=0x454C5550 ("ELUP")`, `C3=0x360FA955`, `C7=0xEF4A9AB6`, XOR `0x9E3B16A2`/`0x764E28CA`.

**Double validation:**
1. `bin_decode.py` deobfuscates the `.bin` and **the additive checksum matches** (`0xa85be7ef`) — the
   SAME check the firmware performs → deobfuscation demonstrably correct.
2. The deobfuscated payload is an **`ELEK0178`** container (identical to the one in the `.syx`). `decode_elek.c`
   (reuses the tool's `ap_depack`/aPLib) decompresses it → **1,112,560 B, SHA256 `164f3122…`**,
   **byte-identical to the MAIN OS extracted from the `.syx`**.

**Full chain reconstructed and verified end to end:**
```
.bin  = [ELUP hdr][seed] + XOR-feedback( [len] + ELEK(aPLib(MAIN_OS)) ) + checksum
.syx  = SysEx 7-bit( ELEK(aPLib(MAIN_OS)) )
                                    → both → the SAME MAIN OS (164f3122…)
```
No cryptographic signature at any layer: reversible XOR obfuscation + additive checksum + aPLib.

### Full storage stack (decompiled) ✓ — logs `out/ghidra_{commit,hw,drv,fac,prim,txn,disp,ata}.log`

Traced from the UI down to the ATA registers. **The OS "flash" = writing to the CompactFlash (ATA)**;
the driver is the ColdFire ATA block stack, NOT an internal NOR flash.

```
os_apply_flash (FUN_40080434)
  └─ FUN_400323a0   dispatches via driver vtable: (*(obj+0x10))(0)   [obj=_DAT_460d16cc]
      └─ FUN_400158cc  = method +0x10 → sends ATA command 0xE0 (STANDBY IMMEDIATE: flush/park before reboot)
          └─ FUN_4001568c  QUEUES the command (async ring, 0x16 B entry) + reserves event (_DAT_460babfc) + waits
              └─ FUN_40015098  DISPATCHER: drains the queue and dispatches by ATA opcode:
                    0x20 READ SECT · 0x30 WRITE SECT · 0x87 · 0xC0 · 0xC8 READ DMA · 0xCA WRITE DMA · 0xE0 STANDBY
                    └─ FUN_40014c48 (0x30 WRITE SECTORS)  ← ATA task-file registers @ 0x90000000 (FlexBus)
```

- **Factory driver** `FUN_40015e28`: builds the vtable at `&DAT_46c85c76` (methods 0x400157xx/0x400158xx)
  and **detects the hardware variant** by reading an IDENTIFY-type descriptor (offsets 0x62/0x6a/0x146/0x7e/0xb0).
- **Confirmed hardware map**:
  - ATA host registers (control/config) in ColdFire MBAR: `0xFC04_51xx`, status `0xFC0A_4039`.
  - ATA task-file (data/LBA/cmd/status) in FlexBus window `0x9000_00xx`
    (data=0xa0, seccount=0xa8, lba=0xac/b0/b4, dev=0xb8, cmd=0xbc, status=0xd8).
  - **The MCF5445x has an on-chip ATA controller → corroborates the ColdFire CPU from Phase 0.**
- **RTOS confirmed (not bare-metal)**: async I/O via command queue with event-based completion
  (bit pool at `_DAT_460babfc`), a worker that drains the queue. There are tasks and synchronization.

## Musical layer — audio/sequencer engine (decompiled) — logs `out/ghidra_{play,trk,voice,voice2}.log`

Engine data map (all in the RAM window `0x80000000` = hot state):

| Structure | Address / layout | What it is |
|---|---|---|
| Per-track voice state | base `0x800049d8`, stride `0xA8`, 8 tracks | live audio voice; byte[0] = active |
| "Active voice" query | `FUN_40000ee0(t)` reads `0x800049d8[t*0xA8]` | 0=inactive, 1/2 per `0x8000184a` |
| "Something sounding" query | `FUN_400448dc` walks the 8 tracks | used by OS-upgrade to block |
| MIDI tracks state | `0x80006500[t]`, global `0x800065b8` | MIDI mute/active flags |
| Voice command mailboxes | `0x46c7e9fa`/`0x800018be`/`0x800018de` `[t*4]` | `FUN_40005178` queues per-track commands |
| Per-track pattern data | `_DAT_46c82456 + pat*0x18b2 + trk*0xc` (+0x8f385) | sequenced data (trigs/params) |
| Globals | current track `0x100b14cc`, current pattern `0x80000003` | live selection |

**Confirmed architecture — same pattern as storage**: `FUN_40005178` (command voice)
writes mailboxes in RAM, consumed asynchronously by an ISR/feeder that feeds the DSP56xxx.
Hardware (DSP) behind an async boundary, just as ATA was behind the command queue.
→ reinforces the RTOS model: producer (sequencer) / consumer (audio ISR) decoupled by RAM.

## RTOS identified: Elektron's PROPRIETARY microkernel ✓ — log `out/ghidra_kern.log`

Not MQX/ThreadX/VxWorks/Nucleus. Negative evidence: **zero** copyright/version/API strings
of a commercial RTOS. Only banner: `ElektronOctatrack DPS-1 0002 / FROM WWW.ELEKTRON.SE`
(DPS-1 = internal Elektron platform, shared across their ColdFire machines).

Positive evidence — preemptive priority-based microkernel, decompiled primitives:
- **`FUN_40000818` (wait_event)**: if `*ev < 1`, links the current TCB into a wait list, state
  `TCB[0x13]=0` (blocked), and executes **`TRAP #0`** = context switch via m68k software trap.
- **`FUN_40000c3c` (post/queue)**: writes ring buffer; if a task is waiting, marks it `TCB[0x13]=1`
  (ready), inserts it into the **priority ready queue** (doubly-linked circular lists), and forces
  reschedule with `0xFC04_C010 |= 0x800` (ColdFire interrupt controller).
- **TCB**: state@0x13, priority@2, list pointers@0/1. Current task = `_DAT_800068fc`.
  Top-priority pointer = `_DAT_800068d8`.

**Unifies everything above**: the ATA stack's "async queues" and the audio engine's "voice mailboxes"
ARE this kernel's message/event queues. A single microkernel, used throughout the firmware.

## DSP interface and audio pipeline ✓ — logs `out/ghidra_{dsp,frame}.log`, r2 disasm

**Physical DSP interface: MMIO at `0x20000000`** (revealed by r2; Ghidra's ColdFire module
fails on this hot-path code). Handshake registers:
- `0x2000_0004` command/status (writes `0x8C`, polls busy bit7 until ack)
- `0x2000_0008` status ("DSP ready": boot polled `while ((*0x20000008 & 6)==0)`)
- `0x2000_001c` frame index reported by the HW → selector of the double buffer `0x800000e0`

**Full pipeline (control path):**
```
sequencer trig
 → FUN_40005178 writes voice mailbox (0x46c7e9fa / 0x800018be) in RAM
   → FUN_4000c8a4 (frame builder, control-rate) consumes mailboxes, updates 8 voices,
      assembles a parameter FRAME in a double buffer in shared RAM 0x80000000 (ping-pong 0x800000e0)
     → handshake via 0x20000000 (reads frame idx 0x1c, writes cmd 0x8C to 0x04, polls busy)
       → DSP56xxx reads the frame from 0x80000000 and synthesizes (samples, time-stretch, filters, FX)
```

**ColdFire↔DSP split**: ColdFire = control (RTOS, sequencer, assembles voice parameters).
DSP56xxx = signal (real-time audio). Synchronized by **double buffer + register handshake**.

### Consolidated memory map

Segment table derived from a static scan of every real address-operand reference in the MAIN OS
(lea/movea/pea/adda/move.l#imm/jsr/jmp), **2026-08-03**. Two RAM chips: a 128 MB main DDR at
`0x40000000` and a **separate ~1 MB metadata SRAM** at `0x10000000` (different chip-select).

| Segment | Range | Size | Use |
|---|---|---|---|
| **Metadata SRAM** | `0x10000000`–`~0x10100000` | ~1 MB | Sample **settings** tables (0x448 B/slot): FLEX `0x100b14f0`, STATIC `0x100d5b30`; project globals (name ptr `0x100f8378`). Highest real ref `0x100fff04`. **Separate small chip — reads past ~`0x10100000` are UNMAPPED → bus fault** (this is what froze the RAM probes). Boxed-in and full → no room to grow the tables here. |
| DDR: code + BSS | `0x40000000`–`~0x40200000` | ~2 MB | OS image (`@0x40000400`, 1.1 MB) + BSS/globals + the free **code cave** `0x400d64da`–`0x400d7c3b` |
| DDR: bank buffers | `0x400e21e0`–`0x40a955e0` | ~10 MB | 16 resident banks (stride `0x9b340`) |
| DDR: flex pool | `0x40a955e0`–`~0x46000000` | ~85 MB | Flex sample RAM **+ recorder buffers** (the shared 85.5 MB budget) |
| DDR: app structs | `0x46000000`–`~0x46ceb400` | ~13 MB | Recorder metadata (`0x46c939cc`), **state** tables (0x2c B/slot): STATIC `0x46c90a78`, FLEX `0x46c922c4`; streaming tables `0x46c7fe24`/`0x46c7ff42` |
| DDR: ~"free" tail | `~0x46d00000`–`0x48000000` | ~19 MB | Mapped but unreferenced in the static image — **NOT free**: a hardware canary showed it (and every unreferenced DDR/SRAM span tried) is used by the heap/pool at runtime. **"Unreferenced ≠ free."** |
| **DDR: RESERVED** | `0x40a955e0`–`0x40af55e0` | **384 KB** | The old flex-pool base. **Reclaimed** by moving the pool physically +64 pages (base `0x40a955e0`→`0x40af55e0` at all 23 code refs; page count `0x390A`→`0x38CA` to keep the top fixed). Now sits below the pool → referenced by nothing → **hardware-canary-confirmed reserved** across record / sample-load / pattern & project changes. The fixed home for the extended static tables (274 KB settings + 11 KB state = 285 KB). |
| DSP shared RAM | `0x80000000`–`~0x80010000` | ~64 KB | Voice state array (`0x80004dc8`, stride `0xA8`), double-buffered DSP frames, selector `0x800000e0`, mailboxes |
| DSP coprocessor | `0x20000000` | — | cmd `0x2000_0004`, status `0x08`, frame index `0x2000_001c` |
| ATA / CompactFlash | `0x90000000` | — | ATA task-file via FlexBus |
| Peripherals (MBAR) | `0xFC000000` | — | ColdFire on-chip: **DDR controller `0xFC0B8000`/`0xFC0BC000`**, ATA host `0xFC0451xx`, interrupt ctrl `0xFC04C010` |

DDR total = **128 MB** (`0x40000000`–`0x48000000`): pool base `0x40a955e0` + 85.5 MB ≈ `0x46000000`,
app structs to `~0x46ceb400` → ~108 MB used, next power-of-two bank is 128 MB → a ~19 MB mapped tail.

**Lesson (why the RAM probes froze):** the metadata region is a small (~1 MB), fully-used, separate
chip — not the 8–16 MB span earlier guessed. Bulk-reading `0x10000000..0x10800000` crossed into
unmapped space → bus fault → "corrupt" noises + freeze. Only bulk-read within the **contiguous DDR**
(`0x40000000`–`0x48000000`); never speculatively read the metadata SRAM past `~0x10100000`.

### Reclaiming fixed RAM from the flex pool  [2026-08-03, hardware-confirmed]

Goal: a fixed 285 KB home for the extended STATIC tables (128→256). No RAM is *free* to
reserve — every unreferenced span is dynamic heap/pool at runtime (proven by canary: DDR
`0x47800000` and SRAM `0x10020000` both got overwritten under operation). The only reliable
way is to **reclaim** from a known allocator.

The flex pool is a paged allocator: `phys = base(0x40a955e0) + pagemap[i]*0x1800`; total pages
in the literal `move.l #0x390A, d6` at `0x40096f80` (→ `0x80006920`); page size `0x1800`.
Reserving *logical* pages (advancing the alloc pointer `0x8000691c`) does NOT reserve a fixed
*physical* address — the page-map scrambles it (canary confirmed: base still used).

**What works — move the pool's physical base up:**
- Rewrite the pool base `0x40a955e0` → `0x40af55e0` at **all 23 code operands** (blanket
  4-byte replace; they are `lea`/`adda`/`addi.l`/`move.l#`/`pea`/`cmpa.l`, no data refs).
- Reduce the page count `0x390A`→`0x38CA` (@`0x40096f82`) so the pool *top* stays put.
- The pool now lives at `0x40af55e0`; `[0x40a955e0, 0x40af55e0)` (384 KB) sits below it,
  referenced by nothing → reserved. **Deterministic, no mapping ambiguity, no canary needed.**

Hardware: audio / recording / sample-load / pattern & project changes all work (the move was
clean — 23 refs is the complete set), and a canary at `0x40a955e0` stayed 100% intact through
heavy operation. `tools/build_ramdump.py` does the relocation; the reserve region is the home
for the relocated static tables. Cost: 384 KB (0.4%) off the ~85.5 MB pool — graceful (worst
case one fewer sample fits when the pool is maxed).

### Moving the settings table to DDR — the CRASH is SOLVED  [2026-08-04, hardware-confirmed]

The earlier "DSP-read" theory was **WRONG** (the DSP is 24-bit, cannot deref a 32-bit CPU
pointer; canary/writethrough/zero-init tests all ruled out memory-behaviour causes). The real
cause was **contiguity**, found by classifying every ref by opcode:

The per-slot (`0x448`) settings live in **one contiguous block** of two adjacent tables:
- **flex** table `0x100b14f0`, **136 slots** (`0x100b14f0 + 136*0x448 == 0x100d5b30`)
- **static** table `0x100d5b30`, **128 slots** (ends at `0x100f7f30`)

So each boundary address is **shared** with a neighbour, and some loops walk the two tables
**as one array** (e.g. `a4 = 0x100b14f0`, `+0x448` until `cmpa #0x100f7f30`). Relocating the
static table alone (`build_ramdump.py`/`build_2afix`) left flex in SRAM and static in DDR →
every combined/boundary loop ran away (start in SRAM `0x100b14f0`, bound in DDR) → **runaway
loop → "corrupt noises" + hang right after the LOADING popup** (the DSP starves while the CPU
spins). This is why zero-init / writethrough / the 2-`pea` fix all failed — none touched the
bad loop bounds.

**Fix — `tools/build_blockmove.py`:** move the ENTIRE block `[0x100b14f0, 0x100f7f30)`
(264 slots, `0x46A40` = 283 KB) to DDR `0x40a955e0` by one delta (`+0x309e40f0`), so every
internal offset is preserved and flex-only, static-only AND combined loops all stay consistent.
Relocate all **166** operand refs in the block; keep only the two `pea 0x100f7f30` base-loads
(that address doubles as a global struct base ABOVE the block, which does not move). 0 false
positives (every relocated operand is even-aligned and a clean instruction operand). Plus
`tools/patch_bootzero.s` zeroes the reserved DDR window at boot (the stock boot conditionally
clears the SRAM `[0x10000000, 0x100fff00)` the block came from, at `0x4001fa64`).

Hardware: **no more crash/hang** — the project load now runs stably; corrupt noises are gone.
The contiguous-block relocation is the correct technique for the 128→256 extension.

**Boundary disambiguation rule** (needed by any block relocation): at a boundary address shared
between the block and a neighbour, the instruction TYPE decides ownership. At `0x100d5b30`
(flex-end / static-base) `cmpa`/`cmpi` are the FLEX table's end bound (keep), base-loads/arith
are the static base (relocate) — 7 boundary refs (5 `cmpa` + 2 `cmpi`). At `0x100f7f30`
(static-end / global-base) `cmpa`/`cmpi`/arith are static loop bounds (relocate), `pea`
base-loads are the global (keep). Moving the WHOLE block makes `0x100d5b30` internal, so only
the top global (2 `pea`) needs keeping.

**The block has METADATA slots past 127 — extend to slot 130.** After the crash fix the load
stayed stable but reported one early `FILE NOT FOUND` and loaded nothing. Root cause (found via
`tools/build_pathlog.py`, which hooks all 7 path-taking FS funcs and logs paths to a DDR ring
buffer dumped on CHANGE — the load's real open is `0x4001b724 = *(0x46c823fa)`, tag `7`): the
load was resolving the project path to `/universi/UNTITLED` — a folder that doesn't exist (the
set has `altre-galassie` + `_2`). The project NAME was read EMPTY:

    FUN_40025230: ... lea 0x100f8378,a0 ; tstb (a0) ; beq -> sprintf(buf,"%s/UNTITLED",set)

`0x100f8378` (the project-name buffer) is `static_base + 129*0x448` = **slot 129** — a METADATA
slot ABOVE the 128-slot table. The static "table" has extra metadata slots (128-129: project
name `0x100f8378`, other fields `0x100f8480`/`0x100f8584`/…, and the CF-card id) that are
accessed BOTH block-relatively (`static_base + slot*0x448`, moved by the relocation) AND by
absolute refs (94 of them, unmoved). Cutting the block at 0x100f7f30 split them → the writer
(block-relative → DDR) and reader (absolute → SRAM) diverged → the name read empty → UNTITLED.

**Fix — `tools/build_blockmove3.py`:** BLK_HI = `0x100f87c0` (through slot 130), so slots 128-129
move WITH the block (253 refs, 0 false positives). **Hardware-confirmed: altre-galassie loads
and PLAYS end-to-end.** The static settings block now lives in DDR — the 128→256 technique is
proven. Minor side effect: the metadata slots were battery-backed persistent state (CF-id,
current project); in volatile boot-zeroed DDR they reset each boot → a dismissible "WRONG
COMPACT FLASH CARD" popup and the current project defaulting to UNTITLED until re-selected.

### Static 128->256 — Phase 2 change map (exhaustive, pre-build)  [2026-08-04]

Phase 1 (done, committed): reserved region enlarged to 768 KB (pool +128 pages, base
0x40a955e0->0x40b555e0, count 0x390A->0x388A) — the 256-block (flex 136 + static 256 +
metadata 2 = ~0x40afecb0 end) fits. Hardware-confirmed load/play/record.

Phase 2 is ONE entangled operation (moving the metadata is inseparable from bumping the
counts, because the metadata sits at static_base + count*0x448 and loops that reach it use
count+1/count+2 bounds). The static-slot count bounds are NOT the ~400 generic `#128`
refs — they are only the bounds on the **stride-0x448 (settings)** and **state-table
(0x46c90a78)** loops, a bounded/enumerable set. Full map:

**Settings loops (stride 0x448) — 26 loops enumerated (tools recon):**
- 4x `cmpi.l #128` (static count) -> **#256**  [0x4008f904, 0x400908f8, 0x40091146, 0x4009137e]
- 1x `cmpi.l #129` (static + template slot 128) -> **#257**  [0x40089604 loop]
- 4x `cmpa.l #static_end` + 3x `cmpi.l #static_end` -> **new static end** (static_end is the
  relocated 0x100f7f30; for 256 = static_base + 256*0x448)
- UNCHANGED: `cmpi #136`/`#137` (flex, 5x), `cmpa/cmpi #static_base` (Table-A end, 7x)

**State table 0x46c90a78 (44 B/slot):**
- 33 of 36 base refs sit in loops bounded by `cmpi.l #128` -> all 33 **-> #256**.
- CANNOT grow in place: 0x46c920a4 (just past the 128-entry end 0x46c92078) is referenced.
  The state table must be **relocated** to a 256*44 = 0x2c00 home + its 36 base refs moved.

**Metadata (slots 128-129, the project name at 0x100f8378 etc.):** 94 absolute refs shift
**+0x22400** (128 slots) so slots 128/129 -> 256/257, past the extended static. The
static-end address bounds and the metadata slot-128 refs are the SAME address, so they move
together. Note the project-name buffer 0x100f8378 has DUAL access (block-relative via the
129-loop AND ~26 absolute refs) — both must land at the new slot-257 position.

**project.work format (FUN_40088288 serializer):** writes a TEXT file (sprintf format
strings), 129 static records per project (`cmpi #129` loop at 0x40089604 = static 0-127 +
template slot 128). Extending to 257 records **breaks compatibility** with stock/existing
128-projects (e.g. altre-galassie) unless the deserializer accepts BOTH counts (129 and 257).
Real cost: existing projects.

**Recorders — SEPARATE, no entanglement (good news):** the flex table (0x100b14f0, 136 slots =
128 flex + 8 recorders) is a different table from static (0x100d5b30). The static 128->256
extension doesn't touch flex, so recorder loops (bounded `#136`) stay unchanged. The old "82
bounds entangled with recorders" note was about a flex change, not static.

**UI:** no simple `#127` clamps; the static-slot LIST draw and the per-track SLOT parameter cap
(0-127) live in the AUDIO-menu code / a parameter-range table (small, findable during the build,
not a scope blocker).

**SCOPE (complete): ~140 coordinated edits** (26 settings-loop bounds ~12 changed + 33 state
#128->256 + 36 state base refs relocated + 94 metadata refs shifted +0x22400) **+ a state-table
relocation + a project.work dual-format deserializer + UI slot-limit edits.** One of the largest
possible firmware mods; every edit exact (one wrong -> crash). The settings-block-in-DDR win
(done) already lets siblings share the pool; whether 128 slots + careful sample layout suffices
for the sibling transition, vs paying this full 256 cost, is the open design call.

## Static 128->256 — REVISED architecture: DUAL TABLE (approach B), no relocation  [2026-08-04]

Blanket relocation of the state table (Phase 2a: 0x46c90a78 -> 0x40b00000, all 36 refs) booted
once then crashed VEC:04 ADDR:0 at the PROJ key / inconsistently at boot, twice. Root cause: a
deep hidden dependency in the HIGH-DDR fixed-structure region that base relocation breaks (table
A is runtime-initialised at 0x46c90a78 and neighboured densely; something reaches it other than
the 36 immediates we moved). Relocation abandoned.

**Approach B (additive, no relocation):** keep table A at 0x46c90a78 for slots 0..127 EXACTLY as
stock (all init, neighbours, deep deps untouched). Add table B for slots 128..255 in reserved
DDR. Every accessor range-checks and picks the table. Because table A is byte-identical to stock,
this is safe by construction.

### State table (0x2c=44 B/slot) accessor anatomy (disassembled, all 36 refs)
- **35 sites are RANDOM-ACCESS** `base + slot*44`: a `muls.l dS,REG` (REG = slot*44) then a
  6-byte `addi.l/adda.l #0x46c90a78,REG`. Registers used: d0(16) d1(2) d2(3) d4(1) d5(1)
  a0(4) a2(3) a3(4) a5(1).
- **1 site is the allocator loop-start** `lea 0x46c90a78,a0` @ 0x4002409c (FUN_40024098): walks
  a0 +44/step, free-flag = `slot[+8]==1`, bound `cmpi #128,d1`. Sequential, not base+slot*44.
- **~24 of the 35 are already guarded** by `cmpi/cmpa #128,dN; bhi/bls <default>` — stock
  STRUCTURALLY rejects slot>=128 (returns null) BEFORE computing an address. So slots 128..255
  are simply unreachable today; opening them is a matter of bumping those guards (Layer 2).
- **CCR-safe:** verified no site branches on the base-add's CCR (each followed by an
  unconditional branch, a movea (no flags), or a flag-overwriting move/tst). So a helper using
  cmpi/cmpa is transparent.

### Layer 1 — dual-table plumbing, BEHAVIOUR-NEUTRAL (tools/build_phase2_state.py + patch_state_helpers.s)
Layers on out/mainos_phase1.bin. Replaces each of the 35 random-access `addi.l/adda.l #base,REG`
(6 bytes) with `jsr sh_<REG>` (6 bytes, byte-exact). 9 helpers in a cave @ 0x400d7400 range-check
the PRODUCT (slot*44):
  product <= 0x1600 (slot 0..128)  -> REG + 0x46c90a78              (table A, IDENTICAL to stock)
  product >  0x1600 (slot 129..255)-> REG + 0x40afea00 (=0x40b00000-0x1600)  (table B, Layer-2)
Allocator lea left literal (extended in Layer 2). Residual 0x46c90a78 immediates after build = 10
(1 lea + 9 helper table-A adds); a static equivalence proof in the build asserts helper(idx) ==
stock base+idx*44 for ALL idx 0..128. Every image bound still stops at 128 -> the table-B branch
is DEAD -> Layer 1 is byte-identical to stock for every reachable index.

**BUG FOUND & FIXED (flash #1 crashed VEC:04 ADDR:0 at IPL 7 / SRC:STATIC):** the first helper
used `bcc` (product >= 0x1600), which redirected INDEX 128 to table B. But index 128 is the stock
TEMPLATE/sentinel slot at table-A end (0x46c92078) — accessors with an INCLUSIVE `bls #128` guard
(0x40021ef2, 0x40077f76, 0x400794fc, 0x4009405a) and the voice "empty slot" path read it. Redirect
-> uninitialised table B -> garbage ptr -> jump to 0. The IPL-7 SR:2700 pinned it to the audio
interrupt = the ONE converted voice site 0x4000f4a6 (sh_a5). FIX: `bcc`->`bhi` (strict >), so index
128 stays in table A. LESSON: index 128 is overloaded (template vs future new-slot-128) — Layer 2
must split template accessors (keep bhi/stock) from audio accessors (switch to >= for table B).

### Layer 2 — open the bounds (next, AFTER Layer 1 verified on hardware)
- Bump the ~24 state `cmpi/cmpa #128` guards -> #256 (they gate the muls+jsr; by proximity to a
  state ref, distinct from the 4 settings-loop #128 counts).
- Extend the allocator (FUN_40024098): after walking table A (0..127) full, continue into table B
  (128..255) — detour to a rewritten walker in a cave.
- Init table B free-flags (slot[+8]=1). Cheapest: the project-load "clear all static slots" reset
  loop, once its bound is 256, initialises B for free — no boot-zero extension needed.
- Settings table (0x448 B/slot, 0x100d5b30 static) gets the SAME dual-table pattern (helpers on
  its 43 base refs / the 100d5b30 siblings seen beside several state refs) + a side-car file
  (e.g. static_ext.work) for slots 128..255, so project.work stays 129-record for bidirectional
  compatibility. UI slot caps (AUDIO list, per-track SLOT param) -> 256.

### Layer 1 exhaustive static audit (post-crash, before re-flash) — ALL GREEN
Multi-pass verifier (each pass independent; 3 initial "fails" were audit-script bugs, corrected):
- **A/B** stock has exactly 36 state-base immediates; 1 LEA (allocator) + 35 addi/adda classified.
- **H (byte-diff phase1 vs phase2_state):** 386 differing bytes, EVERY one accounted for = the
  216-B helper cave + 35×6-B `jsr` rewrites. Zero collateral changes.
- **C** all 9 helpers encode `cmp #0x1600 ; bhi ; +0x46c90a78/rts ; +0x40afea00/rts`.
- **CCR:** 23 addi sites end in the identical `addi #base,dN` -> CCR bit-identical to stock. 12
  adda sites: helper's `cmpa` changes CCR, but the first post-site instr overwrites CCR (movew/
  movel/moveq/tstl) or is `bra` BEFORE any conditional -> invisible. (Verified per-site.)
- **E** no branch targets a converted-site interior byte {o, o+2} (same-length replace, same start).
- **F** equivalence: helper(idx)==stock base+idx*44 for ALL idx 0..128 (template incl.).
- **G** every converted STATIC site's controlling guard is <=128 (27 sites #128, 8 unguarded).
  The 8 unguarded all pair static-state (0x46c90a78) with static-settings (0x100d5b30) on the
  same index reg -> static path, index<=128. `#135` guards belong ONLY to the sibling FLEX path
  (flex base 0x46c922c4, flag 0x46105408) and never feed a converted site. Flex refs (48)
  identical stock vs patched. Allocator lea immediate intact.
Conclusion: Layer 1 is provably behaviour-neutral for every reachable index; only idx>=129
(unreachable until Layer 2) diverges to table B.

STATUS: Layer 1 designed, built, and EXHAUSTIVELY audited (all green). Packaged
out/OCTATRACK_STATE2.bin/.syx (bhi fix). Flash #1 (STATE1, bcc bug) crashed; STATE2 is the fix.
Flash only after the user finishes sysex recovery + confirms.

### DEFINITIVE ROOT CAUSE: PHASE 1 CLOBBERED THE DSP/AUDIO ENGINE  [2026-08-07]
After BLK_HI was fixed, PHASE1B STILL crashed non-deterministically (VEC:04 ADDR:0 SR:2700,
even at EMPTY RESET, sometimes mid boot-animation). The BLK_HI over-reach and the missed pool
literals were real bugs but NOT the cause. The cause: Phase 1 MISIDENTIFIED the structures it
changed. At the DSP/voice-engine init routine 0x40096f80..0x40097018 (stock):
    movel #0x390A,d6 ; movel d6,0x80006920      <- count -> a DSP register
    lea 0x46c2e9c0,a0 ; movel a0,0x80006914     <- buffer base -> DSP register
    lea 0x46c2e580,a2 ; lea 0x46c2e780,a3       <- more DSP buffers
    ... pea 0x40a955e0                          <- the struct Phase 1 "moved" is used HERE
So `count 0x390A` is a DSP AUDIO-BUFFER size (14602 entries at 0x46c2e9c0, pushed to DSP regs
0x8000691x), and 0x40a955e0 is a live DSP-engine struct — NEITHER is a "sample-slot pool
count/base". Phase 1:
  - reduced 0x390A->0x388A at ONE site only; 0x390A occurs 18x (long) + 23x (word) elsewhere
    (loop bound 0x390B unchanged) -> the DSP is told 14474 while the buffer is sized 14602 ->
    out-of-range DSP reads -> NON-DETERMINISTIC audio-ISR crash.
  - moved 0x40a955e0 +768KB (fragile, missed refs 0x40a96de0/0x40b30916) AND relocated settings
    ON TOP of 0x40a955e0 AND boot-zeroed that region -> stomps a live DSP struct.
All five Phase 1 edits stem from this misID. CORRECT BASELINE = STOCK (boots fine). The dual-
table STATE accessor work (passthrough helpers + build_phase2_state) is sound and was riding a
broken foundation; it re-bases onto stock unchanged once a CORRECT free-DDR region exists.

NEXT (no more flashing until designed): map DDR properly from stock — locate the true sample-
slot STATE/SETTINGS tables vs the DSP sample-data buffers, find a provably-unused DDR window
for table B (state 128*44=0x1600 + settings 128*0x448=0x22400 ~= 143 KB), WITHOUT touching the
DSP count/buffers or 0x40a955e0. Then re-layer the passthrough accessors + real table B on stock.

### PRE-FLASH GATE: tools/emu_check.py (Unicorn)  [2026-08-07]
Mandatory gate before building ANY .bin. Unit-emulates firmware routines (m68k) and diffs a
patched image vs pristine stock (out/stock_mainos.bin, decoded once via elektron-firmware-tool
-d 3). Catches the whole class of bug we hit WITHOUT flashing:
    python3 tools/emu_check.py out/<patched>.bin      # -> ALL GREEN or FAILURES-DO-NOT-FLASH
Current checks: dsp_init_regs (emulates 0x40096f80, asserts the DSP-reg writes 0x8000691x match
stock), dsp_struct_intact (0x40a955e0 + audio buffers unrelocated), count_consistency (all 0x390A
occurrences unchanged). Verified: FAILs on mainos_phase1.bin (flags all three), PASSes on stock.
Add a check per new routine we touch (state accessors, table-B init) as the 256-slot work resumes.

### FREE-DDR RECON: table-B window found + verified (static + dynamic)  [2026-08-07]
STATE A [0x46c90a78,0x46c92078), FLEX [0x46c922c4,0x46c94074), last control ref 0x46c93c28.
Then a 350 KB hole [0x46c94074, 0x46ceb400) with ZERO operand refs, capped by the 28-byte
record-array at 0x46ceb400 (base stored in ptr var 0x46c8c5b8, grows UP; init at 0x4001bdb4).
The hole is dead space between two CONTROL structures, NOT sample RAM (verified: the high
"refs" 0x47f98000 were false positives = `lea 0x8000xxxx,a3` bytes; 0x4713c0fc is arithmetic).
PROPOSED table-B window: [0x46c96000, 0x46cb9a00) (~142 KB) = state B [0x46c96000,0x46c97600)
+ settings B [0x46c97600,0x46cb9a00), ~200 KB margin below the record-array, adjacent to table
A (cache-friendly), touches neither DSP nor sample RAM. tools/emu_ddr_free.py: the state-table
scanners (0x40024098/0x400240e8) read up to 0x46c92057 (table-A end) and STOP below the hole;
NONE touches the window -> dynamic corroboration of the static zero-ref finding. (Honest limit:
covers only the traced routines; extend ROUTINES as we implement, and emu_check re-verifies the
accessors we add.) ADJ for table-B accessors when we resume: helper redirect base for slots
128..255, product > 0x1600 -> +(0x46c96000 - 0x1600) etc.

### MILESTONE: passthrough-on-stock BOOTS on hardware  [2026-08-07]
out/OCTATRACK_STATE_STOCK (build_state_stock.py, passthrough helpers on pristine stock,
emu_check ALL GREEN) flashed and ran PERFECTLY: many reboots, EMPTY RESET, load+play+record
altre-galassie — zero crashes, behaves exactly like stock. This validates, on the CORRECT
baseline, all at once: (1) the .bin/CF flash pipeline (first confirmed-booting flash), (2) the
jsr-to-cave state-accessor plumbing, (3) emu_check as a reliable pre-flash gate (predicted GREEN
-> booted). The whole crash saga was Phase 1 clobbering the DSP; on stock the accessors are clean.
NEXT: the REAL table-B (redirect slots 128-255 -> 0x46c96000, init, bounds->256, settings dual-
table). Open design knot to resolve first: the index-128 TEMPLATE overload (verify + decide
255-slots-keep-template vs 256-slots-relocate-template). emu_check gate every step.

### STATE table-B redirect helpers DONE + verified  [2026-08-07]
tools/patch_state_helpers_b.s: two-sided redirect (idx 0..128 -> table A incl template;
129..255 -> table B 0x46c96000; >=256/-1 -> table A stock-safe). ADJ_B=0x46c94a00, LO=0x1600,
HI=0x2bf4. tools/verify_helpers_b.py emu-verifies all 9 helpers x 10 indices = ALL PASS. Decision
locked: 255 usable slots (idx 128 stays template). blob 288 B.

### SETTINGS is HARD: must be CONTIGUOUS (relocation, not dual-table)  [2026-08-07]
Static settings base 0x100d5b30 (SRAM, 0x448/slot), 43 code refs = 31 product-adds (d0/d1/d2/d3,
a1/a2/a3/a4) + 12 base-loads/compares. Unlike STATE, settings is walked CONTIGUOUSLY:
  - ~5 loops do `lea 0x100d5b30,aN; aN += 0x448; count` (assume contiguous slots), and
  - >=3 COMBINED flex+static loops walk from flex base 0x100b14f0 to static END 0x100f7f30
    as ONE array: 0x4008f45c (lea a2), 0x4008fa54 (lea fp), 0x40091024 (lea a3).
A dual-table (table B at a different address) BREAKS every contiguous/combined walk. Settings
therefore needs RELOCATION to a contiguous 256-slot region. Flex loops that END at 0x100d5b30
(cmpa #0x100d5b30: 0x40086020, 0x4008646c, 0x4008f42a...) are flex-only and stay.
Two options: (A) relocate whole flex+static block with static grown to 256 = 392 slots*0x448 =
421 KB (needs a 421 KB window; ~150 literal refs; = Phase-1's mechanism done right, BLK_HI bug
understood, NOT touching pool/DSP). (B) relocate static-256 alone into the verified 137 KB window
[0x46c97600,0x46cb9a00) + REWRITE the ~3 combined loops to walk flex(SRAM) then static(DDR).
NOTE: option A needs a >=421 KB free DDR window not yet found; option B fits but needs loop edits.
Decide + design carefully (emu-gate the combined loops) before any settings .bin.

### WINDOW SEARCH: no verifiable >=430 KB window -> Option A is OUT  [2026-08-07]
DDR reference-gap analysis is dominated by (a) false positives (fourcc constants 0x45464748
"EFGH", 0x434f4d4d "COMM", 0x464f524d "FORM" decoded as addresses) and (b) sample RAM accessed
by computed pointers (so gaps inside it look "free" but are not). The ONLY verifiable free hole
is the 350 KB one near the state tables (137 KB used for state B). No provable >=430 KB window
exists -> the whole-block relocation (Option A) is not safely doable. Settings must use Option B.
The "combined" loops are actually TWO ADJACENT loops: loop 1 walks flex (cmpa #0x100d5b30 end),
loop 2 CONTINUES from a2=0x100d5b30 (relies on static following flex) to cmpa #0x100f7f30. Example
0x4008f3f8: counts flex+static slots where two predicates (0x400204a8/0x400204cc) hold. Option-B
rewrite per such loop: before loop 2, reload a2 = static-DDR base (trampoline to cave, since we
can't insert in place) and change its bound #0x100f7f30 -> static-DDR end. Plus rebase the 31
random-access static refs 0x100d5b30 -> static-DDR base, rebase the ~5 static-only walk loops,
keep the flex-end bounds (cmpa #0x100d5b30) as-is, open the static bound guards #128->#256, and
init static-DDR-256 free flags at boot. Every loop emu-gated (visits all 256 static slots)
before any .bin. This is the delicate core; design slowly.

### SETTINGS relocation — definitive 43-ref classification  [2026-08-08]
Layout in the verified hole (state B dual-table [0x46c96000,0x46c97600) stays):
  SETTINGS-256 relocated -> [0x46c97600, 0x46c97600+256*0x448=0x46cdbe00), 280 KB, margin to
  the record array 0x46ceb400 = 0x1d600 (117 KB). Fits.
The 43 code refs to static-settings base 0x100d5b30 classify as:
  REBASE (static access -> new DDR base 0x46c97600): 31 product-adds (addi d0/d1/d2/d3, adda
    a1/a2/a3/a4) at 0x400050d0,0x4000f4b6,0x40021e3e,... + 5 base-loads (3 move.l# @0x4008f8c8/
    0x400910f6/0x40091340, 2 lea a2 @0x4008fb0a/0x40090854). ~36 total REBASE.
  KEEP (flex-walk END bound, flex ends at old static base and does NOT move): 5 cmpa #0x100d5b30
    @0x40086022,0x40086472,0x4008f42c,0x4008f9e2,0x40090f94  (+ verify the 2 cmpi.l d3/d4
    @0x40089fa6,0x4008f76a: KEEP if they're flex-walk ends).
  Plus the 3 COMBINED loops (0x4008f45c/0x4008fa54/0x40091024 -- NOT in the 43 refs; loop 2
    continues from a2=0x100d5b30 implicitly) -> trampoline: before loop 2, load a2 = 0x46c97600
    and change its end bound #0x100f7f30 -> 0x46cdbe00.
Then: open static-settings bound guards #128->#256 (subset of the 81 cmpi #128), init the DDR-256
table free flags at boot, UI caps. EMU-GATE: rebase must produce NO access to old 0x100d5b30 for
static slots, and every walk/combined loop must visit 256 slots at the new base. NOTE: 0x100d5b30
serves DOUBLE duty (static base AND flex-end bound) so a blanket byte-replace is WRONG -- must
rebase only the classified static-access refs. (This is exactly the mistake class that crashed
Phase 1; the classification above is the guard against it.)

### COMBINED-LOOP TRAMPOLINE technique PROVEN via emu  [2026-08-08]
For combined loop 0x4008f3f8 (loop1 flex, loop2 static-by-adjacency): replace the loop-2 entry
`lea 0x400204a8,a4` @0x4008f432 with `jmp cave`; cave does `lea 0x46c97600,a2` (reset to DDR
static base) + redo `lea 0x400204a8,a4` + `jmp 0x4008f438` (back into loop 2); and change the
loop-2 end bound @0x4008f45c `cmpa #0x100f7f30` -> `#0x46cb9a00` (128-slot neutral end; ->
0x46cdbe00 for 256). EMU PROOF: stock loop2 reads static SRAM 0x100d5b30..0x100f7ae8; patched
loop2 reads static DDR 0x46c97600..0x46cb95b8 and NOTHING at old SRAM; flex loop1 identical.
Apply the same pattern to the other 2 combined loops (0x4008fa54 lea fp, 0x40091024 lea a3 -- each
has its own displaced instr / registers, examine per-loop). Also handle static-ONLY loops whose
END bound is 0x100f7f30 (static end, DOUBLE-DUTY with the global base above -- classify: loop-end
cmpa/immarith -> rebase to new static end; pea/lea base-loads of the global -> KEEP). Then bounds
#128->#256 + DDR free-flag init. Each loop emu-gated (visits the right region) before any .bin.

### MAX256 build in progress: relocate BOTH tables (build_max256.py)  [2026-08-08]
Architecture chosen: relocate state AND settings to contiguous 256-slot DDR tables in the
verified hole (uniform; walk loops work by rebase). NO 430KB window exists so whole-block is out;
this puts each table separately-contiguous:
    STATE-256    [0x46c96000, 0x46c98c00)   (state base 0x46c90a78 -> 0x46c96000; 36 refs, blanket
      rebase -- template 0x46c92078 has 0 refs, no address-bounded static walk -> clean)
    SETTINGS-256 [0x46c98c00, 0x46cdd400)   (rebase 36 static-access 0x100d5b30 -> 0x46c98c00,
      KEEP 7 flex-end cmpa/cmpi)
DONE + emu-verified: Stage 1 rebase (emu_check GREEN, DSP untouched). The 3 combined-loop
trampolines (cave 0x400d7400): loop1 patch 0x4008f432, loop2 patch 0x4008fa00 (walk fp->a2),
loop3 patch 0x40090fc8 (walk d2) -- each resets the walk reg to 0x46c98c00 + retargets its
0x100f7f30 end bound; emu-verified loop1 (full), loop2 (forced-entry DDR coverage 0x46c98c00..
0x46cbabb8 no old SRAM), loop3 (d2 reset OK).
OPEN (must classify before finalizing -- DO NOT touch unclassified): 4 static-END bounds
0x4008626a,0x4008666c,0x4008a0f8,0x4008f7fa (walk a4/a4/d3/d2, loop starts 0x40086040/0x400864a0/
0x40089fb4/0x4008f7a8) end at 0x100f7f30 but their walk-reg base is set FAR back -- some may be
ADDITIONAL combined loops (need trampolines) not static-only (end-rebase). Trace each walk reg's
base init before finalizing. THEN: emu-verify all 4 + full image, THEN bounds #128->#256 for the
feature, init free-flags, UI caps. Neutral (bounds 128) flash de-risks the surgery first; feature
is bounds->256 diff after. build_max256.py currently = Stage 1 only; trampolines applied inline in
the verification (integrate next).

### THE REAL BUG WAS IN PHASE 1, NOT THE ACCESSORS  [2026-08-07]  -> out/OCTATRACK_PHASE1B.*
STATE1/2/3 all crashed identically because PHASE 1 ITSELF was non-deterministically broken;
the state accessors were riding a broken foundation. Confirmed by flashing Phase 1 ALONE:
it crashed intermittently (sometimes during the boot animation, sometimes at PROJ, even at
EMPTY RESET, before any keypress) — VEC:04 ADDR:00000000 SR:2700 (audio IPL7). Non-determinism
+ ADDR:0 = uninitialised DDR read as a code/pointer address.

ROOT CAUSE: build_phase1.py had BLK_HI = 0x100f87c0 for the settings-block relocation, but the
real block is 264 slots * 0x448 = 0x46A40, ending at 0x100b14f0 + 0x46A40 = 0x100f7f30. The
0x890-byte over-reach swept in the SRAM GLOBALS above the block and relocated 94 of their
operand refs to DDR (+0x309c40f0) while the structs themselves do NOT move:
  0x100f7f30 (block-end/global), 0x100f8378 (26 refs), 0x100f8480 (50 refs),
  0x100f8481 (3), 0x100f8584 (4), 0x100f8598 (2 of 461!).
Even 2 broken refs into a 461-ref global -> those code paths read DDR garbage as a pointer ->
intermittent jump-to-0. FIX: BLK_HI = 0x100f7f30. After the fix, step 2 relocates 166 refs
(was 260), keeps the 2 pea base-loads to 0x100f7f30, and every global above the block is
byte-for-byte identical to stock (0x100f8480 50/50, 0x100f8598 461/461, ...). Block-internal
audit clean (only flex/static bases + two base+0x129 field leas are base-loaded inside).
Lesson: a blind byte-scan relocation MUST have its bounds derived from the exact slot count,
and a post-check that the NON-moving neighbours above/below are untouched vs stock.

NEXT: flash PHASE1B ALONE, verify STABLE across many reboots + EMPTY RESET + load+play audio.
Only THEN rebuild STATE3 (passthrough) on the fixed Phase 1 and re-test.

### CRASH #2 (STATE2, bhi) — ROOT CAUSE: the redirect is NOT dead  [2026-08-07]
STATE2 crashed AT BOOT, VEC:04 ADDR:00000000. Full byte-audit of the flashed image was
clean (35 jsr->helper, alloc lea intact, cave = correct helpers, no stray diff, .syx
round-trips byte-identical). So the ENCODING was perfect — the DESIGN assumption was wrong.
  - The "table-B branch is dead because no reachable idx>128" claim is FALSE. `bhi` is an
    UNSIGNED compare (product > 0x1600). Of the 35 sites, 30 sit behind a `cmpi #128; bhi/bls`
    guard (safe), but 5 are UNGUARDED — index arrives straight from the caller:
    0x4000f4a6 (voice/IPL7 — the STATE1 site), 0x40024f72, 0x4007809c, 0x40025548, 0x4009307e.
  - At boot at least one unguarded accessor gets a SENTINEL / out-of-range index (a "no slot"
    -1 -> product 0xffffffd4; or a default current-slot 255 -> 0x2bf4). Stock does base+idx*44
    and lands in adjacent INITIALISED memory (flex/settings) -> benign. The helper's unsigned
    `bhi` catches it -> redirects into table B at 0x40b00000, which bootzero cleared to 0 ->
    read 0 -> deref 0 -> VEC:04 ADDR:0 at startup. Exactly the symptom.
  - Lesson: a range redirect can only be behaviour-neutral if (a) table B is a real,
    initialised table AND (b) the redirect is bounded on BOTH sides to the true new slot range
    AND (c) sentinel/OOR indices are excluded. All three belong to Layer 2, not Layer 1.

### Layer 1 REVISED -> PURE PASSTHROUGH  [2026-08-07]  -> out/OCTATRACK_STATE3.{syx,bin}
Helper is now `addi.l/adda.l #0x46c90a78,REG ; rts` — NO compare, NO redirect. Result =
base+product, identical to the replaced inline op for EVERY input (guarded/unguarded,
negative, >255), CCR included (addi sets flags like the inline addi; adda leaves them like
the inline adda; rts touches neither). Provably byte-behaviour-identical to stock => cannot
reproduce the redirect crash. Its ONLY job: prove the jsr-to-cave plumbing (cave validity,
jsr/rts in the IPL7 voice path, CCR neutrality) before Layer 2 introduces real table-B
semantics. Verified: diff vs phase1 = 72 B cave + 35 jsr rewrites, nothing else; .syx and CF
.bin both decode byte-identical to out/mainos_phase2_state.bin. Flash STATE3, expect
behaviour identical to Phase 1. THEN Layer 2 does table-B init + two-sided bounded redirect
+ sentinel handling + the ~30 guards / allocator / settings / UI to 256.

## Sequencer clock ✓ — logs `out/ghidra_clock.log`, r2 disasm

**The sequencer has NO timer of its own: it is clocked by the DSP's audio FRAME interrupt**
(sample-accurate sequencing). Phase accumulator:
- Tempo → `_DAT_80001814`; per-frame increment `_DAT_80001820 = 2³¹ / tempo`
  (seen in `FUN_4000c8a4`: `_DAT_80001820 = -0x80000000 / _DAT_80001814`).
- `FUN_4009c550` sets the tempo period from the pattern data (`_DAT_46c82456 + pat*0x8ed8`).
- The **frame ISR** (`0x4000aad0`, fires on reading the frame index at `0x2000001c`) accumulates the phase;
  on overflow it advances the step and **posts to a kernel queue** (`FUN_40000c3c`) to wake the
  sequencer task → trigs → `FUN_400977cc` → voice command. Refs to tempo/phase at `0x4000axxx`.

## DSP program: located and extracted ✓ — `out/dsp_region.bin`

**DSP56300 (24-bit), at the TAIL of the MAIN OS image** (`~0x400e2000 .. 0x4010fdf0`, ~188 KB
= ~62,600 24-bit words). Confirmed: `f803 00bb …` = DSP56k opcodes, loaded 3 bytes at a time.
- Loaders: `FUN_40001d4c` → **P** memory (24-bit stream, starts with `0x20000000=0x81`);
  `FUN_40001b18` → **X/Y** data. Uploads in sections to DSP `0x31000`, `0x32000`, …
- Blobs from init: `0x400e21e0`(len 0x96→0x31000), `0x400e2276`(0xae→0x32000), `0x400e2324`, `0x400f59ef`.
- **For the FX/timestretch**: disassemble with target **DSP56300** (Ghidra/r2 don't ship it; a56/dsp56k
  or community SLEIGH modules). Separate project.

## Go/No-Go — patch "preserve volume when switching Part" → FEASIBLE (corrected)

- The behavior lives in the **audio hot path** (`FUN_4000c8a4` + core `0x40009xxx`/`0x4000cxxx`):
  the frame builder reads the **active Part** (`0x80000002`) and **active pattern** (`0x80000003`) every frame
  and from there takes the LEVEL → that's why it jumps when switching Part (continuous read, not "apply on change").
- **CORRECTION of a previous erroneous verdict**: it is NOT blocked by tooling. Ghidra's ColdFire SLEIGH
  **already decodes** this code (defines MAC/MSAC/MACSR/ACC0-3; `71f9`/`73c3` = `mvz.w`/`mvs.w`).
  Verified: the frame builder disassembles **121 clean instr., 0 gaps** in Ghidra's listing.
  The previous error was using **radare2** (blind to ColdFire extensions) for the check and confusing the
  **decompiler** failure (no C) with a **disassembler** failure (which does work).
- **Rule**: for the audio core → use **Ghidra's listing** (not radare2, not the decompiler).
- **EMAC sub-project: UNNECESSARY** (Ghidra already covers the ISA). Off the roadmap.
- Remaining work for wish 1 (hard but defined, NOT blocked): read the frame builder's ASM
  to find the exact LEVEL read, map free RAM in the voice struct (`0x800049d8`/0xA8),
  design the per-voice latch, patch at the byte level, test on hardware.

### A vs B confirmed → **B**, and intermediate "lazy apply on first trig" design
- `FUN_40005030` (trig helper) reads **pattern** data (`_DAT_46c82456 + pattern*0x18b2`, which sample)
  and writes sample-slot + voice command + DSP double-buffer, but **does NOT refresh the Part params**
  (doesn't touch `0x80000a50` nor the Part data `*0x9b340`). → The trig fires the sample but does NOT re-apply
  the Part. Only `FUN_40009094` (by event) does. **Scenario B confirmed.**
- Intermediate design (apply destination Part on the first trig per track): **moderate**. Components:
  "pending" flag per track (or better: **Part-applied per track**, 8 bytes), skip reload of sounding
  tracks in `FUN_40009094`, per-track apply, hook in the trig (`FUN_40005030`/`FUN_400977cc`).
- **Layered params model**: base Part → (FUN_40009094 on change) base buffer → per-frame computation
  (LFO/scene/p-lock, in `FUN_4000c11a` 5066 B, does NOT decompile) → `0x80000a50` → DSP. The voice-in-transition
  uses the buffer, which derives from the ORIGIN Part if we skip the reload → no jump. ✓

### AUDIO PATCH SPEC (intermediate design) — per-track infrastructure ALREADY EXISTS ✓
- **`per_track_part[8]` @ `0x8000182a`, `per_track_pattern[8]` @ `0x80001832`** already exist. Both
  param appliers (frame builder + `FUN_40002df4`) are gated by `per_track == active`.
- The jump originates in the frame builder: when `GLOBAL_applied (0x80001828) == active`, at `0x4000ca32`
  it does `per_track_part[track]=active` (`move.b D1,(A5)`) + `0x4000ca34` pattern + applies params.
- **Patch**: at `0x4000ca30` (update+apply block), gate: if `voice_active[track] && !trig_pending`
  → jump to `0x4000ca76` (keeps old per_track → no jump). Otherwise → apply + clear pending.
  Both appliers respect it for free (they key on per_track). Trig hook (`FUN_40005030`):
  `trig_pending[track]=1`. Active voice = `0x800049d8 + track*0xA8` byte0.
- **Resources**: code cave `0x400d64da` (5986 B of 0x00); free RAM `0x80006a00` (340 slots) for
  `trig_pending`. Minimal new state (the Part array already exists). Difficulty: medium, bounded.
- Improvement over the previous idea of patching `0x4000c8c6`: reuses existing infra, 1 gate + 1 hook.
- Knob→Part editor: cornered to the cluster `0x40041–0x40043` (param pages), writes the Part data
  without calling `FUN_40009094`; still need to pin the exact function (1 pass). Enables the GUI-in-transition
  (route editing through `per_track_part[track]`, which already exists).

### DYNAMIC ANALYSIS OPERATIONAL — ColdFire emulator (Unicorn) ✓✓
- `tools/emu_validate.py`: validates that **Unicorn (m68k) runs the firmware's ColdFire** —
  `FUN_40000e50(5)` → `0x80004d20` exact. Viable approach.
- `tools/emu_trace.py`: memory-write tracer. Ran `FUN_40009094(0,0)` and **dynamically confirmed**
  that it writes `0x80001828/29` (global), `0x8000182a/32` (per-track), `0x80000a50` (voice).
- `tools/emu_find_editor.py`: sets up globals (`_DAT_46c82456`=project, track/pattern/mode) and traces
  candidates watching for writes to the Part data. **Found `FUN_4005a918`**: writes 6 params/page
  to the Part data (`0x8edaa`…) + dirty flag (`0x9b332=1`); operates on `DAT_100b14cc/cf/46c7d8d8`.
  (Probably page recall/scene/commit, not the single-encoder editor — but the dynamic
  methodology works to pin any function.)
- **Proven method**: set globals + trace + watch writes to the `_DAT_46c82456`-region = hunt editors.
  The single-encoder editor is a few more traces away. CPU exception sometimes (~0x40000c42, unsupported
  instr) but the useful trace happens before it.

### "LAZY PART" BEHAVIOR PATCH — IMPLEMENTED AND VALIDATED ✓✓✓ → `out/OCTATRACK_OS1.40C_LAZYPART.syx`
- **Behavior**: on pattern change, SOUNDING tracks keep their params (no volume
  jump); on their first trig they apply the new Part (via the frame builder's D6 gate).
- **Implementation** (save/restore, `tools/patch.s`, assembled with `m68k-elf-as -mcpu=5407`):
  - Cave at `0x400d64e0`: `save_stub` (0x400d64e0) + `restore_stub` (0x400d6538), 184 B.
  - ENTRY detour `0x40009094` → `save_stub`: bulk-saves voice buffers (`0x80000a50`, 0x200 B) +
    per_track (`0x8000182a`, 16 B) + "sounding" flags (`0x80006c20`); runs the displaced lea+movem;
    `jmp 0x4000909c`.
  - EXIT detour (tail-call) `0x40009664` → `restore_stub`: restores voice buffer + per_track of the
    tracks that were sounding; `jmp 0x40000c3c` (original tail-call to post_work). RAM save: `0x80006a00`.
  - Key: `FUN_40009094` does NOT end in rts but in tail-call `jmp 0x40000c3c` @0x40009664 (the rts
    @0x40009844 belongs to ANOTHER function — bug fixed).
- **Validated in the Unicorn emulator** (`tools/emu_clean.py`): sounding track preserved (0xEE intact),
  silent tracks updated. Pre-stub of post_work + 1 EMAC func (instructions Unicorn doesn't
  support; on real HW they run normally).
- **Repackaging**: `-c 3` → `.syx` with `checksums: ok`. Flashable. Final test = flash over MIDI
  (recoverable).

### GUI-IN-TRANSITION PATCH — IMPLEMENTED AND VALIDATED ✓✓✓ → `out/OCTATRACK_OS1.40C_LAZYPART_GUI.syx`
- **What it does**: turning a knob while a track is in transition (per_track_part≠active) edits the ORIGIN
  Part and live-updates (sculpts the sound-in-transition in real time). Combines with the audio.
- **Editor** = `FUN_40052e98(enc,delta)`. Addressing (traced in the emulator): writes the param to
  `_DAT_46c82456 + DAT_100b14cf*0x18b2 + (iVar10*8+track)*0x20 + enc + 0x8f3e2`; live-update gated by
  `0x80000002==per_track_part[track] && 0x80000003==per_track_pattern[track]`. iVar10 = part of
  DAT_100b14cf (from `+0x8ed91`).
- **Discovery**: redirecting ONLY `DAT_100b14cf`→per_track_pattern makes it read/write the source
  (iVar10 still follows); + `0x80000002/03`=source passes the gate → live-update. (emu: TRANS without patch
  writes dest without sounding; with override writes source `0x90df4` + live `0x80000f94/95`.)
- **Implementation** (`tools/patch_gui.s` — SUPERSEDED by `patch_gui2.s`, it was not reentrant;
  see "Hardware crash and fix" below. m68k-elf-as+ld @0x400d6600): wrapper with **return-hook**.
  Entry `0x40052e98`→setup: if in transition, saves+sets globals to source, replaces the return on the stack
  with cleanup. cleanup restores globals + jmp to the real return (covers rts + the editor's tail-call). Save
  area `0x80006c30`, cave `0x400d6600` (no overlap with audio: cave `0x400d64e0`, RAM `0x80006a00`).
- **Validated**: transition→source+live; normal→intact; globals restored; robustness 4 tracks × 4
  encoders (incl. LEVEL=6) all ✓. Combined repackage (audio+GUI) checksums ok.
- **Caveat**: sets `0x80000002/03` temporarily (µs) for the gate; the frame builder skips sounding
  non-triggered tracks (D6 gate) → track in transition unaffected; µs risk window is negligible. Documented.

### FLASHABLE FIRMWARE CHAIN — PROVEN END-TO-END ✓✓✓
- POC patch: `COLLECT SAMPLES` → `COLLECT SAMPLEZ` in the raw MAIN OS.
- Repackaging: `elektron-firmware-tool -i orig.syx -c 3 mainos_patched.bin -o patched.syx`
  (recompresses aPLib + rebuilds ELEK + recomputes checksums).
- `-i patched.syx` → **checksums: ok**. The Octatrack would accept it.
- Byte-perfect round-trip: decompressed differs from the original by **1 byte** (the one we changed).
- → `out/OCTATRACK_OS1.40C_patched.syx` is valid, flashable modified firmware. **Full chain
  decode→patch→recompress→checksum→.syx demonstrated.**

### BEHAVIOR PATCH SITE — CONFIRMED in clean code ✓
- Frame builder D6 gate (`0x4000c9e2 beq 0x4000ca7c`): **the frame builder only applies params
  when there's a trig (D6≠0)**. → The volume jump comes from `FUN_40009094` (per-event applier).
- **Clean patch**: in `FUN_40009094`, skip the apply for SOUNDING tracks (`0x800049d8+track*0xA8` byte0).
  A sounding track keeps its params; on its first trig, the frame builder (D6≠0) applies the new Part.
  No `trig_pending`, no trig hook — the existing D6 gate is enough. Decompilable code.
- Pending implementation: nail the insertion point in the `FUN_40009094` loop (nested loops,
  SP-relative locals), assemble the cave (m68k-elf-as installed), detour, and **validate in the emulator**.

### ENCODER EDITOR PINNED (dynamic + static) ✓✓ — `FUN_40052e98`
- Hunted with `tools/emu_batch.py` (classified functions by number of params written → the 1-param ones).
- **`FUN_40052e98(param_1=encoder_idx 0-6, param_2=delta)`**: the encoder parameter editor.
  - `def = FUN_40031f28()` (param min/max). encoder 6 = LEVEL (special case 0/0x7f).
  - else: reads the current Part value (`…+0x8f3e2`), adds `param_2` (delta), clamps, writes back.
  - Writes the Part data indexed by **`DAT_100b14cf` (DISPLAYED pattern)** + dirty flag `0x9b332=1`.
  - **ALREADY integrates per-track**: only updates the live sound buffer if
    `DAT_80000003==per_track_pattern[track] && DAT_80000002==per_track_part[track]`.
    → If the track is in transition, it writes the Part but does NOT touch the sound — out of the box.
- **GUI-in-transition**: redirect the editor's write destination to `per_track_part[track]` during
  transition (same class of patch as the audio); the live-update check already uses per_track. Sizing closed.

### TWO "current" POINTERS — key to GUI-in-transition ✓
- **`DAT_80000003`/`0x80000002`** = **sounding** pattern/Part → used by the AUDIO engine.
- **`DAT_100b14cf`** = **displayed/edited** pattern → used by GUI and EDITOR (`FUN_40031da4` reads
  `_DAT_46c82456 + DAT_100b14cf*0x18b2 + …`). They are distinct: that's why after the change you see the destination
  but hear the origin.
- Editor/param definitions: `FUN_4004f5f8` (audio branch) → `FUN_40031ee0` → `FUN_40031da4`
  (descriptor selector by machine type; min@0x6a, max@0x9a). It's the definition machinery,
  not the value writer.
- **GUI-in-transition = redirect `DAT_100b14cf` (GUI pointer, SEPARATE from the audio one) toward the
  per-track origin Part during transition.** Same class as the audio patch, they don't interfere.
- Honest limit: the exact audio param value writer was NOT pinned by static analysis (scattered
  through UI). Efficient path to close it: **dynamic analysis** (ColdFire emulator, QEMU m68k style)
  observing what runs when a knob is turned. The emulator we have (`dsp56300`) is for the DSP, no use here.

### PATCH POINT (earlier, superseded) — the Part index is per-track in the hot path
- The knob→Part editor **writes the Part data** (persistent); does NOT call apply. The sound is
  updated because the per-frame compute **re-reads the active Part every frame, per track**.
- The callers of `FUN_40009094` are structural (paste part, assign part), NOT the knob editor.
  → The volume jump originates in the per-frame re-read, NOT in `FUN_40009094` (corrects the previous GO).
- **Surgical point**: `0x4000c8c6` `move.b (0x80000002).l,D0` (bytes `1039 80000002`), INSIDE the
  per-track loop (0x4000c8a2→0x4000ca90, counter D4). The value flows to `A2 → D1*0x9b340` (indexes the
  Part) at `0x4000ca44`. It's code that Ghidra reads cleanly.
- **Patch**: reserve `part_per_track[8]` in RAM; replace the 6 bytes with `jsr code_cave` (6 bytes);
  the cave does `D0=part_per_track[D4]; rts`. Maintain the array: pattern change → old Part for
  sounding tracks; first trig → active Part. Controls ALL params (not just level). **Surgical.**
- Caveat: verify whether there are OTHER re-reads of the active Part for audio (0x80000002 is read 1× in this
  function, but the function is large; confirm this loop is the main param path).

### GUI-in-transition (edit the origin Part's params while the track transitions) — FEASIBLE, the most complex
- The origin params ARE live in the engine (working buffer) during the transition.
- Elegant implementation: use **Part-applied per track** (the same as the intermediate design) also
  for the GUI → edit/display `applied_part[selected_track]` instead of the global active Part.
  This way audio and GUI share a mechanism.
- Extra cost over the intermediate design: route the **parameter editing path** and the **display** path
  through `applied_part[track]`. RE still needed: locate the knob→param editor (the write to the Part data
  is probably decodable code; the per-frame compute `FUN_4000c11a` is the one that doesn't decompile,
  but for editing you don't need to touch it). It's the most ambitious front of the ones discussed.

### Go/No-Go redone with Ghidra → **GO** (cleaner than expected)
- **`FUN_40009094` = "apply Part parameters to the voices"** (decompiles to clean C). Reads Part params
  (`part*0x9b340 + pattern*0x18b2 + track*0x1e + …`) and writes them into the voice working buffer
  `0x80000a50 + track*0x40` (16-bit per param) that the frame builder copies to the DSP double buffer.
- **It's BY EVENT, not per frame**: the frame builder compares active Part (`0x80000002`) vs. applied
  (`DAT_80001828/29`) and only triggers the reload on change. `FUN_40009094` has 9 callers, all
  event handlers (pattern/part change, load). → **That's where the volume jumps.**
- **Clean hook, NO new RAM**: the buffer `0x80000a50` already IS the "current level". To preserve the
  origin level it's enough to **NOT overwrite the LEVEL field for tracks that are sounding** inside
  `FUN_40009094`; the buffer keeps the old value (free latch). On the next trig, the normal path
  applies the new Part's level (desirable).
- "Sounding" = active voice flag in `0x800049d8 + track*0xA8` byte 0 (already read by `FUN_40000ee0`).
- Still needed for the concrete patch: (1) fix the exact offset of the LEVEL field within the params block,
  (2) insert the "skip if sounding" conditional (a code-cave possible for space), (3) test on hardware.
- This also covers the spirit of wish 2 (state preserved until manual re-trigger).

### DSP56300 toolchain ready ✓
- Disassembler built: `vendor/dsp56300` (Access Virus emulator) → `build/.../dsp56kDisassemble`.
  Usage: `dsp56kDisassemble -in blob.bin -pc <addr_hex>` (big-endian by default, 3 bytes/word).
- Validated: boot blobs disassembled (`out/dsp_disasm/mod_31000.asm`, `mod_32000.asm`) → code
  coherent with peripheral registers (`M_TCR0/1`, `M_DCR2`), parallel moves. They are init routines.
- Still needed: enumerate each module's load addresses (from the ColdFire call-sites) to disassemble
  the entirety of `out/dsp_region.bin` with the correct `-pc` per module → effects + timestretch.

### Coverage statistics (measured in Ghidra)
- ColdFire image: **2165 functions** total; **27 named/analyzed** by us (~1.2%).
  187,114 instructions, 593,744 B of code (of 1,112,560 B; the rest is data + DSP program).
- DSP program: ~62,600 24-bit words, 0 functions analyzed (toolchain now ready).

### Pending (Phase 1+)
- Disassemble `out/dsp_region.bin` by modules (with correct `-pc`) → effects + timestretch.
- Sequencer depth: p-locks, conditional locks, scenes/crossfader, LFO designer.
- MIDI subsystem (parser/sync) and UI/display framework.
- Remaining ATA handlers; large functions the ColdFire decompiler doesn't lift.
- Extract the vector table (0x400 preamble, NOT in this section) for the ISR map.

## Phase 2 — Hardware (only if needed)  [PENDING]

- UART on the PCB → boot logs (cheap, low-invasive).
- ColdFire uses **BDM** (Background Debug Mode), not ARM JTAG → live flash dump.
- Desolder flash + external programmer = last resort.

## Open questions

- Exact RAM and DAC/ADC codec (undocumented; require teardown/PCB photos).
- Do MKI (DPS-1) and MKII share the OS container format?
- Is there signature/encryption beyond checksums? (resolved by Phase 0)
- Is there any flash dump or community Ghidra project beyond OctaLib/ot-tools-io/elektron-firmware-tool?

## Sources

- Elektron support: https://www.elektron.se/support-downloads/octatrack-mkii
- elektron-firmware-tool: https://github.com/mischa85/elektron-firmware-tool
- OctaLib (Research.md): https://github.com/snugsound/OctaLib
- Elektronauts CPU thread: https://www.elektronauts.com/t/octatrack-cpu-chip-model/93304
- Modding firmware thread: https://www.elektronauts.com/t/modifying-elektron-firmware/36228
- EFF RE FAQ (legal): https://www.eff.org/issues/coders/reverse-engineering-faq

---

## Boot branding — change the displayed version (splash + SYSTEM STATUS)

**Goal**: the first screen on power-on shows `1.40C`; change it to custom text.

**Finding (RE)**: the displayed version is NOT in the MAIN OS code. It lives as text in the
**ELEK container header**, which ends up in flash starting at `0x4000` after flashing
(`FUN_4007fb84` = flash writer writes the container to flash 0x4000). Header layout:
- `0x00` `"ELEK"` (magic)
- `0x04` `"0178"` (internal version code; used by the downgrade check `< "0178"` — DO NOT touch)
- `0x08` DISPLAY version field: `"     1.40C\0"` (5 spaces + version, right-aligned,
  fixed width **10 chars**, offsets 0x08–0x11). The byte `0x12` = high byte of the aPLib section
  length (always `0x00` for an OS < 16 MB) → serves as the **NUL terminator** of the string.
- `0x12` onward: compressed aPLib section (offset **hardcoded** in the device's decompressor).

The MAIN OS reads the display via `FUN_40069848` (SYSTEM STATUS menu): `DAT_400a95c0` = first entry of
the **flash sector table** = `0x4000`; reads `0x4000 + 8 = 0x4008`, skips spaces, copies ≤10
chars. The **bootloader** (outside our container) draws the splash reading the same `0x4008` — that's
why the splash reflects the installed OS version. Editing `0x08–0x11` changes **both**.

**Hard limit**: the field is 10 chars (0x08–0x11). It can't be enlarged: the aPLib section starts
right after (0x12) at an offset the device's decompressor assumes fixed → moving it = brick. That's
why `"MAXOLYDIAN 1.40C"` (16) doesn't fit; the cap is 10 → `"MAXOLYDIAN"` was used.

**Implementation**: extended `set_version()` of `vendor/elektron-firmware-tool/main.c` so that in
ELEK the editable field starts at `0x08` (previously `ELEK_VERSION_OFF=0x0D`, only 5 chars) → now it writes
the full 10 chars of the display area. Build:
```
elektron-firmware-tool -i downloads/extracted/OCTATRACK_OS1.40C.syx \
    -c 3 out/mainos_combined.bin -V "MAXOLYDIAN" -o out/OCTATRACK_OS1.40C_LAZYPART_GUI_MAXO.syx
```
**Verified**: header `0x08–0x11` = `6d 61 78 6f 6c 79 64 69 61 6e` = "MAXOLYDIAN"; `0178` intact;
`0x12` = `00` (NUL); checksums ok; round-trip of the MAIN OS section byte-identical to `mainos_combined.bin`
(audio+GUI patches intact). 100% cosmetic change; the version code `0178` is not touched.

### Boot splash font = UPPERCASE only (verified on hardware)

When flashing with the field in lowercase (`maxolydian`) the boot splash showed **garbage glyphs**
below the Elektron logo (user's photo) — but the text WAS being drawn (confirms the bootloader
reads the version field from flash `0x4008` and paints it on the splash). The splash font (which lives in the
bootloader, outside our container) **has no glyphs for lowercase**: it's an embedded font of
~6 bits (range `0x20`–`0x5F`: space, symbols, digits `0-9`, `A-Z`), that's why `1.40C` (digits + `.` +
uppercase `C`) always looked fine. The lowercase bytes (`0x61`+) fall outside → garbage.

**Fix**: use UPPERCASE. Rebuild with `-V "MAXOLYDIAN"`. Verified header:
`0x08..0x11` = `4d 41 58 4f 4c 59 44 49 41 4e` = "MAXOLYDIAN"; `0178` intact; `0x12`=`00`; checksums ok;
round-trip MAIN OS byte-identical. **Rule for future splash brandings: only `A-Z 0-9 . space`
(and ASCII symbols 0x20-0x40), NO lowercase, max 10 chars.**

---

## SCENES subsystem (crossfader) — RE for "sticky scenes on Part change"

**User goal**: when switching to a pattern with a different Part, keep the currently selected
A/B scenes instead of loading those of the destination Part.

**Data structure (verified by decompilation):**
- Per-pattern scene selection: byte at `_DAT_46c82456 + pattern*0x18b2 + 0x8ed90` (scene A) and
  `+ 0x8ed91` (scene B). `_DAT_46c82456` = project database base; pattern stride = `0x18b2`.
- Each scene's data (p-locked params): `base + pattern*0x18b2 + scene*0x100 + 0x8f3e2`.
- RAM mirror of the selection: `0x100a4edf + pattern*0x18b2` (written by the writer alongside the project).
- Slot-in-edit flag (A vs B): `_DAT_460d169c` (1 = A).

**Key readers/writers:**
- `FUN_4003f1b4` = **crossfader/scene morph** (live, control-rate): uses the **ACTIVE** pattern
  `DAT_80000003` → reads the A/B selection (`0x8ed90/91`) → reads both scene blocks (`scene*0x100+0x8f3e2`)
  and interpolates them by the crossfader position. **This is where the scenes "change"**: on switching
  pattern, `DAT_80000003` changes and the new pattern's selection is read.
- `FUN_40052944` = scene B selection writer (manual assignment): writes `0x8ed91` in project +
  mirror `0x100a4edf` + display (`FUN_40033e3c(8,0x38,...)`). There's an analog for scene A (0x8ed90/0x37).
- Scene edit menu (COPY/PASTE/CLEAR/UNDO): `FUN_40062da0/e84/f60`, read the selection via `DAT_100b14cf`
  (DISPLAYED pattern) — GUI path.
- The **pattern-change commit** (write of `DAT_80000003`) lives in the giant event loop
  `FUN_40061a94` (store register-indirect, not a direct ref → hard to hook there).

**Part/pattern model**: the selection is stored per-pattern (0x18b2), but in practice reflects the
Part (activating a pattern loads its Part's data into the active block; patterns of the same Part
share the selection). That's why the "jump" is perceived when changing Part.

**Patch feasibility: YES.** Recommended approach (copy-on-change / "sticky"): on Part change,
copy the outgoing A/B selection to the incoming pattern's block (`0x8ed90/91` + mirror `0x100a4edf`),
so that the crossfader reads the previous scenes. Natural hook: the same Part-change path the
lazy-part patch already uses (`FUN_40009094`), carrying a shadow of the last applied pattern to know
origin→destination. **Tradeoff**: it modifies the destination pattern/Part's saved scene selection (working
copy); if the project is saved, it persists. Semantic decision pending with the user.

### Sticky scenes v1 — SUPERSEDED (`tools/patch_scene.s`, buggy; see "Sticky scenes v2" below)

`scene_stub` inserted in the detour chain of `FUN_40009094` (part-apply):
`0x40009094 -> scene_stub(0x400d6700) -> save_stub(0x400d64e0) -> ... -> jmp 0x4000909c`.
Copies the A/B selection of the outgoing pattern (carried in `LAST_PAT`@`0x80006c60`, with `INIT_FLAG`@
`0x80006c61`) to the incoming pattern's block (arg2), at `0x8ed90/91`, before the crossfader reads.
Details: base=`*(0x46c82456)`; `dst = base + arg2*0x18b2 + 0x8ed90/91`. Uses muls.l and movem in
ColdFire style (`lea -0x18,sp; movem.l ...,(sp)` — ColdFire does NOT support `movem -(An)`).
- Validated in emulator (`tools/emu_scene.py`): correct copy, respects init/same-pattern, no
  wild-writes, regs restored, SP balanced, chains to save_stub. The audio+GUI patches intact
  (scene_stub restores all state before the jmp; save_stub byte-unaltered).
- Diff vs mainos_combined: only 2 regions (detour `0x40009098` 2B + stub `0x400d6700` 134B).
- Final firmware: `out/OCTATRACK_OS1.40C_FULL_MAXO.syx` (audio+GUI+scene+MAXOLYDIAN), checksums ok,
  round-trip MAIN OS byte-identical to `out/mainos_scene.bin`.
- **Uncertainty (soft, no brick risk)**: efficacy depends on `FUN_40009094` running on the
  Part change (confirmed: the lazy-part patch that uses it ALREADY works on hw) and on the per-pattern
  selection not being reloaded after the copy (evidence: writer/readers are per-pattern → no reload).
  Worst case if the assumption fails: the scenes jump the same (harms nothing; the stub only writes 2 bytes
  of valid index to an in-range address).

### Correction: there is NO separate RAM mirror — logs `out/ghidra_mirror{,2}.log`, `out/ghidra_partapply.log`

An earlier note claimed the scene LEDs might read a mirror at `0x100a4ede/edf` that the patch
leaves stale. **That was wrong.** `0x100a4ede/edf` and `*(0x46c82456) + 0x8ed90/91` are the
**same two bytes**: the project working copy has a compile-time-constant base `0x1001614e`
(84 code sites use it directly), and part of the firmware reaches the same fields through the
pointer at `0x46c82456` instead. The offsets line up exactly:

| via pointer | absolute | field |
|---|---|---|
| `+0x8ed80` | `0x100a4ece` | (neighbouring field) |
| `+0x8ed88` | `0x100a4ed6` | (neighbouring field) |
| `+0x8ed90/91` | `0x100a4ede/edf` | **scene A / B selection** |
| `+0x8eda2` | `0x100a4ef0` | (neighbouring field) |

So writing "the mirror" would be a no-op — `scene_stub` already writes what every reader reads.
All four functions touching `0x100a4ede/edf` (`FUN_4000e79c`, `FUN_4004a100`, `FUN_40052944`,
`FUN_400a0734`) only **store** to it; none loads from it.

### Two-level scene storage (this is the real model)

- **Live working copy** — `0x1001614e + pattern*0x18b2 + 0x8ed90/91`. What the crossfader
  `FUN_4003f1b4` reads. **This is what `scene_stub` writes.**
- **Per-Part saved copy** — `0x40170f70 + part*0x9b340 + pattern*0x18b2` (+1 for B).
  Part stride `0x9b340`. `FUN_4004a100`/`FUN_400a0734` write both copies, but the live one only
  when the entry's Part/pattern are the active ones (`DAT_80000002`/`DAT_80000003`).

**`FUN_40009094` (our detour host) reads the per-Part copy, not the live one**
(`cVar2 = *(char *)(iVar13 + 0x40170f70)`, then indexes scene data by it). It does **not** write
`0x8ed90/91`, so it does not overwrite `scene_stub` — but anything it drives uses the destination
Part's selection regardless of the patch. Signature confirmed: `FUN_40009094(part, pattern)`,
matching the stub's `arg2 = pattern` read at `0x20(%sp)`.

**Open**: which copy the scene LEDs/display read is still unidentified. If they read the per-Part
copy, full stickiness needs writing `0x40170f70 + part*0x9b340 + pattern*0x18b2` too — more
invasive, since that block is what gets persisted on project save.

**Resolved** (see below): every consumer reads the live copy. Nothing extra is needed.

## Sticky scenes v2 — `tools/patch_scene2.s` (v1 was wrong)

**v1 was broken on hardware**: assigning a scene by hand after a transition got clobbered.

Root cause: v1 hooked `FUN_40009094` and treated every invocation as a pattern change,
copying the outgoing pattern's selection over the incoming one. That premise is false.
`FUN_40009094` is `apply_part(part, pattern)`, called from **10 sites**, and:

- 7 push the active pattern `(0x80000003)` as the argument;
- 3 push an **arbitrary pattern from a register** (`FUN_4002b470` D3, `FUN_4002b654` D7,
  `FUN_4004a8a4` D2), each preceded by `0x9b332 = 1` and `0x100f8598 = 1` — the
  "a parameter was edited, re-apply the Part" idiom;
- `FUN_40052944` (manual scene assign) sets those same two flags, so **assigning a scene
  reaches apply_part too**, and v1 fired as a side effect of the user's own action.

v2 ignores the arguments entirely and polls the real active pattern:

```
enforce():
    p = *(0x80000003)
    if !VALID:          STICKY = live[p]              ; first run
    elif p != LAST_P:   live[p] = STICKY ; HOLD = 4   ; pattern changed -> impose
    elif HOLD != 0:     live[p] = STICKY ; HOLD--     ; anti-loader window
    else:               STICKY = live[p]              ; user assigned -> adopt
    LAST_P = p ; VALID = 0xA5
```

A pattern change and a manual assignment are distinguishable because the index changes in
one and not the other. `HOLD` is a heuristic guarding against the Part loaders
(`FUN_4004a100`/`FUN_400a0734`) writing the destination's saved selection right after the
change; it is the one tunable parameter. RAM `0x80006c60`..`0x64`. `enforce()` is
idempotent and hangs off two hosts: `FUN_40009094` and `FUN_4003f1b4` (crossfader entry,
prologue `lea -0x3c(SP),SP ; movem.l d2-d7/a2-a6,(SP)` displaced into the stub).
Validated 9/9 in `tools/emu_scene2.py`. **Confirmed working on hardware.**

## Display of the scene selection — no GUI patch needed

All three consumers read the SAME live bytes, indexed by the ACTIVE pattern:

| consumer | what it drives |
|---|---|
| `FUN_4003f1b4` | the crossfader morph (audio) |
| `FUN_40061a94` @`0x40062c32` | publishes UI elements `0x37`/`0x38` via `FUN_40033e3c` |
| `FUN_4004d640` | the scene numbers on the LCD (`+1`, so 0-15 shows as 1-16) |

So correcting the data corrects audio and display together. `FUN_4004d5b8` (the scene trig
comparator) is the exception: it uses `DAT_100b14cf`, the DISPLAYED pattern.

`FUN_40002df4(part, pattern, scene, slot)` is NOT an LED setter — it stages 0x20 bytes of
scene parameter data per track from `0x401715c2 + part*0x9b340 + ...` into the live scene
buffer at `0x80000ed4 + track*0x40`, gated on the track's part/pattern matching the active
ones. **That gate is what makes a track in transition keep the source Part's scene params
— the real definition of "dirty".**

## LED subsystem — logs `out/ghidra_led{,map,drv,buf,enc}.log`

- State buffer `0x460ba98c`, **2 bits per LED** — `FUN_400132c4(id, state)` masks with
  `3 << (id & 7)`, and ids advance by 2. Bi-colour: one bit per die, so
  `00` off / `01` red / `10` green / `11` amber.
- Brightness is separate and 4-bit: `FUN_400135b0(id, level)`, one call per die.
- `FUN_400131a0(id)` / `FUN_400131c8(id)` set/clear a single bit (the widely-used pair).
- **Track LEDs**: `FUN_40083eb0` loops 8 tracks over an id table at `0x400a9670`, computes
  a colour state 0-3, and passes a **hardcoded `0xF` brightness** — so brightness is a free
  dimension there. Loop tail registers: `D5` = track index, `D2` = id, `D3` = id+1,
  `A3` = `FUN_400135b0`. It does NOT pop per call; it cleans `0x20` once at `0x40083fc6`,
  so a stub must push exactly the same bytes and clean nothing.
- **Trig LEDs**: `FUN_40034a44` loops 16 trigs building two local arrays, then emits them:
  colour at `SP+0xA0`, brightness at `SP+0x20`, 4 B per entry, 2 entries per trig
  (confirmed by the prologue `lea (-0x120,SP),SP ; lea (0xa0,SP),A6 ; lea (0x20,SP),A2`).
  Stock combinations: `(0,0)` empty, `(0,1)` has content, `(1,0)` selected scene.
  **`(1,1)` is never used** — that is the free slot the dirty indicator takes.

Dirty indicators: `tools/patch_led.s` (track LED dimmed to `0x5`, detour `0x40083fb4`) and
`tools/patch_trig.s` (selected scene trig amber, detour `0x40034b5e` — conveniently a
6-byte `lea`, exactly one instruction). Both use `per_track_part[track] != DAT_80000002`.
Validated 4/4 and 5/5 in `tools/emu_led.py` / `tools/emu_trig.py`.

## Hardware crash and fix — the GUI patch was not reentrant

**Symptom**: `EXCEPTION  VEC:0B  SR:2000  ADDR:000C94CA`. Vector 11 is the unimplemented
F-line trap, and the address contains no defined code — i.e. the CPU jumped to garbage.
Repro: play B1 P1, switch to B2 P1, hold `[SCENE B]` and turn a track's amp volume.

**Cause**: `tools/patch_gui.s` installed a return-hook using ONE global slot (`SAVE_RET`
`0x80006c34`) and ONE flag (`DID_OVERRIDE` `0x80006c33`), and `cleanup` jumped through
`SAVE_RET` unconditionally:

1. outer entry: `SAVE_RET = retOuter`, `(sp) = cleanup`, `DID_OVERRIDE = 1`
2. nested entry: `SAVE_RET = retInner` — **clobbers retOuter**
3. inner returns → cleanup restores, clears the flag, jumps `retInner` (fine)
4. outer returns → cleanup sees the flag already 0, skips the restore, and jumps
   `SAVE_RET` = `retInner`, **an already-consumed address** → wild jump → F-line

A second defect rode along: in step 2 the nested entry saved the *already overridden*
globals as if they were the originals, so the restore left them corrupted.

**Fix** (`tools/patch_gui2.s`): guard at the top of `setup` — if `DID_OVERRIDE` is already
set, a nested entry neither overrides nor hooks the return, and runs like stock. One slot
is then sufficient because only one override can be live. The guard branch must be `bne.w`;
`.b` is out of range (the jump crosses the whole 130-byte override block). Validated 4/4 in
`tools/emu_gui2.py`, including the nested case.

**Lesson for future patches here**: any hook that stores per-call state in a fixed global
must either guard against reentry or keep a stack. The emulator harnesses only exercised
single calls, which is why this survived validation and only surfaced on hardware.

## BANK/PTN selection: removing the 4-second countdown — logs `out/ghidra_{bankptn,timeout,countdown,timerstruct,timerrefs}.log`

Manual (Banks and Patterns): pressing `[BANK]` or `[PTN]` opens a SELECT window that
expires in four seconds; `[NO]` exits. On the unit the countdown is drawn as four boxes
that empty once per second.

**State machine** — `FUN_4005a044(_, event)` is the PTN key handler, `event` 1 = press,
0 = release:

- `_DAT_460d1742`: 0 normal, 1 key held, 2 SELECT window open
- `_DAT_460d1ab2`: set on press to `(mode != 2)` — this is what makes **press-again-to-exit
  already work in stock firmware** on both keys (confirmed on hardware). Only the timeout
  and the key LED were missing from what the user wanted.

**The timed window** — `FUN_40059f8c(text, ticks, enable, on_timeout)`:

```
_DAT_460d1e5c = window handle      _DAT_460d1e60 = on_timeout
_DAT_460d1e50 = ticks >> 2         _DAT_460d1e58 = reload
_DAT_460d1e54 = 4                  _DAT_460d1e4c = enable
```

`0xf0 >> 2 = 60` ticks per box, `_DAT_460d1e54 = 4` boxes → the four seconds.
`FUN_40056ab8` is the tick; it gates on `tst.l (0x460d1e4c)` and on expiry calls
`FUN_40056a70` (close + callback). Callers pass `enable`: PTN `1`, SELECT BANK `0`,
`BANK %c: SELECT PTN` `0` — the BANK path enables it afterwards via `FUN_40031200`
(`moveq #1,D0 ; move.l D0,(0x460d1e4c)`), whose only caller is `FUN_4007b26c`.

**Patch (2 bytes)**: `FUN_40056ab8` → `rts` (`4ab9…` → `4e75`). Safe because the whole
timer is exclusive to bank/pattern selection — `FUN_40059f8c` has exactly three callers,
all of them SELECT windows, and the tick has one caller. Closing on a trig press goes
through `FUN_40056b00` from `FUN_4007b2fc`, independent of the countdown. The four boxes
stay full and act as a mode indicator. **Confirmed on hardware.**

**Methodology note**: a scalar-operand sweep MISSES absolute-long operands — Ghidra models
those as references. That is why an early sweep found neither `tst.l (0x460d1e4c).l` nor the
writers of `_DAT_46c82456`. Use `ReferenceManager.getReferencesTo` for globals; keep the
scalar sweep only for immediates and struct offsets.

## PERSONALIZE menu structure — logs `out/ghidra_{personalize,flags,settingsblock,settertbl}.log`

OS 1.40C has **16 items**, not the 12 in the 1.40A manual (added: `SHORT SAMPLE NAME`,
`RECORD QUICK MODE`, `EXT LEN GRID-REC`, `LED BRIGHTNESS`). Three parallel arrays:

| array | address | entries |
|---|---|---|
| labels | `0x400b2a34` | 16 |
| value getters | `0x400b2a74` | 16 |
| `LED BRIGHTNESS` values (`LOW`/`MID`/`MAX`) | `0x400b2ab4` | 3 |
| setters | `0x400b2ac0` | 16 |

Contiguous, `0x400b2a34`–`0x400b2aff`, immediately followed by unrelated FILE MANAGER data
— so **they cannot be extended in place**.

- `FUN_40068e00(win)` renders: label `[i]`, then calls getter `[i]` for the right-hand
  column. Count `_DAT_460e4678`, cursor `_DAT_460e4670`, scroll `_DAT_460e4668`.
- `FUN_40068fd0(key)` handles input: calls setter `[cursor]`. Setters take `(delta, flag)`
  on the stack, add to the current value and clamp.
- Each setting is its **own 32-bit word**, not a bit in a shared mask:
  `MUTE FOCUSES TRK` `0x80000090`, `QUANTIZE LIVE REC` `0x800000ac`,
  `DIS. PAGE AUTOCOPY` `0x800000c0`, `EXT LEN GRID-REC` `0x800000cc`,
  `LED BRIGHTNESS` `0x800000d0`.
- **Free words inside the block**: `0x800000a8`, `0x800000d4`, `0x800000d8`, `0x800000dc`
  (zero references anywhere).
- No settings word is referenced by the project serializer `FUN_40086d7a`, yet the settings
  survive power cycles → the block lives in **battery-backed RAM** (consistent with the
  Startup Menu's EMPTY RESET, which the manual describes as clearing settings). A new flag
  in a free word should therefore persist with no file-format change. *Inferred, not yet
  verified on hardware.*

To add items: relocate all three arrays to the cave with more entries, repoint the
references, write a getter/setter pair per item, and raise the count.

**Item count** — `FUN_40068fa8` is the list init:

```asm
tstl 0x46c8d18c ; sne d0 ; mvsb d0,d0 ; moveq #15,d1 ; subl d0,d1   -> 15 or 16
movel d1,-(sp) ; pea 5 ; pea 0x460e4668 ; jsr 0x4007ec60            -> list_init(list, rows, count)
```

Raising the immediate to 17 gives 17 or 18 and **preserves the conditionality** of the
16th item (which depends on `0x46c8d18c`). One byte.

**Careful**: the getter and setter arrays are reached by `lea`, but the label array is
loaded as an **immediate into D5** (`move.l #0x400b2a34,%d5` at `0x40068efc`). A sweep
for `lea` alone misses it.

Implemented in `tools/patch_menu.s` + `tools/patch_flags.s`: `NO BANK/PTN TIMER`
(`0x800000d4`) and `LAZY TRANSITIONS` (`0x800000d8`, one switch for lazy part apply +
GUI-in-transition + sticky scenes + both dirty indicators). Both default to unchecked, so
an unconfigured unit behaves exactly like stock — every patch got an early-out gate.
Glyphs: `0x400b5e90` checked, `0x400b5e8e` unchecked. Setters are `(flag + delta) & 1`,
which turns both [YES] and the arrows into a toggle.

## Composition testing — `tools/emu_image.py`

**V6 froze on the logo screen while all 25 per-stub emulator tests were green.** Adding a
gate to `save_stub` shifted `restore_stub` by 10 bytes, and the exit detour at
`0x40009664` kept jumping to the old address, landing inside `save_stub`'s tail.
A second stale detour (`xf_stub`, shifted 8 bytes by the `scene_stub` gate) was found by
the same check before it could cause the next crash.

The per-stub harnesses cannot catch this: each loads a freshly assembled `.bin` at a fixed
address and tests its logic in isolation. Nothing tested whether the detours **in the
assembled image** point where the symbols ended up.

`tools/emu_image.py` runs against the real patched image and checks:

1. every detour targets **exactly a known symbol** — not merely "somewhere in the cave",
   which is what made the bug subtle: `0x400d6538` was inside the cave and inside
   `save_stub`; it just was not an entry point;
2. no target lands in the middle of another stub;
3. real execution from each detour site, flagging any PC that touches a cave byte not
   belonging to a stub (i.e. garbage);
4. no stub overlaps the next.

Verified against a deliberately re-broken image: it fails both statically and dynamically.
**Detour targets are now derived from the symbol tables at build time, never hardcoded.**

Three layers now cover a build: per-stub logic (the `emu_*.py` harnesses), image
composition (this), and reproducibility (`sysex/apply_patch.py`). Both hardware bugs in
this project — the reentrancy crash and this freeze — escaped through gaps between layers,
not through a layer.

## Feature set redefined (R2) — what was dropped and why

After instability on hardware, the spec was rewritten and the build restarted from stock:

- **GUI-in-transition: removed.** It did the *opposite* of the new spec — it wrote encoder
  edits into the SOURCE Part and deliberately kept the track dirty, whereas an encoder move
  must now *end* the transition. It was also the patch that crashed (`VEC:0B`, and a second
  `VEC:04` with `ADDR:00000000` consistent with its `cleanup` jumping through a null
  `SAVE_RET`) and the only one that overrode shared globals.
- **Amber scene-trig indicator: removed.** It scanned all 8 tracks and OR-ed the result,
  forcing a per-track property into one global light — so it latched on permanently and
  conveyed nothing. The scan was the symptom, not the cause: the track LED needs no scan
  because the painter already iterates tracks and each pass checks its own.
- **Track LED: fixed.** It was missing the `&& sounding` half of the condition that the
  original design (`HANDOFF.md`) specified — an idle track with a stale `per_track_part`
  read as dirty forever. Voice-active byte at `0x800049d8 + track*0xa8`.
- **New — encoder ends the transition** (`tools/patch_enc.s`, same hook site the removed GUI
  patch used). The destination Part's parameters no longer exist by then: `apply_part`
  computed them and `restore_stub` overwrote them, which is exactly how the track stays
  protected. So `restore_stub` now snapshots them on the way past — at that instant the
  voice buffer still holds the destination values — into `0x80006e00 + track*0x40`, and
  `enc_stub` copies them back when an encoder moves on a dirty track.

`tools/build.py` replaces the ad-hoc packing: it starts from the stock image, derives every
detour from the linker symbol tables, and aborts if any assumption about the stock bytes
fails.

## CF-card flashing — `tools/make_bin.py`

MIDI SysEx takes minutes at 31250 baud. The manual's §8.5.2 OS UPGRADE path reads a `.bin`
from the root of the CF card instead. Decoding the official `.bin` showed the ELUP payload
is simply:

    [4-byte BE length][ELEK container]

— exactly the container `elektron-firmware-tool` already builds, so no new format work was
needed, only the forward direction of the obfuscation `tools/bin_decode.py` already
reverses. `rot16` and `bswap` are involutions, so inverting is direct:

    encode: x = k ^ mixer ^ p ;  c = rot16(x) ^ XOR_A   (variant 0, k & 0x800000 == 0)
                                 c = bswap(x) ^ XOR_B   (variant 1)

with the feedback `k` being the previous **cipher** word.

Getting the patched container out: the `.syx` is 7460 SysEx messages each with its own
framing, so rather than reverse that transport, `EFT_EMIT_CONTAINER=<path>` was added to the
vendored tool (5 lines) to dump the container it already builds internally.

**Validation**: `make_bin.py` regenerates Elektron's official `.bin` **byte-for-byte** from
that file's own container. Nothing about the format is inferred. Confirmed working on
hardware.

One caveat: a container whose size is not a multiple of 4 needs the payload padded to a word
boundary (ours needed 2 bytes; the official happened to align). The device reads the declared
length and ignores the tail. `FUN_4007f748` validates the checksum and returns an error code
*before* touching flash, so a malformed `.bin` is rejected rather than half-applied.

## Lazy transitions — final shape (R10) and the LED saga

The shipped feature: on a pattern change to a different Part, sounding tracks keep the
previous Part's params (no jump), the track LED dims, and the track adopts the destination
Part on any modification — sequencer trig, manual trig, or an encoder move.

- **Audio**: `patch.s` (save/restore + destination snapshot) + `patch_enc.s`. The encoder
  path was the last piece of point (c). The destination params no longer exist when the
  encoder moves — `apply_part` computed them and `restore_stub` overwrote them — so
  `restore_stub` snapshots them into `DEST_SNAP` (0x80006e00, at the instant the voice
  buffer still holds them) and `enc_apply` copies them back. **There are FIVE encoder
  editors** (`0x40052e98`, `0x40052ae8`, `0x40053498`, `0x40053a68`, `0x4005435c`), same
  shape but different prologues; hooking only one made the feature look dead. All five are
  trampolined in `patch_enc.s`.
- **LED**: `patch_led.s`, eight instructions — `per_track_part[track] != active Part` →
  dim (`0xF`→`0x5`). That is the whole indicator, and it was ALREADY WORKING before this
  round; the user said so explicitly.

### The LED mistake, recorded so it isn't repeated

I "fixed" a working indicator and spent many hardware flashes making it worse. Root causes,
each a thing assumed rather than verified:

1. The "always dirty" bug belonged to the **amber scene-trig** indicator (removed), which
   OR-ed all 8 tracks into one light. `led_stub` never had it — the painter iterates tracks
   and each pass checks its own. I conflated the two and edited the healthy one.
2. Added a `&& sounding` test reading `0x800049d8` — a byte that **pulses** — so the LED
   flickered. The audio patch reads it once per pattern change; in a per-frame painter it is
   not a boolean.
3. Added a patch-owned dirty mask at `0x80006c70` — which the **firmware writes**, proven by
   the flicker returning exactly when the mask was present (R5/R6/R7/R9) and gone when it was
   removed (R8/R10). "Free RAM" was never verified; the earlier `GhidraRamFree` scan misses
   computed/indexed writes. Proven-stable patch RAM ends around `0x80006c64` (scene block);
   `0x80006c70` is past it.

**Rule**: when something worked and now doesn't, the first suspect is what I changed, not the
firmware. And never trust "this address looks free" — the only RAM proven safe is what an
already-working patch reads back correctly.

### Definition (R10): dim == "not yet re-trigged since the Part change"

After the LED saga, the feature was redefined around what the code naturally does rather than
chasing an encoder-clears-the-dim behaviour. The dim means: a **sounding** track that changed
Part and has **not been re-trigged**. A trig settles `per_track_part[track] = active` durably
and clears it; an encoder move does not (it applies the destination sound via `DEST_SNAP`, but
`per_track_part` is firmware-owned and re-asserted to source until a genuine trig). Under this
definition the encoder-not-clearing-the-dim is correct by design: the LED and the encoder are
two orthogonal signals — "re-trigged yet?" vs "apply the destination sound now". No further RAM
hunt or `per_track_part` lifecycle mapping is needed. (Kept for reference: `0x100f8598`, the
"param edited, re-apply" flag, has many writers and no direct reader — polled via a computed
address.)

---

## ARP key-scale (F knob) — RE map for adding scales (Greek modes / blues)

Educational investigation into extending the arpeggiator's "key scale" (ARPEGGIATOR
SETUP, F knob) beyond the stock major/minor. No binary was changed. All addresses
verified against `out/raw/section_3_MAIN_OS.bin` (file_offset = vaddr − 0x40000400);
analysis ran in a fresh fully-analyzed project at `out/ghidra_arp` (scripts:
`tools/GhidraArp*.java`).

### Mechanism (manual §15.4.4)
The F knob forces arpeggiated notes *and* the per-step note offsets onto a key scale;
it "affects the note trigs of the track even if the MODE setting is OFF" → the actual
pitch quantizer sits on the shared MIDI note-trig output path, not inside the arp loop.

### Selector — fully mapped and patchable
- **Per-track storage**: arp struct byte at `_DAT_46c82456 + pattern*0x18b2 + track*0x24
  + 0x8f273` (offset +3; +0 is the arp LEN byte). In the compact load struct
  (`FUN_400260d0`) it is field **+0x16**.
- **Encoder handler**: `FUN_4007a2ec`, branch `param==5`. Reads the byte
  (`mvz.b (1,A0),D0` @0x4007a428), min `0x400d4066`=0, count `0x400d4096`=**0x19 (25)**,
  `subq #1` → max 24, clamp, write back (`0x4007a466`).
- **Enum**: 25 states = `0` OFF, `1..24` = 12 roots × {major,minor}, encoded as one
  value: `root=(v-1)>>1`, `quality=(v-1)&1` (0=MAJ, 1=MIN). No hidden scales.
- **Label render** (`FUN_4003b790`, descriptor @0x400d40c6): draws root-note name +
  suffix from two parallel 25-entry pointer tables — roots @`0x400a7e54`, suffixes
  @`0x400a7eb8` (`MAJ`=0x400b5750, `MIN`=0x400b4419). Guard `moveq #0x18` @0x4003b7ca.
  The scale is TEXT only (root + maj/min); no keyboard is drawn — so new scales are
  cheap visually (just add suffix strings + widen the tables).

### To add qualities (major,minor → +dorian,phrygian,lydian,mixolydian,locrian,blues)
Encoding is root×quality, so 8 qualities ⇒ 1 + 12×8 = **97 states**. Selector/label side:
1. count datum `0x400d4096`: `19`→`61` (25→97).
2. formatter guard `moveq #0x18` @0x4003b7ca (`70 18`→`70 60`).
3. table-copy sizes `pea (0x64).w` @0x4003b7a0 / @0x4003b7b6 (100→388=`0x184`), enlarge
   `FUN_4003b790` stack frame accordingly.
4. rebuild both label tables to 97 entries (root ×8 per pitch class; suffix cycling
   8 abbreviations e.g. DOR/PHR/LYD/MIX/LOC/BLU) — packed literal pool, cannot grow in
   place, relocate + repoint the two `pea` bases (@0x4003b7a4→0x400a7eb8,
   @0x4003b7ba→0x400a7e54).

### Runtime quantizer — LOCATED (`FUN_4009f794`), all bytes verified
The MIDI note-trig emitter for all 8 MIDI tracks (called from `FUN_400a1608`), runs for
every track's note trigs regardless of arp MODE. Reads the scale byte from a **third RAM
mirror** at `0x46c76df1 + track*0x44` (not the project struct +0x8f273; `FUN_400260d0`
writes all three mirrors on load). Algorithm (verified):

```
scale = mirror[track][0x31]                 ; 0x4009fad2  move.b (0x31,A0),D0
if (scale == 0) noQuantize                   ; OFF
root = (scale-1) >> 1                         ; asr.l #1     (root 0..11)
K    = (scale & 1) ? 0x0C : 0x15              ; btst #0 @0x4009fae4; odd=MAJOR(12), even=MINOR(21)
local_44 = K - root
idx  = (note + local_44) % 12                 ; 0x4009fb6a moveq #0xC / divsl.l
note = note + snaptable[idx]                  ; 0x4009fb74 lea 0x400d80a0 ; add.l (A0,idx*4),D0
```

**One snap table only** @`0x400d80a0` (file `0xd7ca0`), 12×int32 =
`[0,-1,0,-1,0,0,-1,0,-1,0,-1,0]` → in-scale PCs `{0,2,4,5,7,9,11}` = **MAJOR**.
Minor has no table of its own: it reuses major rotated by the relative-major offset
(K=21 vs 12; +9 mod 12). Snapping is always DOWN 1 semitone for out-of-scale tones.

Verified byte anchors: scale read `0x4009fad2` (`10280031`); quality bit `0x4009fae4`
(`08000000`); minor K `0x4009faec` (`7415`); major K `0x4009faf8` (`760c`); OFF guard
`0x4009fb58` (`4aaeffc06f22`); table lea `0x4009fb74` (`41f9400d80a0`).

### Adding scales is FEASIBLE — two tiers
- **5 Greek modes = FREE** (all rotations of major, reuse table `0x400d80a0`, new K each):
  Dorian 14, Phrygian 16, Lydian 17, Mixolydian 19, Locrian 23 (Ionian 12 / Aeolian 21
  already present). `local_44 = K - root` stays > 0 for all roots, satisfying the guard.
- **Blues** `{0,3,5,6,7,10}` is non-diatonic → needs one new 12×int32 snap table + a
  conditional table base at the lookup `lea 0x400d80a0` (`0x4009fb74`).
- **Code change (not data-only):** rewrite the decode block `0x4009fad2–0x4009fafc`
  (~46 B). With 8 qualities the split becomes `root=(v-1)%12 / quality=(v-1)/12` feeding a
  small switch that picks K (and, for blues, the alternate table). Relocate to a code cave
  + detour (same pattern as the other patches); pair it with the selector/label widening
  above (enum 25→97 at `0x400d4096`, formatter guard `0x4003b7ca`, label tables
  `0x400a7e54`/`0x400a7eb8`).

### IMPLEMENTED — 12-quality arp key scale (`tools/patch_arp.s`, emulator-validated)

Standalone build `tools/build_arp.py` → `out/mainos_arp.bin` (stock + arp only, for
isolated testing). Cave at `0x400d7000` (inside the proven-free R10 run, clear of R10's
stubs). Adds 10 qualities to the F-knob: MAJ MIN + DOR PHR LYD MIX LOC BLU PHD MEL OCT HIR.

- **Encoding**: value 0 = OFF; 1..144 = root*12 + quality (root = (v-1)/12 slow/outer,
  quality = (v-1)%12 fast/inner). Enum count datum `0x400d4096`: 25 → 145.
- **decode_cave** (detour @0x4009fad2, replaces the 46-byte local_44 block): sets
  `local_44 = 12*quality + (12-root)` (0 for OFF). The 12*quality term vanishes under the
  stock mod-12, so the existing idx computation still yields (note-root) mod 12; and the
  lookup recovers quality as (local_44-1)/12 — so NO extra stack slot / frame change is
  needed (the prologue movem saves regs at the frame bottom, so growing the frame was
  unsafe). Division by 12 done with the magic multiply (v*171)>>11 (exact for 0..143;
  avoids ColdFire divide-form uncertainty).
- **lookup_cave** (detour @0x4009fb74, replaces `lea 0x400d80a0`): idx += quality*12;
  note += UT[quality*12+idx] (signed byte); preserves D2/D3.
- **fmt_cave** (detour @0x4003b790, replaces FUN_4003b790): computes root/quality and
  draws NOTETAB[root] + QUALTAB[quality] instead of the stock 25-entry tables. Same
  callback contract (draw suffix at pos via 0x40013a08, tail-draw root at pos+5).
- **UT** unified snap table (144 signed bytes, quality-major): MAJ/MIN reproduce stock
  `0x400d80a0` exactly; 7-note scales snap down; BLU/OCT/HIR snap to nearest. A snap-up at
  note 127 wraps to a negative byte and the firmware drops it (benign, top of MIDI range).

Validation `tools/emu_arp.py` (Unicorn): decode 145/145, lookup 18432/18432 (scale×note),
MAJ parity 0 mismatches, formatter labels correct. Composes with R10 (no detour/cave
overlap) — mergeable as a new revision. NOT yet hardware-tested.

---

## Bank load from CF is ASYNC and does NOT stop audio (enables live bank paging)

Educational RE of whether a single-bank reload halts playback (for a "page in 16 banks
mid-performance" feature). Verdict: **it does not stop the sequencer/audio, and the load
runs on a dedicated background task** — the same concurrency that streams samples from CF
while playing. Scripts: `tools/GhidraBank*.java`.

### Two-tier bank storage (new structural finding)
- **Resident bank blobs**: `0x400e21e0 + bank*0x9b340` (635,200 B/bank, 16 banks ≈ 10 MB).
  Cold store in RAM, deserialized from `<proj>/bankNN.work` by FUN_4008ded0.
- **Live working copy**: patterns at `0x46c82456 + pat*0x18b2` — filled from the blob only
  when a bank becomes current (FUN_4000faf0), gated on `DAT_80000002` = playing bank.

### RELOAD BANK call chain (verified addresses)
- Menu builder FUN_40063590 → confirm handler FUN_40063bf8.
- FUN_40063bf8: FUN_400a10c8 (reset UI/MIDI scratch — NO transport stop) + FUN_40022778
  posts job `{type=0x14, mask, begin=0x40023230, done=FUN_40023bf4}` via FUN_40000c3c to
  queue @0x460d17ce (sets ColdFire soft-IRQ 0xfc04c010|=0x800 to wake consumer).
- Consumer = dedicated task **FUN_4008445c** (created FUN_40040b94, prio 1, own 0x4000
  stack), blocking-dequeues FUN_40000d00, switch on msg type:
  - type 0x14 → FUN_4008f0b0(mask): loops bits 0..15, copies `bankNN.strd → .work` via
    FUN_40016388 (buffered FS copy, no ATA spin). On done posts type 6.
  - type 6 → FUN_400905d4(mask): loops bits 0..15, opens `bankNN.work`, FUN_4008ded0
    deserializes into `0x400e21e0 + bank*0x9b340`. For NON-playing banks: RAM fill +
    FUN_4000fa98(mask,0) only. Live re-apply gated `if (DAT_80000002==bank)`
    (FUN_4000faf0/FUN_400a1030/FUN_40009094).
- End re-sync FUN_40023998 → FUN_400238a4 (re-derive voice/engine to current position;
  clock never stops). Short-circuit this when the playing bank is not in the mask.
- Blocking "WORKING PLEASE WAIT" (0x400b68b2) is used only by OS-upgrade/other paths
  (FUN_40070db8/FUN_4006e450), NOT the reload path (which uses the non-modal
  "RELOADING BANK" 0x400b3898 overlay FUN_400808bc).

### Feasibility — "page 16 banks from a sibling project, no audio stop"
~90% exists: FUN_4008f0b0/FUN_400905d4 already accept a 16-bit bank mask and loop all 16
into disjoint per-bank regions on the background task, concurrent with audio, no stop.
To build: (1) redirect the filename builder from FUN_40025230(0,0) (current project) to a
sibling project dir; (2) trigger the type-6 job with a mask excluding the playing bank;
(3) short-circuit FUN_400238a4 when the playing bank isn't in the mask.
- "PRELOAD" (0x400be7c5) is a dead string (no xref) — not a usable primitive.
- **Hard usage constraint**: sample slots (Flex/Static pool) are PROJECT-level, not bank-
  level; parts reference samples by slot. Sibling projects must share the same sample
  pool/slot assignments, or paged banks play the wrong/absent samples. Flex RAM is not
  reloaded by a bank load either → siblings should share Flex assignments.

### HARDWARE-VALIDATED: non-playing bank loads from CF without stopping audio

De-risking experiment (throwaway builds, `tools/patch_exp_bankload.s` + `tools/build_exp.py`)
confirmed on a real MKII the assumption behind the live bank-paging feature.

Method: hooked the reload confirm handler FUN_40063bf8 (the sole caller of the poster
FUN_40022778) to (a) skip the synchronous pre-step FUN_400a10c8 and (b) force the reload
mask to a NON-playing bank `(current+1)&15`; plus NOP the end-of-load re-sync call
`jsr FUN_400238a4` at 0x400239a2 (`4ebaff00` → `4e71 4e71`).

Findings, in order (each isolated one variable):
- v1 (mask hook only, pre-step still ran): **audio cut at the instant of confirm** →
  the cut is FUN_400a10c8 (per-track note/voice scratch reset), which runs synchronously
  on confirm, NOT the async load. (Also fixed a self-inflicted VEC:04: a 6-byte detour at
  0x40022778 spilled 2 bytes into the following `lea`; resume must replicate the displaced
  `lea` and land at 0x40022782.)
- v2 (skip pre-step, non-current bank, re-sync kept): immediate cut gone; **audio cut a few
  steps AFTER confirm** → the delayed cut is the end-of-load re-sync FUN_400238a4.
- v3 (skip pre-step + skip re-sync + non-current bank): **audio kept playing through the
  entire load, no cut.** ✓

Conclusion: the async loader task filling a non-playing bank's disjoint RAM region
(0x400e21e0 + bank*0x9b340) does not disturb playback. The only two things that stop audio
are the confirm-menu pre-step and the end-of-load re-sync — both avoidable when the loaded
bank(s) exclude the playing bank. The live bank-paging feature is therefore viable; the
remaining work is plumbing (sibling-project detection, PAGE-key state machine, YES/NO popup,
redirect the load path to the sibling project dir) + the sample-pool-sharing usage constraint.

### S1 HARDWARE-VALIDATED: redirected sibling bank load, no audio stop

Bank paging Stage 1 (tools/patch_bankpage_s1.s, tools/build_bankpage_s1.py) confirmed on the
MKII. Three detours over R11: (1) gate FUN_40025230 @0x40025244 — global g_redirect (char*)
overrides the projname==0 default (0x100f8378) when set; (2) trigger at FUN_40063bf8 @0x40063bfe
— skip pre-step FUN_400a10c8, sprintf("%s_2", 0x100f8378) into a cave buffer, set g_redirect,
mask = 0xffff & ~(1<<curbank) (0x100b14ce), tail-post via FUN_40022778; (3) done at FUN_40023998
@0x400239a2 — clr.l g_redirect + skip re-sync (replicate displaced `pea (0x1).w`, resume 0x400239aa).
The RELOAD gesture loaded the sibling "<name>_2" project's 15 non-playing banks into RAM with the
sequencer running and NO audio stop; a paged bank then played the sibling's patterns. Confirms the
FUN_40025230 redirect gate + the masked multi-bank load are the correct, audio-safe mechanism.
g_redirect/sib_name live in the code cave (writable SDRAM) — worked fine on hardware.

### S3/S3b: PAGE-key bank paging UX (R12) — cycling emulator-validated

Bank paging integrated into build.py as R12 (tools/patch_bankpage.s). Three detours over the
R11 image, cave at 0x400d7400:
- **page_cave** ← FUN_4004ffc4 @entry ([PAGE] key, keycode 0x1b). Gate: edge==1 (press) AND
  in SELECT BANK (`_DAT_460d1e5c!=0 && _DAT_460d1e60==0x4007b408`) AND no popup open
  (`_DAT_460e5cd0==0`). If gated: advance g_page `(page&3)+1` (1→2→3→4→1), build the target
  name into sib_name (page 1 = base `<name>` via `sprintf("%s")`, pages 2–4 = `<name>_N` via
  `sprintf("%s_%d")`), show `FUN_4006d57c("LOAD BANKS?", 1, {&sib_name}, 3, confirm_handler)`,
  swallow the key (rts). Else fall through (replicate displaced `lea -0x10,SP`+`movem`, resume
  0x4004ffcc).
- **confirm_handler**: YES (p==0) → g_redirect=sib_name, mask=`~(1<<playingbank)`, post via
  FUN_40022778, re-enter SELECT BANK via `FUN_4007af80(0x2f,1)`. NO → nothing.
- **gate_cave** ← FUN_40025230 @0x40025244 and **done_cave** ← FUN_40023998 @0x400239a2:
  the S1 redirect + conditional-re-sync mechanism (done_cave now does the stock re-sync when
  g_redirect==0, so a normal RELOAD still re-syncs).

Validation: `tools/emu_bankpage.py` (Unicorn, runs real sprintf) — cycling + name construction
1→2→3→4→1 with correct `<name>`/`<name>_N` = ALL PASS. The core load path is the S1/S3a
mechanism (hardware-proven). **S3b's UX additions (cycling, dynamic name, PAGE hook) are
emulator/static-validated only — pending hardware test.**

Deferred (need hardware + the vtable, see DESIGN_BANKPAGE.md):
- **Existence gate**: only page when `<name>_2` exists, else stock PAGE. Recipe worked out:
  build `<name>_2`, `FUN_40025230(0, name)` → path `0x460bf112`, `FUN_40025650(path)` (nonzero
  = valid project; it checks `<path>` and `<path>/AUDIO` via the FS vtable `_DAT_46c823fa`).
  Not shipped because that vtable is uninitialized in the static image → not emulator-testable,
  and it sits on the PAGE critical path. Currently PAGE always pops the confirm in SELECT BANK
  (NO declines); a load of a missing page falls to the stock error dialog.
- **Skip-missing-page** cycling; the **page LED** (FUN_400135b0(id,0xF)); the **16th-bank
  catch-up** on bank change; the **save guard** while paged.

### Bank paging existence check — via file-open, not a dir predicate (R12, hardware-validated)

The sibling-existence check first tried FUN_40025650 (the firmware's "valid project?"
predicate). Hardware diagnostics (tools/patch_bankpage_diag.s) showed it returns 0 even for
the CURRENTLY-LOADED project (C=0) — its FS vtable `_DAT_46c823fa` does not resolve project
DIRECTORIES from this call site. Switched to a FILE-open check: existence = can we open
`<sibling>/bank01.strd` via the loader's own open helper FUN_40016864(fh, path, "r", buf,
0x10000) (D0>=0 = opened; close with FUN_4001677c). Diagnostics confirmed the sibling's
bank01.work AND bank01.strd both open (wrk=1 std=1).

Critical rule learned: **only ever open SIBLING files, never the playing project's** — a
diagnostic that opened the current project's bank01.strd and closed it made the NEXT open
fail with -2 (closing a handle the firmware holds open for playback corrupts FS state).
chk_sibling only touches `<name>_N` files, so it is safe. Validated end-to-end in
tools/emu_bankpage.py with the open/size/close vtable slots stubbed to simulate a card with
base + _2 + _3 (no _4): the PAGE cycle skips _4 and, with no `_2`, PAGE stays stock.

Open refinement (for the non-modal redesign): skip the CURRENTLY-LOADED page in the cycle
(track g_loaded, updated on YES-load, reset to base on project load) so it never offers a
useless reload of the page you are on.

### Bank paging SHELVED — the audiopool is the real blocker

Bank paging (loading sibling-project banks live) was reverse-engineered and hardware-proven to
load without stopping audio, but cancelled. Reason: it only avoids the audio stop by requiring
siblings to SHARE the sample pool. `PROJECT → CHANGE` stops playback because it reloads the
**audiopool** (samples); paging sidesteps that only by not touching samples. So paging brings in
new patterns/parts but not new sounds — too limiting, and it doesn't solve the root problem
(loading genuinely new material live). The real, unsolved frontier is a **live audiopool swap**
(new Flex/Static samples into RAM without halting the DSP/playback). Shipped firmware reverted to
R11 (arp key scales + lazy transitions). The bank-paging sources/emulators/diagnostics remain in
tools/ and DESIGN_BANKPAGE.md as documented, reusable RE.

## Audiopool / sample slots — extend STATIC 128 -> 256?  [RECON 2026-07-30]

Motivation: sibling-bank paging died because siblings must share the audiopool.
New angle: enlarge the STATIC slot count (128 -> 256). STATIC streams from CF, so
more slots cost no sample RAM — the 128 cap is purely a table/bound artifact.

### Structure (from the two free-slot allocators)
- `alloc_free_static_slot` FUN_40024098: base **0x46c90a78**, stride **0x2c (44 B)**,
  loop bound **!= 0x80 (128)**; slot[+8]==1 means "free". On overflow -> 'NO FREE
  STATIC SLOTS!' via FUN_4005a2b8(msg,0x30). Unified setter `FUN_40023f1c(type,idx,..)`
  type 0=static, 1=flex.
- `alloc_free_flex_slot`  FUN_400240e8: base **0x46c922c4**, same stride 0x2c, same 0x80.
- Table spans: STATIC 0x46c90a78..0x46c92078 ; FLEX 0x46c922c4..0x46c938c4.
  Gap static-end..flex-start = 0x24c (588 B) — NOT enough to grow in place (need 0x1600
  for +128, or 0x2c00 total for 256).
- Right after static table: another struct at 0x46c920a4 (10 refs) — static table is boxed
  in; in-place growth impossible. Relocation is the only path.

### File format = SAFE (the scary risk is gone)
Project/bank sample assignments are serialized as TEXT blocks:
  `[SAMPLE]` `TYPE=STATIC|FLEX` `SLOT=%03d` ... `[/SAMPLE]`  (serializer @0x40089xxx).
UI already renders `STATIC %03d` / `FLEX %03d` (3 digits, @0x4006df80). So more slots
neither shift fixed offsets (no corruption of saved sets) nor overflow the UI/format —
`%03d` already supports up to 999.

### Cost / risk (the real blocker)
- **NO central accessor.** Base 0x46c90a78 is inlined at **36 sites** (flex: 48), as
  absolute 32-bit immediates in heterogeneous ops: `addi.l #base,Dn`, `adda.l #base,An`,
  `lea (base),A0`. Because the value is unique, a blanket 4-byte immediate replace
  (0x46c90a78 -> newbase) mechanically relocates all 36 in one pass.
- **Need a 0x2c00 (11.3 KB) contiguous FREE RAM hole** for the relocated 256-entry table.
  BLOCKER: this lives in 0x46xxxxxx DDR, populated at runtime — CANNOT be found from the
  static flash image. Requires a runtime RAM map from hardware (allocator free-list dump
  or probing candidate regions). The 0x80006a00 fast-RAM cave is too small.
- **Every 128/0x80 bound on the static index must be found & bumped** (alloc loop, UI
  nav clamp, loader loop, serializer loop, collect-samples, ...). A missed *upper* clamp
  = only 128 usable (benign); relocation removes the adjacent-corruption danger.
- **Audio/voice streaming path** must be audited for a baked-in 128 (some of the 36 refs
  are in 0x4000xxxx voice code). Per-voice ring buffers (8 voices) shouldn't scale with
  slot count, but confirm.
- **No emulator harness** for the slot subsystem -> hardware-only verification of a
  memory-layout change = highest brick/corruption risk of anything attempted so far.

### Verdict
Feasible in principle and the file-format risk is gone, but this is a table RELOCATION
(not a counter bump): 36 immediate rewrites + N bound bumps + audio-path audit, gated on
(a) sourcing an 11 KB free RAM hole that needs HARDWARE reconnaissance, and (b) accepting
hardware-only testing. Sibling-bank rehab (base 1-128 / sibling 129-256) would further
need slot-reference REMAPPING of the sibling's patterns — a separate large step.

### UPDATE — there are TWO tables per slot, not one (cost went up a lot)
The setter FUN_40023f1c + FUN_40024510 reveal each slot has TWO parallel entries:
  1. **STATE table, 0x2c B/slot** — 0x46c90a78 static / 0x46c922c4 flex (the free flag
     `[+8]`, label at `+0x18`). STATIC->256 = 0x2c00 (11 KB) relocation. Base inline at
     **36 sites**.
  2. **PATH/SETTINGS table, 0x448 B/slot** — &DAT_100d5b30 static / &DAT_100b14f0 flex,
     in the SEPARATE 0x10000000 region. Holds the sample path + all sample settings
     (trim/loop/gain/slices). STATIC 129 entries span 0x100d5b30..0x100f8378 — and
     0x100f8378 IS the project-name global, i.e. the table is boxed in by project globals,
     cannot grow in place. STATIC->256 = **0x44800 (274 KB) relocation**. Base inline at
     **43 sites**.

Total static base-immediate rewrites: 36 + 43 = **79 sites**, but only TWO unique base
values (0x46c90a78, 0x100d5b30) -> a blanket 4-byte search-replace relocates all 79 in
two passes. So the 79 sites are NOT the bottleneck.

**Bounds are heterogeneous and tangled with the 8 recorders**: static uses 0x80/0x81,
flex uses 0x87/0x88 because the flex tables also hold 8 recorder slots at indices 128-135.
Every static-index bound must be found and bumped without disturbing recorder indexing.

**Both RAM regions look fully used**: a scan of pointer immediates finds references across
the ENTIRE 0x10000000-0x10ffffff and 0x46000000-0x46ffff7f spans (each ~16 MB, densely
referenced). No obvious fixed free hole from static analysis -> the 274 KB + 11 KB holes
can only be confirmed by RUNTIME reconnaissance (canary-paint candidate windows, operate
normally, report surviving-canary runs).

### Revised verdict
STATIC 256 = relocate TWO tables (11 KB in 0x46c9xxxx + **274 KB** in 0x100xxxxx) via
blanket base rewrites + bump heterogeneous bounds (entangled with 8 recorders) + audit the
audio/voice path + hardware-only verification (no emulator). The dominant gate is sourcing
**~285 KB of contiguous fixed free RAM across two densely-packed 16 MB regions** — doubtful
from static evidence, needs a canary-paint diagnostic on hardware to settle. Biggest,
riskiest feature attempted; payoff (128->256 static) is real but incremental.

## Live audiopool swap — why PROJECT->CHANGE stops audio  [RECON 2026-07-30]

Traced the full project-change chain. The stop is PHYSICS, not a lazy safety check.

### The chain
- `change_project_handler` FUN_40063e48: calls `need_stop_predicate` FUN_400448dc.
  - Predicate = "is anything SOUNDING right now?": loops 8 tracks, `FUN_40000e50(t)`
    voice state `& 0xffffff00 != 0` -> active; plus `FUN_4009b290(-1)` = _DAT_800065b8
    (sequencer-running flag). Returns 1 if any voice active or seq running.
  - Predicate ONLY gates the "PLAYBACK WILL BE STOPPED" warning popup. It is NOT a
    "should we stop?" gate. There is NO hidden no-stop path to exploit.
- Both branches call `do_project_change` FUN_40063e28(0), which UNCONDITIONALLY runs:
  1. `FUN_400a10c8()` — full panic/reset: clears MIDI track state (0x80006500..10),
     voice mailboxes (0x46c7e998 / 0x46c7faa4), arp state (0x46c7dfba <- 0x2d), etc.
     (This is the instant-cut culprit we already knew from bank paging.)
  2. `FUN_40008fe4(0xffffffff)` — stop ALL 8 voices (recurses, sets 0x8000184c=0xff,
     FUN_40008f84 per track).
  3. `FUN_400647a0()` — opens the CHOOSE PROJECT picker (FUN_4005829c + FUN_40064624);
     the heavy flex-RAM reload happens AFTER the user picks (cb FUN_40063ee4).
  So audio dies the instant you confirm CHANGE PROJECT, before the picker even opens.

### Flex format vs flex content
- Flex RAM FORMAT (partition layout) = DAT_80000051..56 (live copy in 0x80000000) mirrored
  to DAT_100b14b1..b6 (persistent). `reformat_flex_ram` FUN_40066784 warns "PLAYBACK WILL
  BE STOPPED" only if the target format (0x460e4550..54) differs from the live one.
  reformat_confirm rewrites those params + FUN_4009b5ac/FUN_40006890/FUN_4004bd48.
- Reformatting (repartition) is separate from loading sample CONTENT into partitions.

### The fundamental constraint (established)
Flex samples live in RAM the DSP reads in REAL TIME. Overwriting a flex partition while a
voice reads it = glitch/garbage -> the project load must kill all voices first. STATIC
samples STREAM from CF (not in the swappable pool) -> safe to reassign live (bank paging
proved this). So the audio stop is not removable in general; it's protecting live reads.

### The only glitch-free ways to change the pool live
1. **Shared/identical flex pool (siblings).** The reload writes the same bytes -> sounding
   voices unaffected. This is what was cancelled — but it is precisely the ONLY clean
   UNIVERSAL mechanism. The "limitation" (shared samples) is inherent, not a shortcut.
2. **Lazy per-partition swap** (mirrors the shipped LAZY TRANSITIONS feature): reload only
   flex partitions NOT currently read by a sounding voice; busy partitions keep the old
   sample until the voice stops/retriggers, then load. Glitch-free for the common case.
   Needs per-partition busy tracking + deferred load + retrigger hook. Substantial.
3. **Double-buffer flex RAM** (2x pool, atomic switch). Likely does not fit RAM.

### Takeaway
No free lunch: the stop is real. The realistic frontier feature is (2) a "lazy audiopool
swap" — same philosophy as lazy transitions, applied to flex partitions. The cancelled
sibling approach (1) was actually the correct clean core, just bounded to shared samples.

## Lazy audiopool swap — mechanism + design  [RECON 2026-07-30]

### The flex load is per-slot (great) but the pool is a BUMP ALLOCATOR that repacks
- Reload orchestrator `FUN_4009083c`: loops STATIC 0..0x7f then FLEX 0..0x87 (136), each:
  `if (slot has path) FUN_40096548(slot,1)`. Per-slot -> clean hook point.
- Flex pool prep `FUN_40096a5c`: per-slot unload `FUN_40096300(slot)` x136 (NOT one bulk
  wipe — but it clears every slot's size marker).
- Flex slot load `FUN_40096548(slot,1)`: unloads the slot, reads the .wav, and BUMP-ALLOCATES:
  - pool cursor `_DAT_8000691c`, pool end `_DAT_80006920`, per-slot offset table base
    `_DAT_80006918` (offset = `_DAT_80006918[slot]`), per-slot size `DAT_46c75e88[slot*2]`.
  - `if slot size==0: if (end-cur < need) OUT_OF_MEM; else off[slot]=cur; cur+=need; size=need`.
  - `else (already allocated): error 0xffffffd2` -> so a reload REQUIRES all slots cleared first.
  => The pool is repacked from base in load order every project change. A sounding voice's
     sample region WILL be reused by the repack. This is the physical reason for the stop.

### Consequence for lazy swap
Naively deferring a busy slot breaks addressing (the bump repack moves everything). A true
per-slot lazy swap needs allocator surgery: PIN busy slots (reserve their RAM so the bump
alloc for other slots skips it) + defer their new sample to a queue drained on voice-stop.
Real but invasive (touches the memory allocator + needs voice->slot busy detection).

### THE CLEAN MVP — pool-identity live project change (the sibling case, done right)
If the new project's flex table (128 x 0x448 paths at 0x100b14f0) is IDENTICAL to the
currently loaded one, the reload would produce a BYTE-IDENTICAL bump layout -> same
addresses, same data. So we can simply SKIP the entire flex teardown+reload, and skip the
voice-kill (FUN_400a10c8 + FUN_40008fe4) in FUN_40063e28. Banks/parts/patterns still load
live (bank paging proved that path is audio-safe); patterns reference flex by index -> same
sample -> correct. Result: GLITCH-FREE live project change between audiopool-identical
projects — exactly the cancelled sibling feature, but implemented at the correct layer
(project change + pool-identity detection) instead of the bank-paging hack, and honest about
the inherent shared-pool constraint.
- Hooks: (1) FUN_40063e28 — if pools identical, skip FUN_400a10c8 + FUN_40008fe4(0xffffffff).
  (2) FUN_4009083c — if new flex table == current, skip the flex loop + its prep.
- Identity test: compare the 128 flex 0x448-entry paths (or format params DAT_80000051..56
  + a path digest). STATIC differences are safe (stream from CF).
- Degrades correctly: non-identical pools fall back to the stock stop.

### Full version (later): per-slot pin-and-defer for MIXED pools
Reserve busy slots' RAM, reload only non-busy slots, queue busy slots' new samples for load
on voice-stop/retrigger. Needs: voice->slot busy map, a reserved-region bump allocator, and
a retrigger/stop drain hook. The natural evolution of LAZY TRANSITIONS applied to flex RAM.

## Live pool swap — RECORDER-PRESERVING design (user's, confirmed)  [2026-07-30]

Design (user): allow an audio CUT for everything EXCEPT the 8 recording buffers. On a
project change, reload the whole audiopool (flex 0-127 + static, any new project) but
PRESERVE the recorder buffers (flex slots 0x80-0x87) and keep their voices sounding. User
is responsible that only recorder audio is sounding during the swap. Workflow: record the
live audio into a recorder, mute all other tracks, change project (recorder bridges), then
fade into the new project's tracks.

### Confirmed mechanism
- Flex pool is PAGED: 0x1800-byte pages from a pool at **0x40a955e0**; page index tables at
  0x46c2e9c0 / 0x46c2e580 / 0x46c35bd4; bump/compaction cursor _DAT_8000691c; pool end
  _DAT_80006920; free/clear a page = FUN_40020984(page*0x1800+0x40a955e0, 0x1800).
- Recorders 0x80-0x87 reserve pages in a SEPARATE index range `(rec+2)*0x390a` (limits
  0x3908/0x3909), sized by 0x461053a8[rec] (default 0x461053c8[rec]), managed by
  FUN_40095a90 / FUN_400948cc. Distinct from the flex-slot page pool.
- `unload_slot` FUN_40096300(slot): recorder branch resets size to reserved + reclaims pages
  via FUN_40095a90 -> MUST skip for 0x80-0x87 during the swap. Flex branch frees+compacts.
- `kill_voice` FUN_40008f84(track): sets 0x8000184a bit, resets arp (0x46c7dfba[track]=0x2d),
  FUN_4000672c(track) stops the voice. To spare a recorder voice, skip the track in the kill.

### Scope
1. Trigger: a dedicated live-swap project change. REQUIRE flex format identical
   (DAT_80000051..56 / recorder reservation) so recorder pages stay at the same addresses
   and no DSP reformat runs (reformat = DSP teardown = glitch). If format differs -> abort
   or fall back to the stock stop.
2. In the load path (FUN_40063e28 + FUN_4009083c/FUN_40096a5c):
   - Spare voices reading a recorder buffer in FUN_40008fe4/FUN_40008f84 (and FUN_400a10c8).
   - Skip FUN_40096300 unload + reload for recorder slots 0x80-0x87 (preserve their pages).
   - Reload flex 0-127, static, banks, parts, patterns normally (cut is acceptable there).

### Remaining unknowns (need a bit more recon)
- VOICE->RECORDER detection: which track's voice is currently reading a recorder slot
  (0x80-0x87), to spare it. Look at the voice struct (0x800049d8, stride 0xA8) / the track's
  active machine source slot.
- Does a recorder voice keep sounding across the sequencer stop that a project change does?
  (Workflow implies a held/looping recorder playback that survives; confirm on hardware.)
- Confirm the non-reformat load path doesn't reset the DSP in a way that glitches the spared
  recorder voice (format-identical requirement should prevent the reformat DSP teardown).

### Voice->recorder detection — RESOLVED
- Voice struct: base 0x800049d8 + track*0xA8; [0]=active flag, [0x14]=type (voice_stop
  FUN_4000672c gates on [0x14]==4 for the recorder-linked path). `_DAT_461054ec` = live
  bitmask of recorder-linked tracks; `_DAT_461054f0` = the surviving recorder descriptor.
- Given the user contract (only recorders sound during the swap), detection simplifies to
  "spare every ACTIVE voice" (0x800049d8[t*0xA8]!=0), optionally refined to [0x14]==4.
  Precise track->slot mapping is NOT required.
- Only ONE teardown to skip: FUN_40096a5c unloads all 136 slots via FUN_40096300; skip
  0x80-0x87. The load loop FUN_4009083c already skips recorders (no path in the 0x448 table).
=> Full design in DESIGN_POOLSWAP.md. Contained scope, comparable to arp/bank-paging patches.

## Live pool swap — DIAG #1 result + lazy-parts pivot  [2026-07-30]

MAXODIAG build (skip FUN_40063e28 teardown + preserve recorder pages via FUN_40096a5c
0x88->0x80) tested on hardware. RESULT: still cuts. User confirmed the stock "PLAYBACK WILL
BE STOPPED" popup appears and audio cuts on the load.

Diagnosis: the teardown is NOT only in FUN_40063e28 (that only opens the picker). The real
voice teardown + engine reinit happens in the ASYNC LOAD TASK `FUN_4008445c` (a giant
on-stack trampoline dispatcher) reached AFTER the project is picked. My diag never touched
it -> net behavior looks stock. FUN_4009083c (reload) callers: 0x40084d32 / 0x400853c2 /
0x40085bb0, all inside the 0x4008xxxx load task.

User's key insight (correct): a project load is a FULL REINIT — it selects the new project's
last-saved bank/pattern, whose destination PART may not hold the recorder's flex machine. So
even if the buffer + voice survive, the new part REDEFINES the sounding track. => need the
LAZY-PARTS mechanism (already shipped for in-project part changes) adapted to bridge a
project change.

PROMISING: the load DOES route through the lazy-hooked apply_part. FUN_400905d4 (bank RAM
load) calls, for the playing bank: `if (DAT_80000002==bank){ FUN_4000faf0; FUN_400a1030;
FUN_40009094(bank,DAT_80000003); }` — FUN_40009094 is apply_part, already carrying the
lazy save/restore detours (0x40009094 entry, 0x40009664 exit). And the lazy mechanism
snapshots LIVE voice state (0x80000a50, 0x200 B) — which survives the part-data overwrite.
So lazy-parts is likely the right tool for the machine-def bridge.

STILL NEEDED (scope escalation — multi-hook feature, ~ lazy transitions size):
1. Spare the sounding recorder voice through the load task's HARD voice stop (find it in
   FUN_4008445c / the load orchestrators 0x400853c2 / 0x40085bb0).
2. Preserve recorder pages (done in diag).
3. Lazy-parts bridge: keep the sounding recorder track on its old (recorder) machine def
   across the load, via the existing 0x80000a50 snapshot, until re-trig.

NEXT RECON: (a) locate the hard voice stop in the async load task; (b) confirm whether the
project-load apply_part path triggers the lazy save/restore for the sounding recorder track.

## Live pool swap — teardown is MULTI-MECHANISM (strategic finding)  [2026-07-30]

Traced the voice-silencing during load. There is NO single choke point:
- **FUN_40006820(track)** = per-track voice stop primitive: clears the voice ACTIVE flag
  `0x800049d8[track*0xA8]=0` (the frame builder stops synthesizing when 0) + FUN_4000672c.
  Recursive for 0xffffffff. Called from MANY sites (f6890 stop-all, flex assign
  FUN_40096ab0, etc.). This is the "active flag" silencer.
- **FUN_400a10c8 (panic)** silences via a DIFFERENT path: DSP commands FUN_400a539c(0xffffffff)
  / FUN_4009f2f8 / FUN_4009da20 + mailbox clears — does NOT go through FUN_40006820. ~12
  callers in the 0x40063xxx project-menu region.
- **flex unload** kills the voice of the track reading an unloaded slot via FUN_400977cc ->
  FUN_40008f84 (kill bit + FUN_4000672c). Recorder slots preserved -> shouldn't fire for it.
- **apply_part FUN_40009094** (lazy-hooked) IS called during bank load for the playing bank
  (FUN_400905d4: `if(DAT_80000002==bank){FUN_4000faf0; FUN_400a1030; FUN_40009094(bank,ptn)}`)
  -> redefines the track (user's insight); the lazy save/restore only preserves a track still
  marked SOUNDING.

Voice TYPE field: voice[0x14]==4 (recorder/pickup) in FUN_4000672c; `_DAT_461054ec` = live
recorder-track bitmask. Note: a Flex machine pointing at a recorder buffer may be type 1, not
4 — so type==4 alone may not catch every "playing a recorder" case.

### Assessment
Bridging a live recorder voice through a project load means neutralizing SEVERAL independent
silencers (active-flag FUN_40006820 + panic DSP-command path FUN_400a10c8 + keeping it
SOUNDING so the lazy apply_part preserves its def) AND preserving pages (done). No single
hook. High hardware-iteration cost, uncertain. This is a bigger fight than lazy transitions.

Most informative next test: a diag that hooks FUN_40006820 to SPARE recorder-linked tracks
(_DAT_461054ec / voice[0x14]==4) + keeps page preservation, and see if the recorder survives.
If it does -> FUN_40006820 was the dominant path. If not -> the panic DSP path also kills it,
and the bridge starts fighting the whole load reinit.

## Live pool swap — PIVOT to a dedicated HOT CHANGE entry point  [2026-07-30]

Diag #2 result: Flex-on-recorder does NOT survive (voice[0x14]!=4, likely ==1, so the
FUN_40006820 spare missed it). Pickup untested. But the masking approach is whack-a-mole
against a flow (PROJECT->CHANGE) we don't control.

USER IDEA (adopted): add a NEW menu entry PROJECT -> HOT CHANGE with its OWN load sequence
that BYPASSES the teardowns by simply not calling them, instead of masking a flow we don't
control. We author the exact steps.

Why it's the right pivot:
- Revives the SHELVED bank-paging infra, which ALREADY PROVED audio-safe bank loading on
  hardware (poster FUN_40022778 w/ bank mask, redirect gate FUN_40025230 override,
  conditional re-sync skip). See DESIGN_BANKPAGE.md.
- HOT CHANGE = [preserve recorder pages] + [load new project's banks/parts/patterns via the
  proven audio-safe path] + [reload flex 0-127 + static, recorders preserved] + [lazy-parts
  so the sounding recorder track keeps its def]. The audio-safe machinery already exists.

METHODOLOGY FIX (important): the diag builds were from STOCK, which has NO lazy parts / sticky
scenes / arp scales. The design DEPENDS on lazy parts (to avoid redefining the recorder track
on apply_part). All further pool-swap experiments MUST be built on R11 (out/mainos.bin from
tools/build.py), not stock, so lazy parts is present.

NEXT: design the HOT CHANGE custom load (reuse bank-paging poster/redirect/re-sync-skip +
flex 0-127/static reload w/ recorder preservation + lazy-parts), built on R11.

## Live pool swap — KEY FINDING: the async load is AUDIO-SAFE  [2026-07-30]

Verified: there is NO global audio teardown (panic FUN_400a10c8, stop-all FUN_40008fe4)
ANYWHERE in the async project-load path:
- load task + steps 0x40084xxx: none
- load orchestrator 0x40085xxx: none
- project.strd + bank + flex load 0x4008exxx-0x40092xxx: none
- flex/static load+unload 0x40093xxx-0x40099xxx: only PER-SLOT voice ops (FUN_40006820 at
  0x40093ec0 static / 0x40096ad4 flex-assign; FUN_40008f84 at 0x40097856 per-slot unload).
  These stop only the voice reading the specific slot being (un)loaded — not a global panic.

=> The global audio teardown (panic + kill-all) is a SYNCHRONOUS PREFIX in the menu handler
   (0x40063xxx), NOT in the async load. The async load itself is data-only / audio-safe
   (consistent with bank paging, which posted a load job with no audio stop).

### HOT CHANGE design (flavor a, now tractable)
Do NOT replicate the load (the task is a generic table-driven dispatcher over FUN_4008419c —
impractical to reimplement). Instead: a new menu entry PROJECT -> HOT CHANGE that TRIGGERS
the stock async project load for the target, MINUS the synchronous menu-handler teardown:
  1. Open the CHOOSE PROJECT picker WITHOUT the up-front panic/kill.
  2. On pick: set target project + POST the stock async load (the real, complete load) with
     NO synchronous panic/kill.
  3. Recorder pages preserved (FUN_40096a5c 0x88->0x80, gated on a hot flag).
  4. Lazy-parts (present in R11) preserves the sounding recorder track's machine def; the
     per-slot flex-unload kills never hit the recorder (preserved) nor muted tracks (no
     active voice).
No global panic ever reaches the recorder voice. Build on R11.

NEXT RECON: find the pick->post-load trigger (how CHANGE PROJECT posts the async load after
the picker selection), to replicate just that part minus the synchronous teardown.

## Live pool swap — the load-post template (HOT CHANGE core)  [2026-07-30]

The project-load is POSTED to the load queue, panic FIRST (synchronous). Template (from the
project-menu handler that posts 0x4002325c):
    FUN_400a10c8();                         // <-- synchronous PANIC (HOT CHANGE skips this)
    DAT_460bd922  = 0x13;                    // job id
    _DAT_460bd926 = 0x4002325c;              // handler = project-load orchestrator (audio-safe)
    _DAT_460bd92a = FUN_40023cf8;            // cb1
    _DAT_460bd92e = FUN_40022dc4;            // cb2
    FUN_40000c3c(0x460d17ce, &DAT_460bd922); // POST to the load queue (same queue as bank paging)
Job descriptor table at 0x400227xx: {handler 0x4002325c, cb FUN_40023cf8/FUN_40022dc4}.
The orchestrator 0x4002325c loads the CURRENT project (0x100f8378) — for a CHANGE, the picker
sets 0x100f8378 to the target first.

Why diag #1 still cut: there are (at least) TWO synchronous panic sites on the change path —
FUN_40063e28 (before the picker) AND the load-post handler (before FUN_40000c3c). Diag #1
only skipped the first; the second killed the recorder. HOT CHANGE must skip BOTH.

### Consolidated HOT CHANGE design (final)
Reuse the ENTIRE stock CHANGE PROJECT flow (picker + select + post + async load — the load is
audio-safe, proven above). Gate on a HOT flag so we skip the synchronous teardown and preserve
recorders:
  1. Menu entry PROJECT -> HOT CHANGE: arm g_hot, then run the stock change (open picker).
  2. Skip FUN_400a10c8 + FUN_40008fe4 at BOTH synchronous sites when g_hot (FUN_40063e28 +
     the load-post handler).
  3. FUN_40096a5c unload bound 0x88->0x80 when g_hot (preserve recorder pages).
  4. Lazy-parts (already in R11) preserves the sounding recorder track's def; per-slot flex
     unload kills never touch the recorder (preserved) or muted tracks (no active voice).
  5. Clear g_hot at load-done.
Exact panic/kill sites on the change path to be pinned during implementation (iterate on
hardware like bank paging v1/v2/v3). Build on R11.

## HOT CHANGE prototype — v1 result, v2 (panic gate)  [2026-07-30]

v1 (on R11: skip FUN_40063e28 teardown + preserve recorder pages, LAZY on): still cuts.
User confirmed: LAZY was enabled, and the cut happens AFTER selecting the project (during
load) -> the SECOND synchronous panic (the load-post handler's FUN_400a10c8) killed the
recorder. Not the apply_part redefinition (lazy was on).

v2 (MAXOHOT, tools/patch_hotchange.s + build_hotchange.py, on R11):
- cave @0x400d7240 (R11 free run 0x400d7223+): hot_change + hot_panic + g_hot.
- detour FUN_40063e28 -> hot_change: arm g_hot=1 + open picker (skip panic+stop-all).
- detour FUN_400a10c8 -> hot_panic: if g_hot, one-shot disarm + rts (skip); else stock
  panic (replicate `lea -0x24(sp),sp; movem.l D2-D5/A2-A6,(sp)`, jmp 0x400a10d0).
- in-place FUN_40096a5c 0x88->0x80 (preserve recorder pages).
- LAZY parts (R11) bridges the recorder track's def.
One-shot rationale: FUN_40063e28's panic is no longer routed through FUN_400a10c8 (the cave
replaces it), so the first FUN_400a10c8 after arming IS the post-handler panic. Self-healing
on picker-cancel. Awaiting hardware result.

## HOT CHANGE v2 result + v3 (re-sync skip)  [2026-07-30]

v1 test was INVALID (flex track level was 0 -> nothing sounding). v2, with the recorder
actually sounding: it SURVIVED the whole load and cut only AFTER the project finished loading.
=> panic gate + recorder-page preservation WORK; the remaining cut is the end-of-load RE-SYNC
FUN_400238a4 (called via `jsr (d16,PC)` from FUN_40023998 @0x400239a2) — the same one bank
paging had to skip.

v3 (MAXOHOT3): adds hot_done hooking 0x400239a2 (mirror of bank paging's done_cave): if g_hot,
disarm + SKIP the re-sync (replicate `pea (0x1).w`, jmp 0x400239aa); else stock re-sync. Also
moved g_hot disarm from hot_panic (one-shot) to hot_done (load-done) so the panic gate stays
armed through the whole load. Awaiting hardware result.

## HOT CHANGE v3 fail -> v4 (hook the re-sync FUNCTION)  [2026-07-31]

v3 still cut (SYSTEM STATUS confirmed MAXOHOT3). Root cause: FUN_400238a4 (re-sync) has FOUR
call sites (0x40023936 create, 0x400239a2 bank-reload done, 0x40023a4a FUN_40023a08,
0x40023afa FUN_40023ab8). v3 hooked 0x400239a2 = the BANK-reload done; the PROJECT load
re-syncs from FUN_40023ab8 (0x40023afa). So the project-load re-sync ran (cut) AND g_hot never
cleared (stuck armed). FUN_40099680 (slot finalize) returns early for active recorder slots
(state[+8]!=0, param_3==0) -> does not disturb the recorder; the cut is purely the re-sync.

v4 (MAXOHOT4): hook FUN_400238a4 ITSELF -> if g_hot, one-shot disarm + rts (skip); else stock
(replicate `move.l A2,-(sp); jsr 0x4009b220`, jmp 0x400238ac). Covers all 4 sites; the re-sync
is the per-operation load-done so one-shot is safe. hot_panic reverted to skip-while-armed (no
clear; the re-sync hook now owns the disarm). Awaiting hardware result.

## HOT CHANGE v4 -> v5 (skip recorder unload everywhere)  [2026-07-31]

v4 result: PROGRESS — audio cuts but the SEQUENCER KEEPS RUNNING (panic gate + re-sync skip
worked; no full stop). The remaining problem: the recording buffer of the sounding flex track
reinitializes to EMPTY.

Cause: FUN_40096300 (slot unload) is called from a SECOND site — a per-slot step inside the
load task FUN_4008445c @0x4008598e — not just the prep FUN_40096a5c. So the recorder slots
0x80-0x87 got unloaded (reset size to reserved + reclaim pages) despite the prep-loop skip.

v5 (MAXOHOT5): hook FUN_40096300 ITSELF -> hot_unload: while g_hot, if slot in 0x80-0x87,
return success WITHOUT unloading (covers every unload call site). Removed the in-place
FUN_40096a5c 0x88->0x80 (was ungated / affected all ops); the gated hook replaces it. Hooks
now: hot_change + hot_panic + hot_resync + hot_unload, all gated on g_hot. Awaiting result.

## HOT CHANGE v5 -> v6 (skip recorder page reclaim)  [2026-07-31]

Scope narrowed by user: preserve ONLY flex tracks pointing at a recording buffer, and only
those matching source<->dest (their setup: track 7 = flex on a recorder, in every project).
Since both projects have track 7 = flex-on-recorder, the machine DEF matches -> apply_part
doesn't change it; only the buffer CONTENT (pages) must survive.

v5 result: sequencer runs, but audio cuts after select AND the sounding track shows a
COMPLETELY DIFFERENT waveform + recorder empty -> the recorder PAGES were REUSED by a flex
sample. Root cause: the load task, after the reload (FUN_4009083c @0x40085bb0), runs a
per-recorder loop `FUN_40095a90(rec) [reclaim] ; FUN_400948cc(rec) [realloc]` @0x40085bfc that
FREES the recorder pages (reclaim) -> reused. hot_unload (FUN_40096300 skip) did not cover
this direct reclaim.

v6 (MAXOHOT6): add hot_reclaim hooking FUN_40095a90 -> if g_hot, skip (rts). Keeps the
recorder pages held; FUN_400948cc realloc then no-ops (pages already present, `if *psVar6!=0
stop`). Hooks: hot_change + hot_panic + hot_resync + hot_unload + hot_reclaim, all gated on
g_hot. Awaiting result.

## HOT CHANGE — ROOT of the recorder wipe: FUN_40096f24 (full pool reinit)  [2026-07-31]

v7 result: still fails; but "can't stop the sequencer after the change" CONFIRMS g_hot stayed
armed (hot_panic kept skipping the STOP panic). So hot_unload + hot_reclaim DID fire and still
didn't preserve the recorder -> the wipe is elsewhere / upstream.

ROOT FOUND: FUN_40096f24 (called @0x40085ba0 in the load task, right BEFORE FUN_4009083c
reload) is the FULL FLEX POOL RE-INIT:
  _DAT_8000691c = 0; _DAT_80006920 = 0x390a;        // reset flex cursor + recorder boundary to top
  rebuild free page table 0x46c2e9c0 = 1..0x390a
  clear all flex slot metadata (0x46c922c4 / DAT_46c75e88)
  FUN_40020984(0x40a955e0, 0x5590800)               // ZERO the ENTIRE ~89MB PCM pool
  loop recorders 0x80-0x88: re-establish reserved sizes + FUN_400948cc(rec)
So a project load ZEROES the whole flex pool (flex + recorder PCM) and rebuilds. This is the
real teardown for flex audio (a data wipe, not a voice stop) — and it wipes recorder content.
All prior hooks were downstream of this.

Implication: preserving recorder content across a project load requires making FUN_40096f24
recorder-preserving (skip zeroing the recorder pages + keep the boundary + keep the recorder
metadata/page-table for the preserved recorders) — substantial allocator surgery — OR a
snapshot/restore of the recorder content (needs free RAM for MBs of audio; the RAM blocker).
Recommend building a flex-allocator EMULATOR (like emu_arp.py) to design/validate the
recorder-preserving reinit in software before flashing, to stop the blind hardware iteration.

## HOT CHANGE — allocator emulator validates the recorder-preserving reinit  [2026-07-31]

Built tools/emu_pool.py: faithful model of the flex paged allocator (reinit FUN_40096f24,
rec reserve FUN_400948cc, rec reclaim FUN_40095a90, flex bump alloc). Page geometry: NPAGES
0x390a, page 0x1800, base 0x40a955e0. Free list = band 0 of 0x46c2e9c0; recorders MOVE pages
out of the free list (from the TOP) into their bands; flex bumps from the BOTTOM. Recorders
always hold the HIGH physical pages; flex the low ones.

Design (validated): a recorder-preserving reinit = a FLEX-ONLY reinit —
  - KEEP the current boundary _DAT_80006920 (don't reset to 0x390a) -> recorder region stays reserved
  - cursor _DAT_8000691c = 0
  - rebuild free list ONLY [0..boundary): 0x46c2e9c0[i]=i+1
  - zero ONLY the flex region (pages 1..boundary), NOT the recorder pages (boundary+1..0x390a)
  - clear flex slot metadata (0..0x7f) as stock does
  - SKIP the recorder loop entirely (recorders kept, held by hot_unload/hot_reclaim)

Emulator results: PASS 4/4 scenarios (typical / 8-recs / 64s-24bit / 16-flex-slots) — recorder
pages identical, content kept, ZERO flex<->recorder page overlap. And STOCK-vs-PRESERVE
comparison reproduces the bug: stock reinit LOSES recorder content (kept=False), preserve
KEEPS it (kept=True). Confidence high before hardware.

NEXT: implement the flex-only reinit as a g_hot-gated hook on FUN_40096f24 (cave reimpl of
the flex portion), restore proper g_hot lifecycle. Then one hardware flash.

## HOT CHANGE v8 — recorder-preserving reinit implemented (emulator-validated)  [2026-07-31]

Implemented tools/patch_hotchange.s hot_reinit: hook FUN_40096f24 -> when g_hot, a FLEX-ONLY
reinit (keep boundary, cursor=0, rebuild free list [0..B), clear flex metadata 0..0x7f as
stock, skip pool zero + recorder loop). Mirrors emu_pool.py reinit_preserve exactly (PASS
4/4 + stock-vs-preserve reproduces bug). Restored hot_resync one-shot g_hot clear (so STOP
works again after the change). 6 hooks total, all gated on g_hot; only affects HOT CHANGE,
normal loads stay stock. ColdFire fixups: cmpi/move-#imm can't target memory -> via register.
Build: out/OCTATRACK_MAXOHOT.bin (MAXOHOT8). Awaiting CF mount + hardware test.

## HOT CHANGE v8 result + WALL on recorder content  [2026-07-31]

v8 (recorder-preserving reinit): project loads, STOP works, recorder RESERVATION preserved
(size 1.33 shown) — but the recorder CONTENT is SILENCE after the change (manual re-trig of
track 7 = silence; no waveform, no BPM). User tested correctly (sequencer stopped, record
trig removed from destination) -> NOT the record trig; the PCM pages were wiped.

But: exhaustive search finds NO uncovered zero of the recorder pool region (0x40a955e0):
- FUN_40020984 (memset) has only 2 call sites: 0x40097012 (INSIDE FUN_40096f24 -> replaced by
  v8) and 0x4000fd46 (zeroes the BANK blobs 0x400e21e0, not the flex pool).
- FUN_40095a90 reclaim (which zeroes recorder pages per-page) is skipped by hot_reclaim.
- FUN_40096f24 zero + recorder loop replaced by hot_reinit.
So no known path zeroes the recorder pages, yet they end up silent. The recorder content/
playback model has a dependency not yet mapped (possibly a separate "committed" copy, a
content flag, or a non-FUN_40020984 memset). RE not converging after ~8 hw iterations.

Honest status: the POOL STRUCTURE problem is SOLVED (no crash/overlap, project loads, STOP
works, reservation preserved, emulator-validated reinit). The recorder AUDIO CONTENT bridge
is blocked on an elusive wipe. Realistic paths: (1) robust snapshot/restore of R7's content
pages via a CF temp file (brute-force, sidesteps the mechanism, ~230KB, substantial); (2)
deeper RE of the recorder playback/content model; (3) consolidate the (large) progress.

## HOT CHANGE — MILESTONE: recorder CONTENT is fully preserved  [2026-07-31]

Runtime diagnostics (v10/v11) DEFINITIVELY show v8 works at the pool level:
- v10: R7 (rec6) band[0] = page 14602 (top, non-zero) -> band intact; boundary = 14374
  (not reset to 0x390a=14602) -> reservation preserved.
- v11: content word of an R7 page = 0xF96DFE36 (NON-ZERO, audio-like) -> the recorded PCM
  survives the load. The flex-only reinit (v8) fully preserves the recorder audio + pages.

So the pool-structure problem is SOLVED. The remaining "silence" is PLAYBACK/METADATA: the
audio is in the pages, but the load resets the recorder's playback-enabling metadata (recorded
length / trim points / BPM — user saw the BPM vanish), so the engine treats R7 as empty.

PLAN: snapshot/restore R7's metadata structs around the load (content already preserved by v8):
  - 0x448 settings struct: 0x100b14f0 + slot*0x448 (trim/loop/slices/BPM)
  - 0x2c state struct:      0x46c922c4 + slot*0x2c  (state/length/label)
  - recorder metadata:      0x46c938c4 + rec*0x2c
  - sizes: 0x461053a8[rec], 0x46c75e88[slot]
Small (~2KB), deterministic, sidesteps finding the exact reset. slot=0x80+rec.

## HOT CHANGE v13 — recorder metadata snapshot/restore (THE FIX)  [2026-07-31]

Diag v12 confirmed: after the load, R7 content word = 0xF96DFE36 (preserved) but the recorded
LENGTH field (0x2c struct +0x10) = 0. So the load resets the recorder's playback metadata
(length -> engine sees empty -> silence/no waveform/no BPM), while v8 preserves the audio.

FIX (v13): snapshot R7's metadata while intact (in hot_change, before the load) and restore
it at load-done (in hot_resync, after the reset). Content is already preserved by v8; only the
metadata needs bridging.
  - 0x2c state struct  @0x46c939cc (44 B) -> snap_2c   (holds +0x10 length, state, label, gen)
  - 0x448 settings str @0x100d52a0 (1096 B) -> snap_448 (trim/loop/slices/BPM)
  memcpy = FUN_40020898(dst, src, len) (verified). Buffers live in the cave (writable SDRAM).
Hardcoded to R7 (rec6) for the prototype. If it plays -> generalize to all sounding recorders.
Cave 1608 B @0x400d7240 (fits the R11 free run). Build MAXOHT13. Awaiting hardware.

### v15 (MAXOHT15) — keep track 6's VOICE alive across the swap  [2026-08-01]

v14 result (hardware): pool + metadata fully preserved — R7 shows waveform + BPM and
RE-SOUNDS when the sequencer hits its trig — but the live voice still cuts ~1 s in. User's
decisive observation: *during load all tracks flip to STATIC, then to the part's machine*;
the cut is the machine-reassign stopping the playing voice, NOT the pool/metadata.

RE of the voice-stop path (Ghidra listing — these fns are hot-path, decompiler emits empty):
- `FUN_40006820(track)` = per-track voice-stop primitive: clears the active byte
  `0x800049d8+track*0xA8`, clears the voice command slot `0x80004898[...]`, bumps a gen
  counter `0x80004a68+track*0xA8`, and sends the DSP note-off `FUN_4000672c(track)`.
  `track<=7` stops one; `track>=8` recurses over all 8.
- `FUN_40096ab0(track)` = flex machine-assign: writes machine-type `0x40` to
  `0x46c80354[track]`, THEN calls `FUN_40006820(track)` to kill the voice, then writes the
  slot into the project data. This is the load's "apply flex machine → voice dies".
- `FUN_4000672c` (DSP note-off) is reached ONLY from `FUN_40006820` and `FUN_40008f84`.
- `FUN_40006890` (stop-ALL-8) is called ONLY from `reformat_confirm` — never in the load
  path. So during CHANGE PROJECT the ONLY way track 6's voice is stopped is the
  `FUN_40006820` ENTRY. `apply_part` (FUN_40009094) itself only writes params (no stop).

Fix: 7th detour `hot_vstop` on `FUN_40006820` entry — while `g_hot` and `track==6`, `rts`
(skip the stop). Displaces 8 bytes (2f0a 2f02 222f000c = 3 instrs); trampoline replays them
and `jmp 0x40006828`. `FUN_40096ab0` still writes the (matching) flex machine-type + slot,
so track 6 ends correctly configured but is never silenced → the buffer should sound
continuously across the swap. build_hotchange.py now nop-pads detours that displace >6 B.
Pending hardware test: does R7 now sound WITHOUT the ~1 s cut?

### v16 (MAXOHT16) — timing hypothesis: disarm fires BEFORE the killing apply  [2026-08-01]

v15 (hot_vstop gating FUN_40006820 for track 6) had ZERO effect on hardware, yet pool +
metadata are provably preserved (waveform/BPM show) → g_hot IS armed during the load. The
only consistent explanation: the voice-stop of track 6 happens in the POST-load part-apply
(sequencer re-applies the destination Part → machine reassign → FUN_40006820), which runs
AFTER hot_resync has already `clr.l g_hot`. So when FUN_40006820(6) fires, g_hot==0 and
hot_vstop is inert. Fits all 4 observations: preserved metadata (hot_resync ran), voice cut
~1s in (post-load apply), v15 no-op (disarmed by then), re-sounds on trig.

v16 = DIAGNOSTIC: removed `clr.l g_hot` from hot_resync (leave armed). If track 6 now sounds
CONTINUOUS across the swap → hypothesis confirmed → add proper disarm-on-first-track6-trig
(8th detour on FUN_40005030, arg0=track). If still cuts → stop is a non-FUN_40006820 path.
Caveat of the diag build: g_hot stays armed → track 6 unstoppable + hot_panic keeps skipping
panics → power-cycle after the test.

### v17 (MAXOHT17) — the note-off funnel FUN_4000672c was the leak (emulator-found)  [2026-08-01]

Built tools/emu_hotchange.py: a Unicorn tracer of the REAL patched image that seeds the
load-context globals (0x400d7c48=0 "load active", 0x400d7c4c=6 active track), seeds all 8
voices alive + machine=flex + voice-type(+0x14)=4, runs in supervisor mode (so move-from-SR
in the stop body doesn't fault), and logs every call to the voice-stop/note-off primitives +
writes to track6's voice-active byte and the note-off side-effect 0x461054ec, with g_hot.

Findings (no hardware):
- A. flex-assign(6) DISARMED: FUN_40096ab0->FUN_40006820(6) clears voice byte @0x4000685e AND
  writes note-off fx 0x461054ec @0x400067a0 -> track6 silenced. Ground truth.
- B. flex-assign(6) ARMED: hot_vstop swallows it -> no clear, no note-off. OK.
- E/F. FUN_40008f84(6)/FUN_40008fe4(6): reach FUN_4000672c (the DSP note-off) WITHOUT going
  through FUN_40006820 -> NOT covered by hot_vstop. On the real DSP this note-off silences
  track6 even though the CPU voice-active byte stays set (emulator can't see DSP audio, only
  the note-off write). THIS is why v16 (g_hot armed) still cut after the static-reset.

FUN_4000672c is the SINGLE funnel to the DSP note-off (only FUN_40006820 and FUN_40008f84
call it). Fix v17 = 8th detour hot_noteoff on FUN_4000672c entry: g_hot && track==6 -> rts.
Emulator re-run confirms E/F now hit hot_noteoff and emit ZERO note-off fx write -> track6
cannot be silenced by any path while armed. Displaces 8B (4feffff0 48d7003c); nop-padded.
v17 still keeps disarm OFF (diagnostic) to hold g_hot through the post-load window. If HW
confirms continuous audio -> v18 adds proper disarm-on-first-track6-trig.

### v17 REGRESSION + revert  [2026-08-01]

Hardware v17 (hot_noteoff on FUN_4000672c): audio cut ABSOLUTELY for the whole load,
returned only at load-end. So gating FUN_4000672c is WRONG: that function is voice
ALLOCATION (0x461054ec free-mask + ff1 slot pick + voice-struct probe), not a pure DSP
note-off. Skipping it for track 6 corrupts the voice. The emulator green-lit it falsely
because it only sees the CPU-side write to 0x461054ec, not the DSP audio -> KEY LIMIT of
emu_hotchange.py: it validates *who writes what*, never *is sound produced*.

Reverted: removed the hot_noteoff detour (kept the source stub). Back to best-known v16
(hot_vstop only, disarm off).

Honest architectural read: a project load rebuilds the whole audio engine. We preserve the
recorder BUFFER (pool+metadata) and the voice RETURNS at load-end, but keeping the live
voice continuous THROUGH the load means freezing track 6 across many teardown/rebuild sites,
none of which the emulator can audio-verify. Machine-type writers: FUN_4000db98 sets 0x40
(flex), FUN_4000e018 sets 0x1d; no clean bulk "reset to static" write found -> the visible
"all tracks -> static" is likely a transient display default, not a single gate-able write.

### Global-DSP-mute hunt — CONCLUSION: no global mute exists  [2026-08-01]

User picked "hunt the global DSP mute". Investigated the DSP MMIO (0x20000000) + the frame
handler FUN_4000a8fc (cmd 0x8b, acks int-ctrl 0xfc04801d). Its guards:
- 0x80001860: NOT global — set by FUN_40005214 only when a track's machine-type == 4
  (== the RECORDER-BUFFER-PLAYBACK machine, i.e. track 7's machine). FUN_40005214 configures
  that machine's loop timing (0x80001866 = loop len, 0x8000186a) and is reached via
  FUN_40096ab0(flex-assign) -> FUN_400972fc -> FUN_40005214. Per-track setup, not a mute.
- 0x80000028 bit0: a PROJECT setting (written by project_settings_serialize) — not a load mute.
- 0x46104ca8: its clearer FUN_40056c40 has NO direct callers (vectored) — not in the load path.
- DSP reprogram (FUN_400e1292 via FUN_400e136c): FUN_400e136c is a ROOT (no callers) = boot
  only. The project LOAD does NOT reprogram/reset the DSP.

=> There is NO single global audio-disable toggled by project load. Consistent with v16's
FLICKERING audio (on-off-on), not a clean global off (only the CORRUPTED v17 gave clean-off).
The cuts are inherent PER-TRACK voice reallocation during load: the only clean CPU-side clear
of track6's voice-active byte is FUN_40006820 (already gated by hot_vstop, which recovered the
most); the residual dropouts come from the DSP voice-allocator FUN_4000672c, which CANNOT be
gated without corrupting the voice (v17). Fully-seamless-through-load likely needs a deeper
engine change. Useful byproduct: machine TYPE 4 = the recorder-playback machine (track 7's).

### v18 (MAXOHT18) — index-agnostic gate: protect type-4 recorder voices  [2026-08-01]

Addressed the "am I even targeting the right track?" concern. hot_vstop no longer hardcodes
track==6; it reads voice[track]+0x14 (0x800049ec+track*0xA8) and protects the stop only when
type==4 (recorder-buffer playback). At stop time the voice type still reflects the OLD state
(FUN_40005214 sets type-4 AFTER the stop), so this reliably catches the live recorder voice.
Emulator H1/H2: type=4 voice PROTECTED (no clear, no note-off); type=0 voice NOT protected
(FUN_4000672c runs, voice cleared). Binary question for HW: if "6" was already right, behaves
like v16; if index was wrong, this fixes targeting. disarm still OFF (diagnostic).
Type-4 recorder-playback uses GLOBAL state: 0x80001860(enable) 0x80001866(loop len) 0x8000186a
+ 0x400d7c4c(active recorder track) -> next lever if v18==v16: preserve/keep-active that global
recorder state for the live track across the load.

### v19 (MAXOHT19) — gate the OTHER release caller, fix v17 the right way  [2026-08-01]

v17 corrupted the voice by gating FUN_4000672c (voice ALLOCATOR) directly. Correct approach:
FUN_4000672c has exactly 2 callers (FUN_40006820 -> hot_vstop; FUN_40008f84 -> NEW hot_vstop2).
Gate BOTH callers for a type-4 recorder voice => FUN_4000672c is NEVER called for that voice
(so its DSP slot is never released) while FUN_4000672c itself runs untouched for everything
else (no corruption). hot_vstop2 = 9th detour on FUN_40008f84 (EXPECT 4feffff448d7040c), same
type-4 detection. Emulator: E (f84(6) type-4) + F (fe4(6)->f84) now hit hot_vstop2 and DO NOT
reach FUN_4000672c (previously they did). disarm still OFF (diagnostic). Best-reasoned seamless
attempt: closes the f84->672c leak that survived v16/v18 without the v17 corruption.

### v19 result + CONCLUSION of the seamless hunt  [2026-08-01]

MAXOHT19: SAME as v16/v18 — cuts during load, returns at first trig, buffer survives. So
gating BOTH callers of FUN_4000672c for the recorder voice (emulator-proven: FUN_4000672c
never called for track 6) made NO audible difference.

DEFINITIVE (proven, not guessed):
- buffer (pool+metadata) preserved end-to-end
- track index correct (7=idx6; v18==v16)
- voice-active byte preserved (hot_vstop)
- EVERY CPU-side voice stop/release gated for the recorder voice (FUN_40006820, FUN_40008f84,
  FUN_40008fe4; FUN_4000672c never reached) -- emulator-confirmed
- no global DSP mute; DSP not reprogrammed during load
- AND IT STILL CUTS during the load, resuming at the first trig.

=> The during-load cut is NOT a gate-able CPU-side voice stop. It is inherent to the audio
PRODUCTION/transport being reconfigured by the project load: the recorder-buffer playback is
trig-driven (returns at the next trig), so the load's transport/sequencer/frame-production
reset stops the playing voice by a mechanism orthogonal to the per-voice stop primitives.
Preserving that would require reverse-engineering the frame builder's per-track production
condition + the DSP voice playback state and freezing them across the load -- a large effort
that STILL can't be verified without hardware (DSP not emulated). This is the practical limit
of surgical patching for "seamless DURING load".

WHAT WORKS AND IS WORTH SHIPPING: buffer fully preserved across CHANGE PROJECT, playback
resumes at the first trig. Recommend productizing this (proper disarm + PERSONALIZE toggle),
optionally with an auto-retrig at load-end to tighten the resume to load-duration.

### CF TEXT LOGGING capability found + debug instrument  [2026-08-01]

The frame builder can't be emulated (Unicorn/QEMU-m68k crashes on bfextu @0x4000c8a6 and
lacks ColdFire EMAC MAC/MSAC used throughout the audio hot-path) -> no frame-level emulator
verification is possible. Replaced it with HARDWARE observability via the firmware's own file
primitives (user's idea: reuse the OT crash/log mechanism).

Found: FUN_4001ff2c writes "/LOG %s.txt" using
  FUN_40016864(&fh, path, "w", iobuf, size)  open   (mode string "w" @0x400b328b)
  FUN_400166b8(&fh, buf, len)                write  (the missing primitive)
  FUN_4001677c(&fh)                          close
  FUN_40013a08(dst, fmt, ...)                sprintf
Also: "EXCEPTION"/"SSP:%01x VEC:%02x" @0x400b43cc = the crash handler display.

Built tools/patch_hotdbg.s + build_hotdbg.py (MAXODBG1): two detours, pure observability.
- FUN_40063e28 (change) -> log "BEFORE" track-6 state
- FUN_400238a4 (end-of-load re-sync) -> log "AFTER" + flush to /HOTDBG.TXT
Logs per line: p=playflags(0x800018a6) t=timing(0x80001886) m=mtype(0x46c8036c)
v=voice-active(0x80004dc8) e=rec-enable(0x80001860) k=active-rec-track(0x400d7c4c).
Buffers: logbuf+fh in the cave; iobuf reuses the OT log buffer 0x460261e0. sprintf formats hex.
Comparing BEFORE vs AFTER on real hardware will show EXACTLY what the load clears in track-6's
play-state -> designs the apply_part gate from data, not guesses. Reading: pull CF, cat /HOTDBG.TXT.

### MAXODBG1-3 findings + MAXOHT20 (fix+diag)  [2026-08-01]

CF logging works on hardware (user's idea). Instrumented stock CHANGE PROJECT (MAXODBG1-3):
- MAXODBG1: my assumed play-state addresses (0x800018a6 playflags, 0x80001886 timing,
  0x46c8036c mtype, 0x80001860 rec-en, 0x400d7c4c rec-track) are ALL 0 even while the voice
  plays. Only voice-active v(0x80004dc8 byte0)=FF. => those were the WRONG targets; a fix on
  them would have been blind-wrong. Log caught it.
- MAXODBG2/3 (voice struct 0x80004dc8 diff): the ONLY clean, deterministic destructive change
  the load makes is o0 (active flag) FF000000->0. Other diffs (o44/o48/o4C/o50, o90..oA0) are
  playback POSITION/phase counters that naturally ADVANCE (time passed). o18's byte 0x1a
  oscillates FF/01 across runs = dynamic, not a stable mute. Sample pointers (o4=0x46c939cc
  recmeta, o8=0x100d52a0 settings, o68-74 buffers, o14 slot 0x86) are PRESERVED.

So the load's clean destructive act = clear o0 (via FUN_40006820), which hot_vstop gates. Yet
the fix still cuts -> decisive question: does hot_vstop actually keep o0=FF on hardware?
MAXOHT20 = full fix + hc_diaglog: at armed hot_resync logs V0/V18/V44/V90 of voice[6] to
/HOTDBG.TXT. If V0=FF -> hot_vstop works, cut is elsewhere (frame builder / DSP frame, not the
voice struct). If V0=0 -> a second o0-clearer exists that we haven't gated.

### MAXOHT21/22 — ROOT CAUSE FOUND (hardware-observed) + hot_recmeta fix  [2026-08-01]

MAXOHT20 diag (V0=0): the type-4 detection in hot_vstop (v18+) was WRONG -- the recorder
voice's type byte (voice+0x14) is 0x01, not 4 (MAXODBG2 v14=0x01860001). The EMULATOR
"validated" type-4 only because the harness SEEDED the fake value -> false confirmation. Only
the CF log exposed it. Reverted hot_vstop/hot_vstop2 to hardcoded track 6 (confirmed correct,
v18==v16). MAXOHT21: V0=FF000000 -> o0 now preserved on HW; audio bridges ~1s then cuts,
resumes at trig.

ROOT CAUSE (via FUN_40007960 RE + the diag): FUN_40007960 is the PER-FRAME recorder-voice
processor (sole caller FUN_40004008 = root/vectored audio path). It takes the PLAY path
(produces R7's DSP frame) ONLY if the recorder metadata at voice+0x4 (=0x46c939cc) has
state(+0x8)==0 AND length(+0x10)>0; otherwise it jumps to 0x40008110 -> FUN_40006820 (stop).
hot_vstop blocks that stop so o0 stays FF, but the voice is then ACTIVE-BUT-UNFED = silent.
The load invalidates R7's metadata ~1s in; we only restored it at hot_resync (load-end) = too
late (hence "resumes at trig").

FIX (MAXOHT22): hot_recmeta = 9th detour on FUN_40007960 entry (EXPECT 4e56ff7448d73cfc). While
g_hot, memcpy 0x46c939cc <- snap_2c (0x2c) at entry EVERY frame -> R7's metadata is always
playable -> FUN_40007960 always takes PLAY -> R7's frame produced continuously. Recorder pages
preserved by hot_reinit so the restored handle stays valid. Pending HW test.

### MAXOHT22 result + FUN_40007960 is EMULATABLE (decision function)  [2026-08-01]

MAXOHT22 (hot_recmeta): audio bridged NOTICEABLY LONGER after CHANGE PROJECT, then still cut,
resumes at trig. So hot_recmeta fixed the FIRST mute gate (recorder metadata state/length) but
a later gate remains.

BREAKTHROUGH: FUN_40007960 uses NO ColdFire EMAC -> Unicorn RUNS it (tools/emu_recvoice.py).
So the per-frame PLAY/MUTE DECISION is emulatable (the frame builder itself is not). Findings:
- MUTE-stop (0x40008110, ->FUN_40006820) triggers on: meta+0x10(length)<=0, meta+0x8(state)!=0,
  meta+0x14(gen) != voice+0x10, o0 inactive, voice+0x4(meta ptr)==0. hot_recmeta+hot_vstop clear
  all these -> passes to 0x400079cc.
- MUTE2 (0x4000812c): after the metadata checks, `tst.b D5(arg0x1c); bne skip; tst.b D4; beq MUTE2`
  where D4 = FUN_40001598(voice). FUN_40001598 is a recorder STREAMING check: reads voice+0x14
  (type), voice+0x15 (slot 0x86->rec6), voice+0x5c/0x60 (play position), tables 0x46c7ff42[rec]
  and 0x46c7fe24[rec] (recorder write/limit positions); returns 0 (=>MUTE2) if no data available
  at the position. The load disturbs this streaming state -> the residual cut.

So recorder playback depends on MORE than metadata: also the streaming position tables
(0x46c7ff42/0x46c7fe24) + voice+0x5c/0x60. NEXT: use emu_recvoice.py to pin the exact streaming
state that yields PLAY-complete, then either preserve it per-frame (extend hot_recmeta) or detour
FUN_40007960 to force the PLAY path for track 6. The emulator now verifies the decision, so the
next build is not blind. Progress ladder: nothing -> 1s -> "noticeably longer".

### MAXOHT23/24 — the wall: a transient race on the recorder length (ml)  [2026-08-01]

MAXOHT23 (per-frame settings 0x448 restore): WORSE — audio SCREECH (corruption). The 0x448
settings struct is read LIVE by the DSP; per-frame overwrite tears it. Reverted. Lesson:
per-frame restore is safe ONLY for CPU-side bookkeeping (metadata), NOT DSP-read data (settings).

MAXODBG4 (capture PLAY vs LOAD external state): the ONLY disturbed field is ml (recorder
metadata length 0x46c939dc): PLAY=0x556BC -> LOAD=0. Tables (t1/t2), position (p5), settings[0]
(s0), state (ms) all PRESERVED. So o0 (hot_vstop) + ml (hot_recmeta) is the complete disturbed set.

MAXOHT24 (fix + min-ml diag): mlmin=0 -> ml DOES hit 0 during the load despite the fix. hot_recmeta
restores it at FUN_40007960 entry, but that runs AFTER the frame builder (FUN_4000c8a4) in the frame
cycle (the tick FUN_4000a8fc sends DSP cmd 0x8b only after the buffer is built). So the frame builder
reads ml=0 in the window before hot_recmeta's first restore -> silent frame -> the voice mutes.
=> RACE. Per-frame restore can't win it (frame builder reads first, un-detourable: bfextu+EMAC).

The ml clearer is elusive: the two functions that clear the recorder metadata length by index
(FUN_40096f24 @0x400970ba, FUN_40096300 @0x40096524) are BOTH already gated (hot_reinit/hot_unload).
Other clr.l(0x10,An) sites operate on different structs (e.g. FUN_40093814 uses base+0x46c90a78).
So an un-pinned early-teardown path clears ml once, before hot_recmeta can cover it.

STATUS: progress ladder nothing -> 1s -> noticeably longer -> "continues after the change, stops
during load". Real progress, deep understanding, powerful tooling (CF logging + FUN_40007960 is
emulatable). But the residual is a transient race in a deeply timing-sensitive subsystem; robust fix
needs pinning + gating the early ml-clearer (elusive) or restoring ml before the frame builder
(un-hookable). Diminishing returns. Options: keep hunting the clearer; productize the partial bridge;
or pivot to the hardware-proven RELOAD path (no audio stop, but shared samples).


================================================================================
## SESSION STATE + NEXT STEPS  [2026-08-08]  (authoritative current state)
================================================================================

### WHERE WE ARE
The 256-static-slot feature is being built by RELOCATING the tables to the verified-free DDR
hole, on PRISTINE STOCK (out/stock_mainos.bin -- Phase 1 is abandoned: it clobbered the DSP).
Everything is gated by emulation before flashing (tools/emu_check.py etc.: "green in emu ->
boots on hardware" has held).

CURRENT IMAGE: out/mainos_max256.bin / out/OCTATRACK_MAX256N.bin  (sha 0ceca542..., built by
tools/build_max256.py). WHOLE-BLOCK relocation, static still 128 (neutral). READY TO FLASH but
NOT YET TESTED on hardware (the prior whole-block build hung the splash from a bug now fixed).

Layout in the hole [0x46c94074, 0x46ceb400):
    STATE-256    [0x46c96000, 0x46c98c00)   state base 0x46c90a78 -> 0x46c96000 (36 refs, blanket)
    FLEX+STATIC  [0x46c98c00, 0x46cdf640)   whole block [0x100b14f0,0x100f7f30) moved by
                 DELTA=0x36be7710 (166 OPERAND refs); flex_new=0x46c98c00 static_new=0x46cbd240
    boot-zero [0x46c96000, 0x46cdf640) via hook @0x4001fa64 (NOT the DSP -- that was Phase 1's bug)
Above the hole: 28-byte record array @0x46ceb400 (ptr var 0x46c8c5b8; grows up) caps it.

### HARDWARE TEST HISTORY (this feature)
1. passthrough-on-stock (build_state_stock.py): BOOTED perfectly -> validated pipeline+plumbing+gate.
2. MAX256N static-only reloc, base only: booted, project loaded, but samples empty/trimmed/no slices.
3. + settings FIELD refs rebased (folded offset addi #base+0x10e): static slot table EMPTY.
   -> revealed the leak: flex+static are ONE contiguous 264-slot array (static=flex+136*0x448),
   accessed flex-relatively; relocating static-only can't catch those.
4. WHOLE-BLOCK but moved ALL 4-byte values in range (no opname filter): splash-screen HANG
   (coincidental non-operand values + mid-instruction windows corrupted). 
5. WHOLE-BLOCK with opname filter (166 refs, == Phase 1's clean count): CURRENT, untested.

### LESSONS (hard-won, do not repeat)
- Relocation MUST filter by opname (operand position); moving every in-range 4-byte value corrupts
  code -> hang. build_phase1.py had this; the whole-block rewrite dropped it (bug #4 above).
- flex+static settings are ONE 264-slot contiguous array -> relocate the WHOLE block by one delta,
  never static-only (bug #2/#3). Moving everything by one delta preserves ALL relative addressing.
- Settings has field accessors with the offset FOLDED into the immediate (addi.l #(base+0x10e),dN
  where dN=slot*0x448) -> not the exact base literal; a range-scan (not exact-match) catches them.
- Double-duty addresses need classification: 0x100d5b30 = static base AND flex-walk end;
  0x100f7f30 = static end (block-end bounds MOVE) AND global-above base (2 pea KEEP).
- emu harness CATCHES: DSP register writes, loop access coverage, helper contracts. MISSES: full
  boot / project-load / UI, coincidental-value corruption (until opname-filtered), flex-relative
  semantics. Add checks per new routine.
- Root cause of the whole early crash saga: Phase 1 mis-identified DSP structs (count 0x390A ->
  DSP reg 0x80006920; struct 0x40a955e0) as pool slots. STOCK is the only correct baseline.

### NEXT STEPS
1. FLASH MAX256N (0ceca542) -> expect: boots, altre-galassie loads with static samples, SOUND,
   correct trim + slices, flex still OK. If yes: the full relocation is proven on hardware = a
   solid working base (still 128 static, behaviour-identical).
2. THE 256 FEATURE (the actual goal) -- OPEN PROBLEM: flex(136)+static(256)=392 slots*0x448=430KB
   does NOT fit the 350KB hole. Options to solve first:
     (a) enlarge the window: relocate the 28-byte record array @0x46ceb400 too (extend the hole up),
     (b) find/verify a different >=430KB free DDR region (emu_ddr_free-style),
     (c) reconsider whether flex must stay 136 or the extra static can live separately.
   Then: open static bound guards #128->#256 (subset of 81 cmpi #128; classify carefully),
   free-flag init (falls out of opening the init loop's bound; boot-zero already covers 256),
   UI caps (AUDIO list, per-track SLOT param).
3. Every change emu-gated (emu_check + a coverage/access check for the touched routine) before .bin.

### TOOLS
- tools/build_max256.py       -- current whole-block relocation build (the feature-in-progress)
- tools/build_state_stock.py  -- passthrough state accessors on stock (the proven de-risk)
- tools/patch_state_helpers_b.s + verify_helpers_b.py -- dual-table state redirect (if we go that way)
- tools/emu_check.py          -- pre-flash gate (DSP + state helpers); MANDATORY before any .bin
- tools/emu_ddr_free.py       -- verify a DDR window is free (neighbour access coverage)
- Package: EFT_EMIT_CONTAINER=out/x.bin elektron-firmware-tool -i downloads/extracted/
  OCTATRACK_OS1.40C.syx -c 3 out/mainos_max256.bin -V TAG -o out/NAME.syx ; make_bin.py -> .bin
- Recovery: sysex OCTATRACK_OS1.40C.syx (slow) ; CF .bin OS UPGRADE needs a booting OS first.


### CRITICAL FINDING: settings is a SUB-REGION of a loaded project BLOB  [2026-08-11]
Whole-block MAX256N (sha 0ceca542) HARDWARE result: boots clean (no hang, no corruption),
patterns + parts load, but BOTH flex AND static slot tables are EMPTY / do not populate.
Root cause: the settings block [0x100b14f0,0x100f7f30) is NOT independently loaded -- it sits
inside a LARGE contiguous SRAM project-data region (52+ distinct struct bases scanned in
[0x10090000,0x100b14f0), and data continues up through 0x100f7f30+). The project LOAD writes this
whole region as a BLOB to fixed SRAM (via a base BELOW 0x100b14f0, not a literal we can rebase).
Relocating only the settings sub-region's 166 code refs moves the READS to DDR, but the LOAD still
writes the OLD SRAM -> relocated reads see the boot-zeroed DDR = empty slots. (Static-only left
flex in SRAM so flex loaded; whole-block moved flex too -> both empty. Consistent.)

=> RELOCATION OF SETTINGS IS INFEASIBLE (can't move a sub-region of a blob-loaded structure).
=> DUAL-TABLE (settings A stays in SRAM, loads fine; B in DDR for slots 128-255) is the only
   path, BUT has two hard problems to solve: (1) walk/combined loops break at the A/B boundary
   (need trampolines -- 7 known, technique proven), and (2) slots 128-255 have NO load path (the
   project blob is 128-slot; the sibling project's 128-255 settings would need a load route into
   settings-B). State (0x46c90a78, 44B) may have the SAME blob-load issue -- verify before assuming
   the state relocation "worked" (in test #2 the slot table showed, but that may have been the
   field-0x10e display path, not real load).

NEXT SESSION -- change of plan required:
1. FIND + UNDERSTAND THE PROJECT LOADER: where project.work is read from CF and written to the
   SRAM project region. Identify the blob base + the settings sub-offset + how many slots it loads.
   (grep for CF read -> SRAM write; the settings live at blob_base + fixed_offset.) This determines
   EVERYTHING about whether 256 is feasible and how to load slots 128-255.
2. Given the loader, choose: (a) intercept/extend the loader to also populate settings-B (DDR) for
   128-255 and redirect random-access reads there (dual-table), OR (b) relocate the WHOLE project
   blob (huge, likely infeasible), OR (c) reconsider the feature scope with the user.
3. The current whole-block relocation (build_max256.py) is a DEAD END for settings -- keep as a
   record but do not pursue. State-relocation cleanliness is UNVERIFIED (may share the blob issue).
The unit is fine on stock; MAX256N boots but is non-functional (empty slots). Revert to stock.


### FOLLOW-UP: reloc LOOKS correct but DDR settings don't populate  [2026-08-11 cont.]
Dug into the loader: there are dozens of `pea 0x100b14f0; jsr <serializer>` (project SAVE/LOAD
in 0x40085xxx) and a descriptor store `movel #0x100b14f0 -> 0x460bdc8c`. In out/mainos_max256.bin
ALL of these ARE rebased to 0x46c98c00 (0 remaining 0x100b14f0), and emu confirms the serializers/
combined loops access the DDR block. So the relocation is byte-correct, yet on hardware flex+static
slots stay empty. => the failure is NOT a missed ref. Two leading hypotheses for next session:
  (A) the "free" hole [0x46c96000,0x46cdf640) is NOT actually free at runtime -- stock uses it via
      COMPUTED pointers (project-load scratch buffer / sample cache / a structure between the flex
      state table end 0x46c94074 and the record array 0x46ceb400). emu_ddr_free only probed a few
      routines; it can't prove a 300KB region unused. A collision would let the load write DDR then
      get overwritten -> empty. VERIFY: trace runtime writes into the hole (broader emulation of
      project-load / audio init), or pick a window proven free by more than static refs.
  (B) a load-init/default subtlety (block expected pre-initialised to non-zero defaults, boot-zero
      gives zeros; or an auto-load timing).
RELOCATION HAS HIT DIMINISHING RETURNS -- every flash exposes another subtle trap (blob-adjacency,
now possible hole-collision). STRATEGIC PIVOT for next session:
  * DUAL-TABLE instead: keep flex+static settings in SRAM (where the loader demonstrably works --
    static-only test #1 loaded flex fine), add settings-B in DDR ONLY for new slots 128-255,
    redirect ONLY the random-access playback accessors for idx>=128 (leave all load/save/walk/
    combined paths on SRAM untouched). Then solve the ONE remaining hard thing: a LOAD ROUTE for
    slots 128-255 (the project blob is 128-slot; the sibling project's 128-255 need to get into
    settings-B somehow -- maybe a second load pass, or copy-from-slot-0..127 as a starting point).
  * OR invest in a fuller project-load emulation to definitively test hypothesis (A) before any
    more flashing.
The unit runs fine on stock; MAX256N boots but slots are empty (non-functional). This session
proved the relocation MECHANICS are byte-correct; the blocker is now runtime data flow, which needs
either dual-table (sidesteps it) or real load-path tracing.


### HYPOTHESIS A RESOLVED: the hole is FREE -- it is NOT a runtime collision  [2026-08-12]
Ran two independent no-flash tests (tools/scan_hole.py + tools/emu_ddr_free.py):
  1. STATIC: scan every operand-position pointer literal in stock for a value inside the hole
     [0x46c96000, 0x46cdf640). RESULT: ZERO hits. The DDR neighbourhood [0x46c90000,0x46cf0000)
     occupancy map is: state tables (0x46c90a78 x36, 0x46c920a4 x10, 0x46c922c4 x48, 0x46c93a24
     x10, 0x46c93c28 x14) all BELOW 0x46c94000, then NOTHING until the record array 0x46ceb400 x2.
     The hole is a genuine gap -- no statically-addressed structure lives in it.
  2. EMU TRACE: static_slot_scan / flex_slot_scan read the state tables and stop below 0x46c94074;
     record_array_init writes only at/above 0x46ceb400. No traced routine writes into the hole.
=> Hypothesis A (stock overwrites the relocated DDR at runtime -> empty) is FALSE with good
   confidence. The clean-EMPTY, stable failure signature (patterns/parts load, no crash, no
   garbage, just zeros) corroborates: a collision would show corruption/instability, not pristine
   zeros. Pristine zeros = the loader NEVER WROTE the DDR = it wrote the OLD SRAM base.

=> Therefore the blocker is the LOAD-BYPASS, not the hole. The project loader populates settings
   through a path that is NOT one of the 166 rebased refs. The pea-0x100b14f0 cluster (0x40084xxx)
   is a generic TOKEN serializer framework (primitives 0x400204a8/cc scan slot names for '/' '.';
   walker 0x4008f3f0 = read-only count of flex+static). The real per-slot resolver at 0x40084c8e
   HARD-CAPS at 128: `cmpil #128,d2; blss; clrl d1 (=NULL for idx>=128); else #0x448*idx+0x100d5b30`.
   So the settings serializer is structurally 128-slot AND a stock project file only stores 128.

BOTTOM LINE for 256: relocation is a dead end for a reason deeper than the hole -- even done
perfectly, the loader writes SRAM. And 256 real slots = a FILE-FORMAT change (serializer capped at
128, project files store 128). Confirmed the ONLY viable path is DUAL-TABLE with a bespoke load
route for 128-255, AND that requires changing what a project file contains. Big scope; needs a
product decision with the user about whether the underlying goal (fast switch between sibling
128-slot projects with different slot->sample maps) is better served by stock's existing project-
switch (zero firmware risk) than by a 256-slot format.
New tool: tools/scan_hole.py -- occupancy map of a DDR window by operand-position pointer literals.


### WAVE 0 STATUS — getter-only foundation, EMU-GREEN, PACKAGED  [2026-08-12]
tools/build_dual256.py -> out/mainos_dual256.bin -> out/OT_dual256_w0.{syx,bin} (round-trip verified).
Contents: helper family @0x400d7400 (emu-verified 170/170); boot-init stub @0x400d64e0 (assembler-
generated zero+fill of the 4 B-tables, detour @0x4001fa64); ONE migrated function -- the canonical
settings getter 0x4006da78 (clamp 0x4006da88 #128->#255; add 0x4006da98 -> jsr h_set_d0).
Emu proof: boot stub zeros hole + fills all 4 B-tables + returns to boot seq; getter idx 0-127->A,
128-255->B, 256+->NULL; emu_check ALL GREEN (DSP untouched). Boot-safe by construction; NOT user-
observable yet (getter-only). Purpose of this flash: confirm the FOUNDATION (B-tables+boot-init+
helper plumbing+clamp) boots on hardware without bricking -- the prerequisite de-risk before adding
multi-add functions. NEXT (Wave 1): audio-bind + loop-setter functions behind an OOB emu-gate (run
each migrated fn at idx=200, assert no access into 0x100f7f30+ or flexstate = catches a missed add),
then the UI slot-param cap so 128-255 are selectable+audible. build_dual256.py CORE dict grows per wave.


### ★ WAVE-0 HARDWARE RESULT #1 (boot-init ON): booted, but EMPTY SLOTS + CLOCK RESET  [2026-08-12]
Flashed OT_dual256_w0 (getter migrated + boot-init zero+fill of [0x46c96000,0x46cb9e00)). Result:
BOOTED with NO crash (foundation mechanism is boot-safe!), BUT after loading a project the static
slots are EMPTY and the unit asked to SET THE CLOCK on boot. The getter is byte-identical to stock
for idx<128, so it cannot cause this -> the BOOT-ZERO of [0x46c96000,0x46cb9e00) clobbers a RUNTIME-
LIVE DDR region. => HARDWARE PROOF that the "free hole" is NOT free: it holds live data (slots +
clock/settings) accessed via register-relative/computed pointers, which the static scan (absolute
refs only) and the limited emu trace could not see. Hypothesis A is resurrected WITH hardware proof.
Consequence: scan_hole.py / emu_ddr_free.py are necessary but NOT sufficient — a region with zero
absolute refs can still be a live heap/buffer. Need a DDR region proven free by a stronger method
(broad runtime write-trace, or place B-tables above the true top of OS DDR usage).

DIAGNOSTIC BUILD (BOOTINIT=False in build_dual256.py) -> OT_dual256_diag: getter migrated, boot-init
REMOVED (boot hook 0x4001fa64 intact). Only diffs vs stock: getter 2 patches + dormant helper cave.
Expected: behaves 100% like stock (idx<128 identical; B never read) -> if slots load fine, the getter
mechanism is proven harmless and the SOLE remaining problem is finding a genuinely-free B-region.


### ★ WAVE-0 HARDWARE RESULTS #2/#3 + ROOT CAUSE: boot-zero CORRUPTS THE PROJECT  [2026-08-12]
Flashed getter-only diag builds (boot-init OFF): #2 clamp opened #128->#255, #3 clamp KEPT #128
(getter emu-identical to stock for every real input). BOTH still showed empty static slots -> looked
like the getter was guilty. It was NOT. Ground-truth reflash of STOCK ALSO showed empty slots ->
the PROJECT FILE was corrupted. Proof: universi/altre-galassie/project.work = 2877 B (truncated),
vs the good sibling altre-galassie_2/project.work = 15034 B; project.strd was intact/identical.
=> ROOT CAUSE: Wave-0 #1 (boot-init ON) boot-zeroed [0x46c96000,0x46cb9e00), which is RUNTIME-LIVE
DDR used by project load/save; that corrupted the in-memory project, and on power-off the OT
auto-saved a TRUNCATED project.work. Every later flash then loaded the already-broken project.
FIXED by copying project.work from altre-galassie_2 -> altre-galassie (corrupt saved to scratchpad
altre-galassie_project.work.w0corrupt as evidence).

LESSONS (critical):
- NEVER re-flash a boot-init build that zeroes a not-proven-free DDR region: it silently corrupts
  the LOADED PROJECT on the CF (persisted on auto-save), not just RAM. Cost us 3 flashes + a project.
- The getter migration is now PLAUSIBLY INNOCENT (empty slots were the corrupted project, not the
  getter) but NOT yet confirmed -- must retest a getter-migrated build on the RESTORED project.
- [0x46c96000,0x46cb9e00) is LIVE (hardware-proven): the B-tables need a genuinely-free region,
  found by a stronger method than static scan / limited emu (both said "free" and were WRONG twice).

NEXT:
1. On STOCK (currently flashed), load altre-galassie -> confirm slots restored (validates the fix).
2. Retest getter-innocence: flash OT_dual256_noclamp (boot-init OFF, getter jsr, clamp #128) and
   load the RESTORED project. Slots present -> getter mechanism cleared. Slots empty -> getter guilty.
3. REAL blocker: a truly-free DDR region for the 4 B-tables. Options: trace runtime writes broadly
   during project-load+audio to map used DDR; or place B-tables ABOVE the top of OS DDR usage
   (the record array 0x46ceb400 is the last known fixed structure -- probe well above it); or use a
   region the OS demonstrably never touches (needs a runtime-write census, not a static one).


### ★ DUAL-256 FOUNDATION WORKING ON HARDWARE  [2026-08-13]
Full chain of hardware results this session resolved every blocker:
1. B-tables must live ABOVE the OS working-DDR region. The OS boot-clears [0x46025de0, 0x4763d580)
   (loop at 0x40000518/0x4000f984); putting B inside it corrupted the project. Moved B to 0x47700000
   (STATE-B 0x47700000, STRIDE4-B1 0x47701600, B2 0x47701800, SETTINGS-B 0x47701a00, end 0x47723e00).
   HARDWARE: project loads perfectly, zero corruption. Region is SAFE.
2. The boot-init stub must be REGISTER-TRANSPARENT: the detour point 0x4001fa64 sits between
   `d0=a0+514` and `cmpl 0x100fff00,d0` -- clobbering d0/a1 reset the clock + emptied boot state.
   Fixed with individual move.l push/pops (ColdFire movem has no predecrement). HARDWARE: no clock
   reset, boots normally.
3. The getter migration is INNOCENT -- the earlier "empty slots" were a CORRUPTED PROJECT
   (altre-galassie/project.work truncated to 2877 B by the w0 boot-zero; restored from _2's 15034 B).
4. WAVE-1 (4-function playback migration: getter+activation 0x4009367c+trackenable 0x40093e9c+slice
   0x40094334; 7 per-slot adds redirected, 5 clamps opened) loads + plays altre-galassie perfectly.
   Multi-function migration mechanism VALIDATED on hardware. (Stock-identical for 0-127 -- no track
   references 128+ yet, so no visible change; this was the de-risk checkpoint.)

Static OOB GATE (build_dual256.py scan_slot_adds): after redirect, asserts ZERO un-redirected
per-slot base-adds remain in any opened-clamp function [entry,end). enum_fn.py gives TRUE extents
(next-prologue, not first-rts which undercounts -- it missed slice's 3rd add 0x400946f8). This makes
adding more functions safe: a missed add = OOB write into the working region = corruption, and the
gate catches it before flashing.

CURRENT STATE: OT_dual256_wave1 flashed + working. B boot-filled with copies of slots 0-127
(placeholder). Redirect helpers emu-verified 170/170.

NEXT -- OBSERVABILITY (the blocker to SEE/HEAR 128-255): a normal 128-slot project never sends
idx>=128 to the migrated functions (slots 0-127, sentinel -1 -> NULL), so nothing is visible yet.
To reach idx 128 need EITHER (a) open the per-track STATIC SLOT UI cap 127->255 (agent hunting it),
OR (b) edit a project/bank to reference slot 128 on a track. Then a track at slot 128 plays B[0]
(= placeholder copy of slot 0) -> the end-to-end proof. After that: the SIDECAR loader for real
128-255 data (the actual feature).

TOOLS added: enum_fn.py (true function extents + per-slot add census), scan_slot_adds OOB gate in
build_dual256.py. Packaged builds: OT_dual256_wave1.{syx,bin} (current), OT_stock.bin (recovery).


### ★★★ WAVE-2 HARDWARE: 256 SLOTS WORK END-TO-END  [2026-08-13]
OT_dual256_wave2 (7 functions migrated: 4 playback + popup browser render 0x40077b04/apply
0x40079428/0x400796a4; 14 adds redirected, 11 clamps opened; list-length cap 0x40079238 128->256).
HARDWARE RESULT: scroll to slot 255 works; LOADED a real sample into slot 128 -- it loaded with ALL
settings (name, SLICES, etc.) and PLAYS; project loads fine, all slots sound. The dual-256 feature
is FUNCTIONAL end-to-end (browse + assign + display + slices + playback). (Slot numbering is 1-based
in UI, so "129" on screen = index 128.)

TWO polish items found:
1. "L" on selected 128+ slots: the browser render reads the slot LOAD-STATUS from STATE@(8) and,
   when "loading", uses format "%d%sLOAD..." (0x400b7267) -> shows an L. STATE-B holds RUNTIME state
   (load status/refcount/handle @8/@20/@24/@36) that is NOT maintained for 128+ yet -- the sample
   load/status path is still 128-capped (CLASS B fns e.g. 0x400939a4 load-request, 0x4008b906 load).
   settings-B (name/slices, from CF) is fine; only the runtime STATE-B flag is stale -> cosmetic
   LOADING indicator on the SELECTED item. FIX = migrate the load-status/STATE-maintenance path for
   128+ (next wave; makes STATE-B first-class, not just boot-filled).
2. Tempo showed 106 vs expected 121: almost certainly from the project.work RESTORE (we copied
   altre-galassie_2's project.work, which was saved at 106). NOT a firmware effect (migrations/boot-
   fill don't touch project tempo). Verify: set tempo 121 + SAVE; if it reloads as 121 -> confirmed
   (just re-set it). If it reverts to 106 on reload -> real bug, investigate.

NEXT WAVES:
- Wave 3: migrate the load-status / STATE-maintenance functions so STATE-B is runtime-maintained for
  128+ (fixes the "L"; makes 128+ fully first-class for status/refcount/streaming).
- Wave 4: the SIDECAR loader -- load real 128-255 slot data from a parallel project file (replaces
  the boot-fill placeholder = copies of 0-127). This is the actual feature the user wants.
- Remaining accessor census still un-migrated (the other ~17 functions touching settings/state) --
  migrate as needed behind the OOB gate for full 0-255 consistency (save/serialize stays 128 unless
  the sidecar handles 128-255 persistence).


### WAVE 3+4 BUILT + EMU-VERIFIED (packaged OT_dual256_wave34)  [2026-08-13]
Wave 3: migrated load-request 0x40093984 (STATE@8 load-status) so selecting a 128+ slot maintains
STATE-B -> should clear the stale "LOAD"/"L".
Wave 4 SIDECAR: assembler-generated save/load routines (708B @0x400d6600) persist SETTINGS-B
[0x47701a00,0x47723e00) (140KB) to <projectdir>/project.256 using the verified CF I/O layer
(open 0x40016864, read 0x40016564, write 0x400166b8, close 0x4001677c; dir 0x40025230(0,0);
sprintf 0x40013a08; buf 0x460a8f60/0x10000; modes "w"0x400b328b/"r"0x400b3289). Hooks: save-complete
0x4008ff44, load-complete 0x4009021a (register-safe; replicate displaced bytes). Load ZEROS all 4
B-tables first (clean project switch) then reads SETTINGS-B if present; missing file skips gracefully.
Boot-init now ZERO-only (placeholder copy-fill removed; sidecar owns 128-255).
Emu proof: sidecar save/load call-sequence+args, missing-file skip, reg preservation (d2/a3/d0);
boot zero + reg safety; helpers 170/170; OOB-gate clean (8 fns); all diffs in expected regions.
Expected on HW: 128-255 start EMPTY (---); assign sample to 128 -> SAVE (writes project.256) ->
reload -> 128 PERSISTS. Selected 128+ no longer stuck "LOAD". NOTE: the wave2 ephemeral slot-128
assignment is GONE (never persisted); re-assign + save to test the sidecar.


### ★ CRITICAL: persistence needs the ASSIGN-WRITE + SERIALIZER layers, not just the sidecar  [2026-08-13]
Wave-4 HW: project.256 IS written (140288 B = 128*0x448, sidecar save/load mechanically work) BUT it
is 100% ZERO -> SETTINGS-B was all-zero at save time. Two consequences that reframe the whole thing:
1. The ASSIGN/copy-sample-to-slot path does NOT write SETTINGS-B[0] (0x47701a00) for idx128. The
   wave2 "assigned sample plays with slices" was the boot COPY-FILL PLACEHOLDER (a copy of slot 0)
   being displayed/played -- an ILLUSION. The assign never populated the B-table. => must find +
   migrate the assign/sample-load WRITE path so idx>=128 writes SETTINGS-B (currently un-migrated ->
   writes to SRAM-A OOB or NULL, leaving B zero).
2. "reload points to the first slot": the TRACK->slot reference (which static slot a track plays) is
   stored in the bank/project and the serializer CAPS slot refs at 128 -> a track set to 128 reverts
   to 0 on save/reload. This is the on-disk FORMAT cap (the "file-format change" flagged at project
   start). The sidecar persists SETTINGS-B (slot data) but NOT the bank's track->slot references.
Also: the boot COPY-FILL is unreliable (copies SETTINGS-A which is zero/garbage at the 0x4001fa64
detour, before/around the SRAM clear) -- it produced zero here, "drumz" in wave2 (SRAM retention).

=> The persistence stack has THREE layers; only the sidecar (settings-B I/O) is done:
   (a) ASSIGN-WRITE: migrate the assign/sample-assign path so idx>=128 writes SETTINGS-B.  [TODO]
   (b) SIDECAR: persist SETTINGS-B to project.256.  [DONE, mechanically verified]
   (c) TRACK-REF SERIALIZATION: bank/project stores track->static-slot; serializer caps at 128 ->
       must extend (or sidecar the bank refs) so a track referencing 128-255 survives save/reload. [TODO]
FOUNDATION REMAINS SOLID: browse/display 0-255, DDR/boot/memory, redirect helpers, OOB gate, sidecar
I/O -- all proven. The remaining work is (a) assign-write and (c) the on-disk track-ref cap.


### PERSISTENCE INVESTIGATION: copy/paste writer still elusive  [2026-08-14]
Feature WORKS for browse/display/playback of 0-255 (wave2). Persistence of a copy/pasted 128+ slot
is blocked: project.256 (sidecar file, 140288 B) saves ALL-ZERO -> SETTINGS-B is zero at save time
-> the slot COPY/PASTE (user: FUNC+COPY slot 57 -> FUNC+PASTE slot 129) does NOT write SETTINGS-B[0]
for idx>=128. The writer/accessor it uses is un-migrated (clamps idx>=128 -> NULL, or writes SRAM-A
OOB). Sidecar save/load I/O is mechanically verified; bank stores track->slot as a full byte (no
format change needed, per agent). project.256 mtimes run ~5h behind wall clock (OT RTC offset).

RULED OUT as the copy/paste writer (migrated, project.256 still zero):
- 0x40024f00 SWAP (two-slot exchange, clipboard bufs 0x460beca8/7c are swap-local; NOT copy/paste)
- 0x40022614 rename / 0x40021d94 orchestrator (pool-assign path, reverted)
- 0x40086800 [/SAMPLE] parser (project-load filename writer)
- 0x40024514 = "SAVE SAMPLE SETTINGS" (.ot writer), 0x4006a2f4 = display helper -- both not it
No "COPY SLOT"/"PASTE SLOT" strings exist (copy/paste strings are PART/LFO/PAGE only). Browser action
handlers (0x40078b1a etc.) call 0x40021d94 + 0x4006a2f4 (select/display), not a slot-struct writer.

NEXT: (waiting on user for the exact copy/paste SCREEN + whether paste shows a message + whether slot
129 VISUALLY shows the 57 sample after paste). If visually-works-but-project.256-zero => paste writes
SETTINGS-B but sidecar/save mismatch; if visually-empty => wrong writer. Backup plan = HARDWARE TRACE:
hook memcpy 0x40020898, log (caller_PC,dst,src) for slot-region copies to a DDR ring buffer, persist
via a debug file, read back to identify the copy/paste function definitively (the COPY of slot 57 is
a valid <128 read that always fires memcpy, revealing the handler even if PASTE is clamped/no-op).

### WAVE 6 — ROOT CAUSE of non-persistence: STATIC slots use POINTER-WALKS, not base-adds  [2026-08-14]
Three independent HW traces (memcpy hook, settings base-add logger, full accessor-log) ALL returned
count=0 for idx>=128 during COPY 57 -> PASTE 129 -> SAVE. Conclusion + disasm proof:
- STATIC slot sample assignment lives in the SETTINGS table (base 0x100d5b30, stride 0x448, filename
  at slot offset 0). Proven by disassembling the STATIC serializer at 0x40089420.
- Serializer walks the table by POINTER: `lea 0x100d5c59,%a3` (=SET+0x129) then `lea %a3@(0x448),%a3`
  each iter; reads PATH from a3-0x129 (=SET[idx]+0). Counter d4, cap `cmpil #137,%d4` (FLEX) then
  STATIC loop d4=1.. capped at 128. So base-add/memcpy redirects (all my Wave1-5 work) NEVER touch the
  walk -> invisible to those traces, and the serializer emits only SLOT=001..128.
- SET-A is EXACTLY 128 slots [0x100d5b30, 0x100f7f30); slot 129 would land at 0x100f8378 (SRAM overlap).
- project.work already writes FLEX SLOT=129..136 (3-digit slots are format-OK). STATIC caps at 128.
- Format-string refs: [SAMPLE] 0x400b85de; TYPE=STATIC 0x400b868f; SLOT= 0x400b85f5; PATH= 0x400b8601.
  FLEX serializer ~0x4008920c; STATIC serializer ~0x40089420 (walk-base 0x100d5c59 @0x400893f0, UNIQUE).
  Parser/loader ~0x4008f000-0x40091000 (refs lea/move #0x100d5b30 @0x4008fb0a,0x40090854,0x4008f8c8).
  Serializer I/O regs: a4=0x40013db0(strlen), a5=0x400166b8(IO_WRITE), fp=0x40013a08(sprintf),
  d5=0x40020554 d6=0x400204a8 d7=0x400204cc (path-string helpers), d3=stream handle, a2=sprintf buf.
- CRASH: build_dumpA dumped 140KB SRAM from 0x100f7f30 via IO_WRITE -> that region is NOT contiguous
  settings (live globals + gaps) -> hung audio + "syncing project". DO NOT bulk-read SRAM windows.
- altre-galassie verified INTACT after the crash (project.work 15034 B, valid; crash was post-work,
  during the sidecar project.256 dump). Deleted the all-zero partial project.256.
PLAN (user-approved): EMULATE serializer+parser round-trip of a 256-slot project in Unicorn, verify
byte-identical, THEN one prepared flash. Restore build ready: OCTATRACK_W6.bin (DUAL256W6) = proven
256 browse/play + safe B-dump sidecar.

### WAVE 6b — SERIALIZER 256-extension PROVEN IN EMULATION (no flash)  [2026-08-14]
tools/emu_serializer.py runs the STATIC [SAMPLE] serializer loop in Unicorn (enter 0x400893ee, exit
0x40089612; only IO_WRITE 0x400166b8 hooked to capture text; sprintf/strlen/path-helpers run native).
- STOCK: populated A slots 0,1,56,127 -> emits SLOT=001,002,057,128 (empty slots skipped via strlen==0
  guard at loop head; display N = storage SET[N-1]). Reproduces real project.work. VERIFIED.
- PATCH(256): at loop tail 0x40089608 replace `cmpi.l #129,d4`(0c84 00000081)+`bnew 0x40089420`(6600
  fe10) [10 bytes] with `jmp CAVE`(4ef9+addr)+2 nops. CAVE routine:
      cmpi.l #129,%d4 ; bne 1f ; lea SET_B+0x129,%a3 ; 1: cmpi.l #257,%d4 ; beq 2f ;
      jmp 0x40089420 ; 2: jmp 0x40089612
  Result: SLOT=128->A[127], SLOT=129->SET_B[0], SLOT=256->SET_B[127]. Boundary exact. VERIFIED.
  (SET_B = 0x47701a00, same as build_dual256 SETTINGS-B.)
NEXT: map the PARSER (subagent) and mirror-emulate the round-trip (serialize 256 -> parse -> compare
SET-A/SET-B byte-identical) before authoring the combined flash.

### WAVE 6c — PARSER mapped + PERSIST256 build EMU-PROVEN (no flash yet)  [2026-08-14]
PARSER (subagent map): char/line state machine, entry 0x400866c4, end 0x40088284. STATIC dest addr =
base-add `movew #1096,d0; mulsl d1,d0; addil #0x100d5b30,d0` @0x400869c4-cc -> stored 0x460fab50; PATH
written at slot_base+0. Working build ALREADY migrates 0x400869ce->h_set_d0 (B for idx>=128) and raised
the addr-bound 0x400869bc to #255. Slot index from SLOT= line (atoi-1). ONLY remaining gate: cap
0x40086922 `movel #129,d1` (STATIC) / +7 (FLEX). Globals: 0x400d166c TYPE(0=STATIC), 0x400d1668 idx,
0x460fab50 slot ptr. Callers 0x4008ffdc/0x400900cc/0x400901aa (jsr 0x400866c4, args stream,flag).
PERSIST256 build (tools/build_persist256.py) = working image + (A) serializer 256-ext (cave@0x400d6900,
tail 0x40089608 -> jmp cave; A->B reload a3=SET_B+0x129 at d4==129, cap 257) + (B) parser cap
0x40086922 #129->#256 + boot COPYFILL_SET=False (SETTINGS-B zeroed -> no phantom high slots; STATE/
stride4-B still filled). EMU-VERIFIED on the FINAL image out/mainos_persist256.bin:
 - serializer: SLOT=001..128 from SET-A, 129..256 from SET-B; empty B slots skipped (no phantoms).
 - parser: cap PASS 1..256 / REJECT 257; dest SLOT 1..128->SET-A[0..127], 129..256->SET-B[0..127], 257->NULL.
 - emu_check ALL GREEN. Sidecar dumps SET-B (safe DDR) to project.256; NO SRAM bulk-dump (avoids the
   build_dumpA crash). Non-destructive for projects with no high slots (serializer skips empty B).
OPEN QUESTION (HW-only, not a corruption risk): does the interactive PASTE write SET-B[idx-1]? If yes,
save -> STATIC SLOT=129 block -> full persist. If no (paste walks A base), SLOT=129 absent -> must find
the paste's walk base next (infra now ready). Package: OCTATRACK_P256_1.bin (DUAL256P1).

### WAVE 6d — ROOT CAUSE of empty high slots: reset-slot 0x40099148 UN-MIGRATED  [2026-08-14]
Full-parser Unicorn trace (tools/emu_parser_full.py) proved the parser DOES write PATH to SET-B[0]
for STATIC SLOT=129 (idx128) in the REAL pass -- but ONLY because the harness skipped reset-slot
0x40099148 (jsr'd @0x40086940 before the settings write; faults in emu on hardware). reset-slot is the
slot INITIALISER and had its OWN un-migrated base-adds (STATE 0x46c90a78 @0x40099170, SETTINGS
0x100d5b30 @0x400991dc, stride4 @0x40099352/5c) + its own #128 STATIC clamps (0x4009915c, 0x400991c4).
For idx>=128 it inited the OOB SET-A[128]/STATE-A[128] struct while the parser wrote PATH to SET-B ->
slot SPLIT across A and B -> shows EMPTY. FIX: added resetslot_0x40099148 to CORE (sites h_st_a0/
h_set_a2/h_s42_a0/h_s41_a0; clamps raised). Emu-verified reset-slot settings dest now: idx128->SET-B[0]
.. idx255->SET-B[127], idx256 bails. Build P256_2 (DUAL256P2). Also learned: the OT LOAD reads BOTH
project.work AND project.strd (both text, %s/project.work @0x400b5cd0); a text edit must be in .strd too.

### WAVE 6e — LOAD path completed offline (reset-slot + sample-loader), audit of remaining fns  [2026-08-14]
Added to CORE: resetslot_0x40099148 (slot initialiser) + sampleloader_0x4008445c ("Couldn't load
STATIC[%d]" -- loads the sample file into the slot). Both had un-migrated STATIC settings base-adds ->
idx>=128 hit OOB SET-A. Now 38 sites / 21 clamps, OOB-gate green, emu_check green. Build: P256_3
(DUAL256P3). Reset-slot callers = the slot-init sites: 0x40086940(parser), 0x40084b66/c34(sample-
loader), 0x400255a0 (fn 0x40025288 -- FLEX-range slot mgr, NOT yet migrated). Full audit: 51 un-migrated
slot base-add sites remain across ~25 functions (most are other features: 0x40021d94/0x40022614 assign,
0x40027716, 0x40029004, 0x4004xxxx, 0x4006-0x40073 STATE readers, 0x40098xxx, etc.). NOT migrating them
blindly (wave-3 risk). PASTE still unidentified as a single fn; the ACC trace showed 0 settings base-add
access for idx>=128 during paste -> paste reaches its dest via a pointer it already holds (cursor slot
ptr from a getter) or index 129 (1-based) which bails reset-slot's #128 clamp. Needs HW to test P256_3:
if load of a project with STATIC SLOT=129 now populates slot 129, the LOAD path is DONE; then chase paste.

### P30 PACKAGED — full fix set, all gates green (ready to flash)  [2026-08-20]
Rebuilt `build_dual256.py` -> `build_persist256.py` -> out/mainos_persist256.bin (1,112,560 B), then
packaged: `EFT_EMIT_CONTAINER=out/elek_p30.bin elektron-firmware-tool -i out/OT_stock.syx -c 3
out/mainos_persist256.bin -V DUAL256P30 -o out/OT_p30.syx` + `make_bin.py out/elek_p30.bin
-o out/OCTATRACK_P256_30.bin` (446,484 B, sha256 c844aec8…c69b7b17, checksum 0x05a3e770).
Build: 70 migrated sites / 44 clamps; OOB-gate OK; serializer-ext 34 B @0x400d6900 (A->B @ d4=129,
cap 257); parser cap 0x40086922 #129->#256.
GATES (all GREEN on the final image): emu_check (DSP regs/pool intact) · verify_dual256 (200/200) ·
audit_dual256 (CLEAN, 3 reviewed-safe whitelist entries) · emu_serializer (SLOT=001..256, B slots
emitted) · emu_header_name (idx128 STATIC -> SET-B[0]) · emu_parser_full (REAL pass writes
'../yok-b.aif' -> SET-B[0]@0; the DRY pass legitimately writes nothing) · emu_sidecar_load (skip-empty:
populated restores / empty survives / missing untouched) · emu_aed_state (6 resolvers -> STATE-B) ·
emu_aed_write (load-sample -> SET-B+STATE-B) · emu_allocator (A full + B[10] free -> slot 138).
Contents beyond P29 (HW-confirmed slot-129 playback): AED tab-body STATE resolvers + wavestream,
AED load-sample WRITE path, skip-empty sidecar_load, latent-OOB fix (assign type-1 0x40023f1c),
extended allocator + boot STATE-B free-init.
CAVEAT: the boot STATE-B free-init (status@8=1 on 128 slots) is NEW boot behavior, emulator-only —
for a minimal-risk flash set MIGRATE_ALLOC=False + STATEB_FREEINIT=False and rebuild.
NOT COPIED: no CF mounted at build time. HW test plan: RELOAD -> slot 129 -> AED (waveform/slices?)
+ track header NAME; also read altre-galassie_2 project.work for SLOT=129 blocks and project.256 SET-B[0].

### WAVE 14 — the OFF-BY-ONE clamp class; track->slot mapped; P31 packaged  [2026-08-20]
HW result on P30 (user): AED FILE-menu load into slot 129 WORKS (waveform + slices + playable slices).
Broken: slot-list selection doesn't load; track-header name blank; SAVE+RELOAD reverts the track's slot.

**TRACK->SLOT REFERENCE FULLY MAPPED** (was NOTES item (c), open since 2026-08-13):
  addr = bank_base + pattern*0x18b2 + track*5 + type + 0x8F04A     (one byte, 0-based slot)
  type = bank_base + pattern*0x18b2 + track     + 0x8EDA2          (0 = STATIC)
  bank_base = *0x46c82456. Disassembled from the sequencer resolver FUN_40005030 (0x40005048-0x4000507e).
  Validated against real files: track 4 (UI track 5) slot byte 128 == UI slot 129, neighbours 49..57.
  Both writers ALSO mirror the value into an SRAM shadow table at 0x100A5198 (type shadow 0x100a4ef0) --
  a copy NOT previously in NOTES. Only 2 literal writers exist: 0x40027ebe, 0x400795bc; neither clamps.

**SAVE WORKS, RELOAD IS THE BUG** (hard evidence from the CF, fresh mount):
  bank01.strd (saved)      track4 = 128   <- SAVE writes the high slot correctly
  bank01.work (post-reload) track4 =   0   <- RELOAD substitutes 0 (= UI slot 1)
  Diff strd vs work = EXACTLY 2 bytes: that field + the file's last byte (checksum). A targeted
  single-byte write, not a bulk clear. Control test: a LOW slot (11) survives the same SAVE+RELOAD,
  so this is a genuine high-slot bug, not Octatrack part-save semantics.
  Author of the 0 NOT yet identified: writer A (0x40027ebe) is gated on command==26 in 0x460c80f0 and
  NO code path in the image emits 26 (emitters found: 5,7,9,11,12,13,14,15,16,17,21,22,23,24); the load
  path that feeds writer B (0x40083c60: mvzb slot -> set_selection 0x4006de34 -> ui_apply) preserves 128
  cleanly. So a third, pointer-based route remains to be found. project.work/.256 persistence is FINE
  (TYPE=STATIC SLOT=129 PATH=yok-vox.aif present; project.256 carries the name).
  CAUTION: macOS FAT caching served STALE bank contents while the OT wrote the card (dd read 0 bytes from
  a 636 KB file) and produced one wrong intermediate conclusion. ALWAYS unmount+remount before reading
  files the OT has just written.

**THE OFF-BY-ONE CLASS (the real find).** Every site the earlier census filed as "SAFE/leave (clamp
closed)" is NOT closed for idx=128: the guard is `cmpi.l #128,dN` + **bhi**, which bails only on
idx > 128, so idx == 128 falls through into the stock add -> SETTINGS-A[128]/STATE-A[128], one stride
past table A. Stock-safe (slot 128 unreachable there), reachable here. idx=128 is UI slot 129 -- exactly
the slot under test, and the ONLY value that slips through (129..255 do bail).
  => Testable prediction for the next HW session: slot 130 should behave BETTER than 129 in these
     features. If 130 fails identically, the cause is elsewhere and we learn that unambiguously.
Migrated in wave 14 (MIGRATE_OFFBYONE toggle, 9 functions / 10 sites / 9 clamps): slotclear 0x40025288,
unresolved 0x400276fa + 0x40027772, cfmount 0x40028fec, plockdesc 0x4003193c, trigdisp 0x40044050,
dspcount 0x40044d88 + 0x4004fe00, renamed 0x4006da16. Chose MIGRATE over closing the guards: two of them
are DSP per-voice readers on the audio path for the playing high slot, so NULLing them risks re-introducing
the P29 silence; migrating keeps idx<128 byte-identical and gives idx>=128 the real B record.
DELIBERATELY HELD: 0x4008b904 (CLASS-B bank serializer -- it writes a file and the save path is proven
working on HW, needs its own analysis) and 0x4008e638 (guard is `bls`, polarity not the bail idiom).

**TOOLING (both blind spots were causing wrong conclusions):**
- audit_dual256.py CHECK 1 counted `cmpi #128` as closed regardless of branch type -> that is why the
  audit reported CLEAN. Now distinguishes bhi (>) from bhs/bcc (>=) and reports the off-by-one as a
  first-class finding; `bls` guards are reported as REVIEW instead of assumed. The old "0 un-migrated
  adds safely closed" count is now literally 0 -- every one of them was off-by-one.
- xref.py only scanned absolute jsr/jmp + bsr.w, so PC-relative `jsr %pc@(d16)` / `bra.w` / short
  bra/bsr callers were invisible -> the 0x40027e4c dispatcher looked uncalled when it has 2 callers.
  Any earlier "no callers" conclusion in this project is suspect. Fixed + verified.

BUILD: 80 sites / 53 clamps (was 70/44). OOB-gate OK. ALL GATES GREEN on the final image: emu_check,
verify_dual256 (200/200), audit (only the 2 deliberate holds), emu_serializer, emu_header_name,
emu_parser_full, emu_sidecar_load, emu_aed_state, emu_aed_write, emu_allocator, emu_seq_slot, emu_seq_plock.
PACKAGE: out/OCTATRACK_P256_31.bin (DUAL256P31, 446,452 B, sha256 4de0b03c..., checksum 0x14fab470).

### WAVE 15 + P32 HW RESULTS — crash fixed, high slots play; spurious load error remains  [2026-08-20]
HW on P32 (DUAL256P32, sha256 ef7c406b...):
- **Slot 130 exception GONE.** Wave 15 (`loadhandle_0x4008e608`: clamp 0x4008e620 #128->#256, add
  0x4008e63a -> h_st_a3) was the fix. The site was `cmpi #128 + bls` -> `subal a3,a3` (NULL) ->
  `movel %a3@(36)` (the file handle) -> bus error for idx>=129. `bls` is why slot 129 survived and 130 died.
- **ALL high slots now show the waveform and play** (129 and beyond). Name shows on the track header.
- REMAINING: slices never load, and slots >=130 print "SAMPLE LOAD ERRORS!" after selecting the sample
  even though the load visibly succeeds (waveform + playback fine) -> a spurious negative result code.
- `STATEB_FREEINIT = False` CONFIRMED the @8 hypothesis: @8==1 means FREE (allocator tests it at
  0x400240a2) and the AED's "has content?" predicate (0x4006db32) is true only when @8==0. Boot-marking
  all 128 B slots free made every high slot read as empty -> no waveform. THIS IS A DIAGNOSTIC, NOT THE
  FIX: the proper repair is to clear @8 on load so the extended allocator keeps working. TODO.
- "SAMPLE LOAD ERRORS!" = 0x400b37f0, emitted at 0x40022b60 / 0x40022bee. Both live in
  `finish_load(result)` 0x40022b70 -- an ASYNC COMPLETION CALLBACK (its address is stored into a request
  struct, e.g. 0x460e735a in the slot-list path at 0x40079372) that only REPORTS a negative result; the
  failure happens upstream. Note 0x40022bd0: `cmpi #128,d2` treats 128 as a SENTINEL (jmp 0x4007927c) --
  another stock "128 can never be a real slot" assumption, not yet assessed.
- Ruled out as the cause (verified ON THE BUILT IMAGE): no #128 slot guard remains anywhere except the
  held-back serializer 0x4008b8ee; no cmpa.l #128/#129 guards remain; 0x400802e2 is a FALSE POSITIVE of
  the off-by-one scan (`addi #-128,d2` + `cmpi #128` is a 128-block copy loop, not a slot clamp); the
  STATIC loader guards 0x40084c56/0x40084c9c are ALREADY migrated (clamps #256, adds -> helpers).

**PROCESS FIX (this cost three wrong conclusions in one session):** `tools/otdis.py` defaulted to
out/stock_mainos.bin, so reasoning about the patched build silently read stock -- where a guard still
shows #128 that the build has already raised to #256. otdis now DEFAULTS TO out/mainos_persist256.bin,
honours OTDIS_IMG=<path>, and prints `[otdis] disassembling <file>` once per image. When a finding
depends on whether something is patched, verify on the BUILT image and say which image was read.
Related earlier fixes: xref.py was blind to PC-relative callers; audit_dual256.py counted `cmpi #128`
as closed regardless of branch. All three were producing confident wrong answers.

NEXT: the 129-vs-130 difference may NOT be an index boundary at all -- slot 129 was already populated
from an earlier save while 130+ are FRESH loads. Test: load a fresh sample into 129 on P32; if it also
errors, the split is "fresh load into any high slot", not idx>=129.

## P36 — the P34/P35 brick: hook padding off-by-one (NOT the code cave) [2026-08-20]

**Symptom:** P34 threw an exception on project load and hung on empty boot; P35 crashed with
`VEC:04  ADDR:0x4009937E` (illegal instruction) on the device screen.

**Root cause, byte-exact.** The slice probe hooks `0x40099374`, whose stock prologue is an 8-byte hole
`4fefffd8 48d73cfc`. The builder wrote a 6-byte `jmp` plus `pad_nops=2` — and that field means *two
NOPs*, i.e. 4 bytes. 6+4=10 into an 8-byte hole:

```
P32  0x40099374: 4f ef ff d8  48 d7 3c fc  28 6f 00 2c     moveal %sp@(44),%a4
P35  0x40099374: 4e f9 40 0d 6a 58  4e 71 4e 71  00 2c     <- 28 6f clobbered
```

`002c` at `0x4009937e` is not an instruction → VEC:04, exactly the address on the photo. The same
overrun was present in P34, so **both bricks were this one bug** — my earlier attribution of P34 to the
relocated cave `0x400d6c00` was wrong.

**Why three gates all said GREEN.**
- `emu_probes.py` stopped *at* the landing address without executing it, so it never reached the
  corrupted instruction. Hardened: it now runs 8 instructions past the landing. Verified against the
  reconstructed bricking image — it FAILS it (UC_ERR_EXCEPTION on probe S) and passes the corrected one.
  Also: it took `--img` only, and silently ignored a bare positional path, so a gate run could report on
  a *different* image than intended. It now accepts a positional arg and REFUSES unrecognized ones.
- `emu_check.py` checks DSP regs/pool/helpers — never the hook sites.

**Structural fixes in `build_diag_loaderr3.py`** (so this cannot recur by inattention):
1. The pad count is *derived*: `hole = len(expected_bytes)//2`, `(hole-6)//2` nops, asserted
   `hole >= 6 and hole % 2 == 0`. Nothing is hand-counted. It now prints `(hole 8 B, 1 nop)`.
2. **Hard byte invariant**: the build refuses to emit if a single byte outside the hook holes and the
   cave differs from the base image. This alone would have stopped P34 and P35.
3. `VALIDATED_CAVES` — only extents that have carried working code on hardware.

**P36** = P32 + the two probes, `DUAL256P36`, sha256 `56a0120c…`. Repackaged from
`out/mainos_diag_loaderr3.bin` and confirmed byte-identical to the earlier P36 artifact. Byte diff vs
base: exactly `0x40022b50..0x40022b56` (6 B), `0x40099374..0x4009937c` (8 B), cave
`0x400d6a00..0x400d6ab0`. Copied to CF and hash-verified after a `diskutil unmount`+`mount` cycle.

**Lesson (same class as otdis-reads-stock, xref-blind-to-pc-relative, audit-counts-#128-as-closed):**
every one of these gates returned a confident GREEN while measuring the wrong thing. A gate that does
not execute the patched bytes is not a gate.

## P36 HW MEASUREMENT — the load error is code -2 on a dispatched callback [2026-08-20]

Read from `altre-galassie/project.256` @0x21000 after the P36 run (CF remounted first):

```
magic=0x10ade111  cntB=1  cntS=16
B[0] result=0xfffffffe (-2)   PC=0x40062462
S[0..15] slot=128..135, arg1=1, twice
```

**Probe B (the live emitter) fired once with result -2.** `PC=0x40062462` is the return address of
`jsr %a0@` at `0x40062460`, i.e. the generic message-pump case:

```
40062454: moveal %a2@(2),%a0     ; callback
4006245c: movel  %a2@(6),%sp@-   ; its argument = the -2
40062460: jsr    %a0@
40062462: addql  #4,%sp          ; <- captured PC
```

So the popup rides a queued message whose `+2 == 0x40022b0c` and `+6 == -2`. The callback itself
(`0x40022b0c`) tests `sp@(4)` at `0x40022b50` and, if negative, calls `0x40080844` and draws
`"SAMPLE LOAD ERRORS!"` (`0x400b37f0`).

**Probe A never fired**, which rules out a whole branch: `FUN_40028fec` installs `finish_load
0x40022b70` for **type==0 (STATIC)** and `0x40022b0c` only for **type==1**. The STATIC loader is not
the path. `0x40022b0c` is also installed unconditionally by `FUN_40022610` — the assign/paste writer
migrated in Wave 5 — which is what the AED "load sample into slot" actually runs.

**Where static analysis stops.** The literal `0x40022b0c` is stored at exactly two places in the whole
image, both at *record+18* (`0x460bd8fe` by `FUN_40022610`, `0x460d1010` by `FUN_40028fec`), and there
is no PC-relative reference either. Neither record has a callback at `+2`, and neither `+6` can hold -2
(each has a single writer, `clrl` and `moveq #1`). So the dispatched message is a THIRD object,
assembled at runtime by generic code that copies the callback out of `record+18`. Enumerating all 44
records posted to queue `0x460d17ce` found no candidate. This cannot be resolved by scanning.

**Probe S was contaminated — my filter was wrong.** `slot >= 128` also matches the 8 RECORDER entries
of the FLEX table (that table is bounded by `#135` everywhere in the code). The 16-entry ring filled
with 128..135 twice during project load, before the user ever touched a slot. The captured range
stopping exactly at 135 is the proof. **No slice data was obtained.** v3 filters `slot >= 136`, so the
HW test must use a STATIC slot **>= 137**, not 130.

### Two candidate producers of -2 (the image's only direct `moveq #-2 ; rts` returns)
- `FUN_400148d4` — handle validation: `-2` if the pointer is NULL **or** `(*handle)-1 >u 510`
  (valid ids 1..511). Generic I/O; reached via `0x46c8241e` dispatch.
- `FUN_4008fa68` — path classification (compares against `"../"`, `0x400b36a4`): `-2` if the path
  pointer is NULL, `0` if the string is empty. **Nothing in the image references it** — neither
  absolute nor PC-relative — so it is called through a function-pointer table or is dead.

Note the loop just above it (`0x4008fa0c..0x4008fa5a`) walks SETTINGS by `0x448` from `SETTINGS-A[0]`
to `#0x100f7f30` = `SETTINGS-A[128]` — a **128-bounded** bulk path check that sets a per-slot error
byte. One of the "walk-start" sites the census parked; high slots are never visited by it.

## P37 = measuring build v3 (`DUAL256P37`, sha256 `c9bba72c…`)
`tools/build_diag_loaderr4.py`, blob 436 B at cave `0x400d7100` (768 B free), four probes:
- **B** `0x40022b50` -> `[result][caller_PC][a2]`. `%a2` at callback entry still holds the pump's
  message pointer — one long that names the poster outright. This is the measurement that cannot miss.
- **S** `0x40099374` -> `[slot][arg1][caller_PC]`, **slot >= 136**.
- **N1** `0x400148d4` -> `[handle][caller_PC]`, only on the paths that return -2.
- **N2** `0x4008fa68` -> `[caller_PC]`, only when the path pointer is NULL.

Byte diff vs base: `0x400148d4`(8) `0x40022b50`(6) `0x4008fa68`(8) `0x40099374`(8) + cave(436). Nothing else.

**Gate hardening (`tools/emu_probes.py`):** it now (1) refuses to run without an explicit image — the
old implicit default meant a bare positional path was silently ignored and the WRONG image got gated;
(2) asserts what each probe **wrote** into the PROBE block, not just where it landed. Verified the
assertions bite: gating the P36 image reports the missing N1/N2 records as FAIL. 13/13 green on P37.

## P37 HW MEASUREMENT — `-2` means EMPTY PATH; slices reach the high slot [2026-08-20]

```
magic=0x10ade111  cntB=1  cntS=4  cntN1=0  cntN2=0
B[0]  result=-2  PC=0x40062462  a2=0x460364e4
S[0..3] slot=139 arg1=0 PC=0x4009968e     (four calls)
```

### 1. The error code -2 = "the sample path string is empty"
`a2=0x460364e4` is entry 0 of a **32-entry x 26-byte request pool** owned by the project/bank loader
(`lea 0x460364e4,%a0` at 0x400840b4 / 0x40084138 / 0x400841cc / 0x40085ace; the allocator scans
entry+22 for a free marker, `moveq #32` bound at 0x40085afc). So the failing job was posted by the
**loader**, not by the AED assign.

Its four `-2` exits (0x4008498c / 0x400849de / 0x40084a80 / 0x40084b20) are all branch targets, and the
two guards that reach them are identical:

```
movel %fp@(-470),%d0 ; addql #1,%d0 ; beq  -> -2      ; pointer == -1
movel %d0,%sp@-      ; jsr 0x40013db0 ; tstl %d0 ; ble -> -2
```

`0x40013db0` is **strlen**, not a file open:
`moveal sp@(4),a0 ; clrl d0 ; 1: addql #1,d0ptr ; tstb a0@(0,d0:l) ; bne 1b ; rts`.
So the second guard is **strlen(path) == 0 -> -2**. The same idiom guards the STATIC assign path at
`0x400290a4` inside `FUN_40028fec`. **-2 is an EMPTY PATH, not a missing/unreadable file.**

That fits the symptom exactly: the sample the user picked loads fine (waveform + audio), and a
*separate* request carrying an empty path fails alongside it.

**Leading hypothesis — this is the STATEB_FREEINIT debt.** With `STATEB_FREEINIT=False`, STATE-B is
never initialised, so `@8` reads 0 for every high slot — and `@8==0` means "has content" (1 == FREE,
per the allocator test at 0x400240a2 and the AED predicate 0x4006db32). Every empty high slot therefore
advertises content with an empty path; the loader enumerates it and strlen fails -> -2. It also
explains why turning FREEINIT off is what made the waveform appear at all. Proper fix stays the one
already written down: clear `@8` when a sample is loaded into a high slot, then re-enable FREEINIT.
NEXT: find who clears STATE@8 on a successful low-slot load and check whether that write is migrated —
P31 had FREEINIT=True and high slots read as empty, which says that write is NOT reaching STATE-B.

### 2. N1/N2 both zero — clean negative
Neither `FUN_400148d4` (handle validate) nor `FUN_4008fa68` (path classify) fired. Both leads dead;
the -2 is the loader's own, as above.

### 3. Slices: the function IS reached for the high STATIC slot
`FUN_40099374(type, slot, flag)` — **my probe's field labels were swapped**: `sp@(4)` is the machine
TYPE and `sp@(8)` is the slot (confirmed at 0x4009937c: `moveal sp@(44),a4` = type, `movel sp@(48),d7`
= slot, after the 40-byte frame). So P37 recorded **type=0 (STATIC), slot=139**, four times, all from
the wrapper at 0x40099680 (which passes flag=0; its twin 0x40099668 passes 1).

This retroactively PROVES the P36 contamination reading: those `slot=128..135, arg1=1` records were
**type=1 (FLEX)**, i.e. the 8 recorders — exactly as diagnosed.

Both per-slot resolutions inside the function are already migrated and clamped at #255
(`jsr 0x400d75c0` for STATE at 0x4009939a, `jsr 0x400d74c0` for SETTINGS at 0x40099410), and the
STATE@8 content test at 0x400993d8 is on the migrated pointer. So the missing slices are **not** an
addressing miss in this function — the failure is downstream (slice DATA / the shared high-slot scratch
`SLICE_SCRATCH 0x40aba000`, which all high slots share), or STATE@8/@20 not being populated.
Note 0x400993f2 reads `%a0@(20)` into a5 right after the @8 test — that is the slice-table pointer.

## STATE@8 semantics NAILED, and the bulk load loop is NOT the source [2026-08-20]

Helper map (from the assembled ELF, `assemble_helpers()`): `0x400d74c0 h_set_a2`, `0x400d74e0 h_set_a3`,
`0x400d75c0 h_st_a0`, `0x400d7600 h_st_a3`, `0x400d76c0 h_slice_d0`. Reading a `jsr 0x400d7xxx` without
this map is how `a3` got mistaken for a STATE pointer in one function and a SETTINGS pointer in another
— they genuinely differ per function.

**`STATE@8` is the occupancy field, confirmed on both consumers:**
- allocator `0x400240a2`: `movel %a0@(8),%d0 ; moveq #1,%d2 ; cmpl %d0,%d2 ; beq found` -> **1 == FREE**
- AED has-content `0x4006db38`: `movel %a0@(8),%d0 ; seq` -> **0 == HAS CONTENT**
- `0x400939da` writes 2 on another path, so `@8` is an enum, not a flag.

Every write to `@8` in the image that follows a STATE helper is already migrated (only three exist:
`0x40093856`, `0x400939da`, `0x40094070` — and all three SET 1 or 2, i.e. release). The write that
marks a slot LOADED (`@8 = 0`) is `0x40093df4 clrl %a3@(8)`, whose `a3` comes from `h_st_a3` at
`0x400939b6` — **migrated**. So the "clear @8 on load" half of the FREEINIT debt may already be in
place; what P31 showed (FREEINIT=True -> high slots read empty) still needs explaining before
re-enabling it. Do NOT flip STATEB_FREEINIT on that basis alone.

**The STATIC bulk load loop is exonerated.** Its body head at `0x4009087a` is
`tstb %a2@ ; beq skip` — the FIRST instruction skips a slot whose path is empty, and a second filter at
`0x40090886` skips again. Our LOADLOOP_STUB extension walks 128..255 through SET-B, so empty B slots
are skipped, not errored. Its own error path logs `"Couldn't load STATIC[%d] with '%s' (%s)"`
(`0x400b7933`) vs `"Successfully loaded STATIC[%d] with '%s'"` (`0x400b8af1`) — worth capturing later.

## P38 = measuring build v4 (`DUAL256P38`, sha256 `40930cc2…`)
`tools/build_diag_loaderr5.py`, blob 298 B at cave `0x400d7100`, three probes:
- **B** `0x40022b50` -> `[result][callerPC][a2]` (the anchor, unchanged)
- **G1** `0x40084a12`, **G2** `0x40084ab8` -> `[strptr][a2][16 bytes of the string]`. Both replace a
  `jsr 0x40013db0` (strlen): the stub records, performs the same `jsr`, then jumps past the original
  call, so `d0` and the stack are untouched. **The captured pointer names the slot**:
  SET-A -> `(p-0x100d5b30)/0x448`, SET-B -> `128 + (p-SET_B)/0x448`.

Byte diff vs base: `0x40022b50`(6) `0x40084a12`(6) `0x40084ab8`(6) + cave(298). Nothing else.

**Gate**: `emu_probes.py` now detects which hooks an image actually has and runs only those suites, so
one gate serves every diag build and old images stay re-gateable. It also classifies post-landing
faults: a DATA read/write to unmapped memory after the landing is a gate artifact (synthetic registers),
but an illegal instruction or an unmapped FETCH is a real defect and still fails — the P35 brick mode.
Added a `strlen passthrough` check asserting `d0 == 2` after the probe, i.e. the probe is transparent.
10/10 green on P38; re-gating P37 still runs B/S/N1/N2 and is green.

## P38 result + P39 = WIDE instrumentation [2026-08-21]

P38: `cntB=1 result=-2 a2=0x460364e4` again, but **cntG1=0 cntG2=0**. The strlen guards were never
reached, so the -2 comes from `0x4008498c` or `0x400849de`, not from `0x40084a80`/`0x40084b20`.
Also in that save: `SET-B[15]` = UI slot 144 = `'../AUDIO/afo-melero.aif'` — **high-slot persistence
works**; the sidecar wrote the right path. So the -2 is NOT about the slot being loaded.

**Lesson: probe SITES and DECISION POINTS, not guards.** G1/G2 covered two of four exits and returned a
pure negative for a whole flash cycle. Four exits reached by six branches, only two sharing the strlen
shape — picking two of them was a coin flip.

### P39 (`DUAL256P39`, sha256 `cca5ded3…`) — `tools/build_diag_loaderr7.py`, 650 B at cave 0x400d7100
Eight probes, chosen to answer every open question in ONE flash:

| probe | site | hole | records |
|---|---|---|---|
| B  | 0x40022b50 | 6  | `[result][callerPC][a2]` — popup emitter (anchor) |
| E1 | 0x4008498c | 10 | `[site][rec][32 raw bytes of rec]`, rec = `a2` |
| E2 | 0x400849de | 12 | same, rec = `a2` |
| E3 | 0x40084a80 | 10 | same, rec = `-470(fp)` |
| E4 | 0x40084b20 | 10 | same, rec = `-482(fp)` |
| L  | 0x400908ac | 6  | bulk load-loop outcome, slot >= 128: `[slot][result][pathptr][str16]`, + `cntLall` counts every pass |
| C  | 0x400993d8 | 6  | slice-fn decision, type==0 && slot>=128: `[type][slot][STATE@8][STATE@20]` |
| A  | 0x4006db38 | 6  | AED has-content, slot>=128: `[slot][STATE@8][type]` |

**Why C is the slice answer.** At `0x400993d8` the slice function proceeds only if `STATE@8 == 0`, or
if `@8 == 2` AND the third argument is non-zero. P37 proved the call arrives from the wrapper at
`0x40099680`, which passes **flag = 0**. So any high slot whose `@8 != 0` bails to `0x4009965e` and
draws nothing. C reads `@8` at the exact deciding instruction; A reads what the AED concludes.

Probe block is now 1008 B and spans **SET-B[123..124] -> UI slots 252 AND 253 are reserved.**

### Boot-safety review (the failure mode that cost two sysex recoveries)
- **Byte invariant**: diff vs base is exactly the eight holes (6/6/10/12/10/10/6/6) + 650 B of cave.
  Nothing else. The build refuses to emit otherwise.
- **Register safety**: disassembled the whole cave and grepped for any write outside the saved set
  `{d0-d3,a0,a1}` — none (the only match is a `cmpi` reading d7). Every value the replaced instructions
  left live is re-established AFTER the register restore (E3/E4 `d2` and `a0`, L `d2`).
- **No fallthrough**: every stub ends in `jmp`; the cave's last instruction is a `jmp`.
- **CCR discipline**: L's branch depends on the flags from `move.l %d0,%d2` and A's `seq` on the Z from
  `move.l 8(%a0),%d0`; both replays reproduce that ordering, and `addq.l #N,%sp` (An) sets no flags.
- **Width check**: `a_probe` reads global `0x46c8d19c` as a long — confirmed that is how all ~100
  references in the image read it.
- **Bounded loops**: `rawcopy` is a fixed 16/32-byte count; `rec_alloc` is capped per ring.
- **Stack**: max 24 (frame) + 12 (rec_err spill) + 8 (two nested bsr) = 44 B added, no ISR involved.
- Gates: `emu_probes` 17/17 GREEN across all 8 suites (it auto-detects installed hooks);
  `emu_check` GREEN; `verify_dual256` 200/200; `audit_dual256` output byte-identical to the base image
  (its one flagged item is the pre-existing `0x4008b904` CLASS-B serializer, held back on purpose).

## P39 threw VEC:04 at 0x4008498E -- hook holes with INTERIOR branch targets [2026-08-21]

Loading a sample into slot 144 raised `VEC:04 ADDR:0x4008498E`. That address is two bytes into the
6-byte `jmp` that probe E1 wrote at `0x4008498c`. Cause: replacing N bytes at a site silently assumes
the whole run is entered only at its FIRST address. For all four `-2` sites that is false:

```
0x40084912 / 0x4008491e / 0x40084966 / 0x4008498a  bra.b -> 0x4008498e   (the SUCCESS path,
0x400849d8 blt.b / 0x400849dc bra.b                      -> 0x400849e0    which skips the moveq #-2)
0x40084a76 bge.b / 0x40084a7a ble.b / 0x40084a7e bra.b   -> 0x40084a82
0x40084b1a ble.b / 0x40084b1e bra.b                      -> 0x40084b22
```

Eleven branches land inside holes I consumed, each one mid-`jmp`. The only safe hole at those sites is
the 2-byte `moveq` itself -- too small for a 6-byte jmp. **Those four sites are simply not hookable.**

**New permanent gate: `tools/hookcheck.py`.** `check_holes(img, [(va, n), ...])` refuses the build if
any branch (Bcc.b/.w, bra, bsr, jmp/jsr abs, jmp/jsr pc@) or any stored 4-byte pointer targets an
address strictly inside a hole -- odd addresses included, since a target mid-word is worse. It is
called from the diag build before any byte is written. Run retroactively against P39's hook set, it
prints all eleven offenders. This is the fourth tool in the family whose absence produced a confident
wrong answer (otdis-reads-stock, xref-blind-to-pc-relative, audit-counts-#128-as-closed,
emu_probes-stops-before-the-landing).

## P40 (`DUAL256P40`, sha256 `8fbda79c…`) -- `tools/build_diag_loaderr8.py`, 532 B at cave 0x400d7100
The four E probes are replaced by ONE strictly better probe:

| probe | site | hole | records |
|---|---|---|---|
| B | 0x40022b50 | 6 | `[result][callerPC][a2]` |
| **X** | **0x40013db0 (strlen)** | 6 | `[callerPC][strptr][str16]`, only when caller PC is in `[0x40084800,0x40084c00)` |
| L | 0x400908ac | 6 | `[slot][result][pathptr][str16]`, slot >= 128, + `cntLall` |
| C | 0x400993d8 | 6 | `[type][slot][STATE@8][STATE@20]`, type==0 && slot >= 128 |
| A | 0x4006db38 | 6 | `[slot][STATE@8][type]`, slot >= 128 |

X covers **all six** strlen guards in the loader function at once instead of two of four exits, and
needs no register saving on its fast path: the replaced `moveal sp@(4),a0 ; clrl d0` writes both d0 and
a0, so both are dead on entry. The gate asserts the replay still leaves `a0 = arg` and `d0 = 0`.

All five holes are 6 bytes, all verified free of interior targets. Layout (976 B, one slot):
`+0x004 cntB +0x008 cntX +0x00c cntL +0x010 cntC +0x014 cntA +0x018 cntLall`,
`+0x020 B[8]x12  +0x080 X[12]x24  +0x1a0 L[12]x28  +0x2f0 C[8]x16  +0x370 A[8]x12`.

Gates: hookcheck OK; emu_probes 17/17 across B/X/L/C/A; emu_check GREEN; audit identical to base;
byte diff = five 6-byte holes + 532 B cave; no cave write outside `{d0-d3,a0,a1}`; cave ends in `jmp`.

## P40 HW RESULTS -- three corrections and one clean answer [2026-08-21]

```
magic ok  cntB=1  cntX=5  cntL=0  cntC=5  cntA=8  cntLall=88
B[0] result=-2 PC=0x40062462 a2=0x460364e4
X[0..4] callerPC=0x400848e0  ptr=0x460bd00d  str='/universi/AUDIO/'   (all five identical)
C: type=0 slot=128 @8=1 @20=1 | type=0 slot=143 @8=2 @20=5 | slot=143 @8=0 @20=5  (x3)
A: slot=143 @8=0 type=0  (x8)
SET-B[15] = UI slot 144 = '../AUDIO/afo-melero.aif'
```

### CORRECTION 1: `-2` is NOT an empty path string
X caught every strlen call inside the loader: **five, all from `0x400848e0`** (block A's guard), all on
`a2+1 = 0x460bd00d` holding `'/universi/AUDIO/'` — length 16. **strlen never returned 0.** So the
earlier "-2 == EMPTY PATH" conclusion, drawn from reading the guard statically, is wrong. The only
other route to `0x4008498c` is the NULL-field test right after it:

```
400848e2: tstl %d0            ; strlen result -- PASSED all 5 times
400848e4: blew 0x4008498c
400848e8: movel %a2@(262),%d0
400848ec: beqw 0x4008498c     ; <-- a2@(262) == 0  ==> -2      (or block B's 0x4008493a, same field)
```

So **-2 means field `+262` of the request record is NULL**. `a2 = 0x460bd00c` (X's pointer minus 1),
which is the record posted at `0x4002213e`. Next probe: `0x400848e8` (8 B hole) and/or `0x4008493a`
(6 B) recording `a2`, `a2@(262)` and 32 bytes of the record — run hookcheck on both first.

### CORRECTION 2: `FUN_40099374` is trim/loop-points, not slices
Its `%a5 = STATE@20` is only ever written back at `0x4009964e`; the body clamps `SETTINGS+300/304/308`
(trim start / length / loop point). `STATE@20` is a refcount (`movel @20,d0; addq #1,d0; bne; moveb #1`
at 0x4009405e), not a slice-table pointer. The "sampleslice" label from the earlier session is wrong,
so probe C does NOT answer the slices question — it does confirm the high slot reaches this code with
`@8 == 0`.

### CORRECTION 3: the AED is not the slice blocker
A recorded slot 143 with `@8 = 0`, `type = 0`, eight times: **the AED's has-content predicate correctly
sees the high slot as occupied.** That path is fine.

### L recorded nothing -- and that is a TIMING result, not a probe failure
`cntLall = 88` (88 slots with non-empty paths went through the bulk loader) but `cntL = 0`: **no slot
>= 128 ever reached it.** Expected for this run — project.256 was deleted, so SET-B was empty at
project-load time and the loop's first instruction (`tstb %a2@ ; beq skip`) skipped every high slot.
The path only arrived later, from the UI assign.

**But `project.work` DOES contain `TYPE=STATIC SLOT=144 PATH='../AUDIO/afo-melero.aif'`** — the
serializer writes high slots correctly, and the parser runs BEFORE the bulk load loop. So a RELOAD
should make the loop walk SET-B[15] with the path present, and L will record slot/result/path.
**That measurement needs NO new flash.** Test: delete project.256, RELOAD the project, then SAVE.

## RELOAD WORKS -- high-slot persistence is closed end-to-end [2026-08-21]

P40, after `RELOAD` with project.256 deleted (so SET-B came only from the project.work parser):

```
cntLall=266  cntL=2
L[0] slot=143 result=1 ptr=0x40a99618 [SET-B[15]=UI slot 144] path='../AUDIO/afo-mel'
L[1] slot=143 result=1  (same)
```

`0x40a99618 - SET_B = 0x4038 = 15 * 1096` exactly -> **SET-B[15] = UI slot 144**, and `result = 1` =
success. The LOADLOOP_STUB's A->B redirection works: the bulk STATIC loader walks past idx 127 into
SET-B, finds the high slot's path and loads it. HW-confirmed by the user: **slot 144 loads after
RELOAD, the AED draws the waveform, and it plays from the trigs.**

Full chain now proven: assign -> SAVE (serializer writes `TYPE=STATIC SLOT=144
PATH='../AUDIO/afo-melero.aif'` to project.work; sidecar dumps SET-B to project.256) -> RELOAD (parser
writes SET-B[15]; bulk loader loads it) -> waveform + playback. That closes the "RELOAD reverts the
slot" item open since P30.

## SLICES ROOT-CAUSED: SETTINGS+1092 (slice count) is 0 while the .ot says 11

The .ot sidecar parser `FUN_40089940` reads the file field-by-field into `d3 + N`, where d3 is the
**migrated** SETTINGS pointer (clamp raised to #255 at 0x40089958, site 0x4008996c -> h_set_d3 --
verified on the BUILT image). Its layout:

```
40089cc8: subal %a2,%a2                 ; i = 0
40089cca: pea 0xc                       ; read 12 bytes per slice
  ...     dest = d3 + 300 + i*12        ; slice array = SETTINGS[300 .. 1068)
40089d10: moveq #64,%d2 ; cmpl %a2,%d2 ; bne  -> 64 iterations
40089d16: lea %a2@(1092),%a2 ; pea 0x4 ; jsr read   ; SLICE COUNT -> SETTINGS+1092
```

Measured directly out of project.256, `SET-B[15]` (UI slot 144):

```
SETTINGS+1092 (0x444) = 0            <- slice count
bytes 0x440..0x448   = all zero
/universi/AUDIO/afo-melero.ot        <- u32 at 0x33a = 11 slices
slice array 0x12c..0x42c             = zero except 0x131..0x134
```

The lone non-zero run at +305 is the trim/loop triple that `FUN_40099374` writes to
`SETTINGS+300/304/308` (which shares the first 12 bytes with slice[0]) -- not parser output.
**So the .ot slice loop never ran for this slot.** Scalar attributes DID land (length at +0x104,
tempo `0x09bb` at +0x116, `0x639750` at +0x131), so the parser started and got through the early
fields, then either bailed at one of its many `blt 0x40089d7a` error exits or was never invoked on
this path at all.

NEXT (needs a probe): instrument `0x40089940` entry (slot + which exit) and the error exit
`0x40089d7a`/`0x40089d78`. Run `tools/hookcheck.py` on both before writing a byte.

## TOOL FIX: `tools/fnscan.py` was reading STOCK
Same defect as the old otdis: it hard-coded `out/stock_mainos.bin`, so it reported
`0x4008996c addi #0x100d5b30,d3` and `cmpi #128` where the BUILT image has `jsr 0x400d7480` (h_set_d3)
and `cmpi #255`. Now defaults to `out/mainos_persist256.bin`, honours `OTDIS_IMG`, falls back to stock,
and prints `[fnscan] scanning <path>`. Fifth tool in this family; distrust any earlier fnscan output.

## The `-2` popup is unrelated to the high slot
Even on this clean successful reload, `cntB=1` with the same `result=-2 a2=0x460364e4`, while
`L` shows the high slot loading with `result=1`. X again caught only the five `'/universi/AUDIO/'`
strlen calls, all passing. So the popup is a **separate** request failing on `a2@(262) == 0`, not the
sample load. Worth checking whether it also fires on a stock-only project (i.e. pre-existing).

## P41 RESULT: the .ot parser is NEVER INVOKED for a high slot [2026-08-21]

```
cntP = 0     cntS1 = 0     cntE = 0        (parser entry / slice-loop-done / parser exit)
cntB = 1     cntL = 0      cntLall = 88
SET-B[15] = UI slot 144 = '../AUDIO/afo-melero.aif'   slicecount(+1092) = 0
```

Not aborted, not failing — **never called**. That clears `FUN_40089940` itself: it is correctly
migrated and would have written SET-B if it ran.

`FUN_40089940` has exactly **one** caller: `0x40084eba`, inside the loader state machine. The state
that reaches it starts at `0x40084e7a`:

```
40084e7a: movel %a2@(270),%sp@- ; jsr %pc@(0x40084094)     ; register/yield
40084e82: movel #65536,%sp@-    ; pea 0x460263e0 ; pea 0x400b328b ; pea %a2@(10)
40084e98: movel %fp,%d3 ; addil #-30,%d3 ; movel %d3,%sp@-
40084ea2: jsr 0x40016864                                    ; open the .ot sidecar
40084eac: tstl %d0 ; blts 0x40084ee4                        ; <-- open FAILS => parser SKIPPED
40084eb0: movel %a2@(2),%sp@-   ; slot   (arg3)
40084eb4: movel %a2@(6),%sp@-   ; type   (arg2)
40084eb8: movel %d3,%sp@-       ; handle (arg1)
40084eba: jsr 0x40089940
```

So the slot the parser gets comes from `a2@(2)` of the job record — the same field layout as the job
records seen earlier. Two possibilities remain: the state never runs for the high slot, or it runs and
the `.ot` open at `0x40084ea2` fails. Note `0x4008498c`'s `-2` exit branches to `0x40084e70`, which is
a *different* state (`push d0 ; push a2@(278) ; bra 0x400849ea` = post the completion) — adjacent in
the listing but not the same path.

## P42 (`DUAL256P42`, sha256 `b8c8ebe0…`) -- `tools/build_diag_loaderr10.py`, 516 B at cave 0x400d7100

| probe | site | hole | records |
|---|---|---|---|
| B | 0x40022b50 | 6 | `[result][callerPC][a2]` |
| **ST** | **0x40084e7a** | 8 | UNFILTERED `[jobrec][a2@2 slot][a2@6 type]` + total at +0x2c — does the state run at all? |
| **O** | **0x40084ea8** | 6 | `[open result][jobrec][16 bytes of the filename at a2@(10)]` — did the .ot open? |
| P | 0x40089940 | 8 | `[slot][type][handle]`, slot >= 128, + unfiltered total at +0x20 |
| L | 0x400908ac | 6 | `[slot][result][pathptr][str16]`, slot >= 128 |

ST's replay reproduces `jsr %pc@(0x40084094)` as `pea 0x40084e82 ; jmp 0x40084094` rather than a real
`jsr` + `jmp`, so the callee sees the ORIGINAL return address on the stack — safe even if that function
does anything with it. The gate asserts both pushed longs.

Layout (768 B, offsets): `+0x04 cntB +0x0c cntL +0x18 cntLall +0x1c cntP +0x20 cntPall +0x24 cntST
+0x28 cntO +0x2c cntSTall`; `+0x40 B[8]x12  +0xa0 L[8]x28  +0x180 P[8]x12  +0x1e0 ST[8]x12  +0x240 O[8]x24`.
Reserves UI slots **252 and 253**.

Build bug caught by the gate: cntST and cntSTall initially shared offset +0x24, so the manual increment
ran before `rec_alloc` read the count and entry 0 was skipped. The memory assertions flagged it
(`CNT=2 want 1`, array empty). Counters must never share an offset.

Gates: hookcheck OK; emu_probes 14/14 across B/L/P/ST/O; emu_check GREEN; audit identical to base;
exact unmerged byte diff = the five holes (6/8/6/8/6) + `[0x400d7100,0x400d7304)`; no cave write
outside `{d0-d3,a0,a1}`; cave ends in `jmp`.

## P42 RESULTS + the .ot loader is still unidentified [2026-08-21]

**User correction:** the earlier run where "slices appeared" was on a LOW slot. Re-tested properly:
**high slots have no slices, via AED FILE->LOAD NEW SAMPLE and not after RELOAD either.**

```
run A (project-open + assign):  cntP=0 cntPall=0 cntST=0 cntO=0 cntSTall=0  slicecount=0
run B (AED FILE->LOAD, low):    cntP=0 cntPall=0 cntST=0 cntO=0             slicecount=0
run C (AED FILE->LOAD, high):   cntB=4 cntL=4 cntLall=444  all parser counters 0
```

**`FUN_40089940` never executes -- for ANY slot.** `cntPall` is the UNFILTERED total and the gate now
proves it ticks for a low slot too (`P unfiltered total` check), so the zero is real, not a filter
artifact. The state at `0x40084e7a` that contains its only call site never runs either (`cntSTall = 0`).
So the .ot sidecar parser we spent P41/P42 instrumenting is dead code in these flows, and the slice
data that low slots DO show comes from somewhere else entirely.

**Two false leads closed.** `0x460ba8a4` (STATIC) and `0x46105424` (FLEX) looked like the slice source
-- both are copied into `SETTINGS+312` and `SETTINGS+1092` at `0x40093fbc` / `0x40096bbe`. They are a
**park/restore cache**, not a loader: the mirror site at `0x400936ec..0x40093720` does
`cache[64 + a4*4] = SETTINGS[1092]` and then `SETTINGS[1092] = 1`, i.e. it saves the slot's slice state
away and resets the slot to a single whole-sample slice. Only 6 references each, all inside those two
functions. Index `a4` is a small cache index, NOT the slot (entry stride 12 from +4, counts from +64 --
they would overlap past index 4).

## P43 (`DUAL256P43`, sha256 `953bc40e…`) -- `tools/build_diag_loaderr11.py`, 438 B at cave 0x400d7100
Probes B / L / P (kept) plus:

| probe | site | hole | records |
|---|---|---|---|
| **AED** | **0x40070cd2** | 10 | UNFILTERED `[SETTINGS ptr][slice count][slice[0] word]` + total at +0x2c |

`0x40070cd2` is the exact instruction where the AED SLICE tab loads the count it will draw
(`movel %a3@(1092),%d3`), and `a3` comes from the migrated getter `0x4006da78` two instructions earlier,
so the pointer names the slot: SET-A -> `(p-0x100d5b30)/0x448`, SET-B -> `128+(p-SET_B)/0x448`.

**Test:** open the AED on a LOW slot that draws slices, then on the HIGH slot that does not, then SAVE.
Reserves UI slots 252 and 253. Delete project.256 first.

It decides between the only two possibilities left:
- low slot non-zero + high slot zero -> `+1092` IS the field the screen uses; fix the writer
- low slot ALSO zero but still draws -> the screen reads slices from elsewhere and `+1092` is a red
  herring (which would also explain why the `.ot` parser being dead does not stop low slots working)

Gates: hookcheck OK; emu_probes 11/11 (B/L/P/AED); emu_check GREEN; audit identical to base; zero
changes outside the four holes and the cave.
