# HOT CHANGE — live project change without stopping a recorder-buffer voice

Educational reverse-engineering log for the Octatrack MKII (OS 1.40C). Goal, mechanism,
everything tried, the tools built, the current wall, and the concrete next steps.

## Goal & success criterion

Change to a **sibling project** *without stopping the audio of a Flex/recorder track that is
playing a recorder buffer* — the live-performance "bridge": capture live audio into a recorder
buffer (R7 = recorder 7 = slot 0x86), change project, and have that buffer keep sounding to
cover the load. **Success = the audio does not stop.** If it stops, stock CHANGE PROJECT is no
worse, so a partial bridge is not shippable. Only track 7 (voice index 6) needs to survive;
non-matching audio may stop. Sibling shares the RESERVE RECORDINGS (flex) format.

## Architecture (what actually makes sound)

- **Two processors.** A ColdFire MCF5445x main CPU (OS, sequencer, UI) and a separate
  **DSP56300** that synthesizes audio. They share RAM + a mailbox (producer/consumer).
- **The DSP is fed frame-by-frame.** Every audio frame the CPU assembles a per-voice parameter
  packet in shared RAM (double buffer at `0x80000000`, selector `0x800000e0`) and pokes the DSP
  (cmd `0x8b` to `0x20000004` in `FUN_4000a8fc`). **The DSP does not play autonomously** — if the
  CPU stops feeding a voice, it goes silent with no explicit "stop".
- **A recorder buffer is PCM in a paged RAM pool** (base `0x40a955e0`, ~89 MB). We proved this
  data survives a project change (pool + metadata preserved). The audio itself is never lost.
- **Playback is sequencer-driven (trig).** After a project load the sound returns exactly when
  the sequencer next hits the track's trig — the tell that the *voice*, not the *data*, is lost.

## The cut mechanism (fully mapped)

A project load reboots the whole audio-engine state: it tears down every track's voice and
rebuilds them from the loaded project. Key functions:

- `FUN_40007960` — the **per-frame recorder-voice processor** (sole caller `FUN_40004008`, a
  root/vectored audio path). It takes the **PLAY** path (produces R7's DSP frame) only if a chain
  of checks pass; otherwise it jumps to `0x40008110` → `FUN_40006820` (voice stop) or `0x4000812c`
  (MUTE2). Checks found (via RE + Unicorn, since this function has **no EMAC** and *runs* under
  Unicorn — unlike the frame builder):
  - recorder metadata (`voice+0x4` → `0x46c939cc`): `state(+0x8)==0` **and** `length(+0x10)>0`
  - `gen(meta+0x14) == voice+0x10`
  - `o0` (voice-active byte at `0x80004dc8`) non-zero
  - a **streaming** check `FUN_40001598`: play position vs recorder write-position tables
    `0x46c7ff42[rec]` / `0x46c7fe24[rec]` and `voice+0x5c/0x60`
  - deeper play-path byte checks (e.g. `voice+0x18` byte0 != 0)
- `FUN_40006820` — per-track voice stop: clears `o0`, sends the DSP note-off via `FUN_4000672c`
  (the single note-off funnel; only `FUN_40006820` and `FUN_40008f84` reach it).
- `FUN_4000c8a4` / `FUN_4000c11a` — the **frame builder** (hot path). Uses ColdFire **EMAC**
  (MAC/MSAC) + `bfextu` → **Unicorn cannot execute it**, and no available emulator can. It does
  NOT read the recorder metadata directly (only `0x80000110`, `0x800000e0`, applied-part flags).

**So the cut is: the load invalidates the recorder-voice state; `FUN_40007960` then fails a check
and does not feed the DSP → silence. The buffer PCM is intact; the *voice* is unfed.**

## The progress ladder (each fix fed the voice a bit longer)

| Build | Change | Result |
|---|---|---|
| v8–v14 | preserve pool pages (`hot_reinit` flex-only reinit) + snapshot/restore R7 metadata + settings | buffer + waveform + BPM survive; audio ~1 s then cut, resumes at trig |
| v16 | leave `g_hot` armed through load | audio flickers on/off |
| v17 | gate `FUN_4000672c` (note-off) | **worse** — that function is voice *allocation*, gating it corrupts the voice |
| v18 | index-agnostic gate via voice type==4 | **no-op** — the type byte is 0x01, not 4 (emulator "validated" a fiction because the harness seeded the fake value) |
| v21 | hardcode track 6 in `hot_vstop`/`hot_vstop2` | `o0` preserved on HW (`V0=FF`); audio bridges ~1 s, resumes at trig |
| v22 | `hot_recmeta`: restore R7 metadata per-frame at `FUN_40007960` entry | audio bridges **noticeably longer** |
| v23 | also restore settings (0x448) per-frame | **worse** — SCREECH: the settings are DSP-read live; per-frame overwrite tears the audio |
| v25 | re-validate metadata at teardown-phase end too | bridges until **~50% of the load bar**, then cut |

## What we learned (the hard rules)

1. **Per-frame restore is safe only for CPU-side bookkeeping** (recorder metadata), **not for
   DSP-read data** (the 0x448 settings) — overwriting live DSP-read state corrupts the audio.
2. **The emulator can mislead** if you seed guessed values. Only the **hardware CF log** exposed
   that the voice type byte is 0x01, not 4, and that the only externally-disturbed field is `ml`.
3. **`FUN_40007960` (the decision) IS emulatable** (`tools/emu_recvoice.py`) — the frame builder is
   not. So the play/mute decision can be tested off-hardware; the actual audio cannot.
4. The only externally-disturbed state captured PLAY-vs-post-load is the recorder **length `ml`**
   (`0x46c939dc`: 0x556BC → 0). Everything else external (tables, position, settings[0], state) is
   preserved *at end of load*. But the cut happens **mid-load (~50%)**, where more may be
   transiently disturbed and recover by end — the before/after capture misses that transient.

## Tools built (reusable)

- `tools/patch_hotchange.s` + `build_hotchange.py` — the 9-detour HOT CHANGE patch (pool preserve,
  `hot_vstop`/`hot_vstop2` keep `o0`, `hot_recmeta` restore metadata per-frame, etc.).
- `tools/patch_hotdbg.s` + `build_hotdbg.py` — **CF text logging** via the firmware's own file
  primitives: `FUN_40016864` open, `FUN_400166b8` write, `FUN_4001677c` close, `FUN_40013a08`
  sprintf → `/HOTDBG.TXT`. Hardware observability (the frame builder can't be emulated).
- `tools/emu_recvoice.py` — runs `FUN_40007960` under Unicorn; tells PLAY vs which MUTE for a given
  state. `tools/emu_hotchange.py` — traces the stop/note-off primitives + `g_hot`.

## Current wall (honest)

The recorder-playback voice is a **DSP-driven, continuously-fed** voice with extensive, timing-
sensitive live state (metadata + 0x448 settings + streaming tables + position + voice fields). The
load disrupts it mid-way (~50%). Surgical CPU-side preservation is fundamentally limited: the state
that still cuts is read by the un-hookable frame builder / the deep play-path, some of it can't be
restored without corruption, and the disruption is a mid-load transient the end-of-load capture
can't see. We reached "bridges to ~50% of the load" — real, but not "does not stop".

## Concrete next steps (in order of promise)

1. **Mid-load timeline capture.** Detour several load phases (the load orchestrator `FUN_4008445c`
   sub-calls: `FUN_40096f24`, `FUN_40096300`, `FUN_40095a90`, `FUN_400905d4`, `FUN_400238a4`) and
   log the *full* recorder-voice + play-path state (metadata, tables, `voice+0x5c/0x60/0x18`,
   settings fields `FUN_40007960` reads) at each, with a phase tag. This pins **exactly** what is
   disturbed at the ~50% cut — the before/after capture cannot. Then feed those real values into
   `emu_recvoice.py` to confirm which check mutes, and preserve/gate precisely that.
2. **Force the PLAY path.** Detour `FUN_40007960`: for track 6 while `g_hot`, after `hot_recmeta`
   has restored the metadata, jump past the mute checks into the play computation. Emulator-verify
   it runs to completion without crash first. Risk: wrong params if deep state is off (but sound,
   not silence).
3. **Reconsider the architecture.** Truly zero-gap may require not rebooting the engine at all —
   the hardware-proven **RELOAD** path loads sibling banks with NO audio stop (`tools/patch_bankpage*`),
   but only works when siblings share the sample pool. Or a capture path that plays the bridge
   through a mechanism the load doesn't tear down.

## Key addresses (for future work)

- voice[6] base `0x80004dc8` (stride 0xA8); `o0`=+0, meta ptr=+0x4 (`0x46c939cc`), settings ptr=+0x8
  (`0x100d52a0`), gen=+0x10, type/slot=+0x14 (`0x01860001`, byte@+0x15 = slot 0x86 = rec 6).
- recorder metadata `0x46c939cc` (0x2c): state+0x8, length+0x10 (`0x46c939dc`), gen/handle+0x14.
- recorder settings `0x100d52a0` (0x448): trim/loop/slices/BPM — **DSP-read live, do not per-frame
  overwrite**.
- streaming tables `0x46c7ff42[rec]`, `0x46c7fe24[rec]`.
- per-frame recorder-voice processor `FUN_40007960` (emulatable); voice stop `FUN_40006820`;
  note-off funnel `FUN_4000672c`; frame builder `FUN_4000c8a4`/`FUN_4000c11a` (EMAC, not emulatable).

## The progress meter + the force experiment — DEFINITIVE conclusion  [2026-08-01]

Built a progress meter (MAXOHT26): detours on `FUN_40007960`'s two non-PLAY exits
(`0x40008110` stop, `0x4000812c` MUTE2) + a call counter, logging `fmute` (frame of first
track-6 mute), `which` (1/2), `g` (total calls), `m1`/`m2`. This is the anti-circular tool:
`fmute`/`m2` are objective, comparable across builds; `which` names the blocker.

Baseline MAXOHT26: `fmute=8 which=2 g=254963 m1=21869 m2=130851` — MUTE2 (`0x4000812c`)
dominates by ~6x; the voice plays/mutes INTERMITTENTLY (first mute at frame 8 is transient;
the perceived cut is at ~50% of the load bar).

RE of the caller chain: `FUN_40007960`'s D5 (arg 0x1c) comes from `FUN_40004008` @0x400041b2:
`sne` of `bclr.b #4,(0x43,SP)` — a flag bit that is set during play, clear during load.
Emulator: D5!=0 skips the D4/D5 MUTE2 gate (`0x40007a26`).

MAXOHT27 (force D5=0xFF for track 6): `m1=16133 m2=130877` — **m2 UNCHANGED**, and the audio
got WORSE (cut at ~15% vs ~50%). Conclusion: the D5 gate was NOT the dominant MUTE2; forcing D5
drove the play path into the DEEPER MUTE2 branch (`0x40007efe`, `voice+0x18 byte0 == 0`), which
CLEARS voice fields (`clr voice+0x78/7c/80/88`, `voice+0x84=1`) — actively degrading the voice.

**DEFINITIVE: forcing individual play-gates BACKFIRES.** `FUN_40007960`'s PLAY path is a chain
of gates (D5 flag, D4 streaming, `voice+0x18`, deeper), each fed by state the load
comprehensively resets. Forcing one gate reaches a deeper broken gate that corrupts. And the
coherent full state can't be surgically preserved: `o0` (hot_vstop ✓) + metadata (hot_recmeta ✓)
help to ~50%, but the settings (0x448) can't be restored (DSP-read, corrupts), and the play-flags
are dynamic. **Surgical preservation of the recorder-playback voice through a full project load
is not achievable — the state is too extensive, dynamic, and DSP-coupled.** Best result: ~50% bridge.

The GOAL (audio never stops) therefore needs an ARCHITECTURAL change, not more gates: either the
hardware-proven RELOAD path (no engine reboot -> no audio stop, but siblings must share the sample
pool), or a mechanism that plays the bridge outside the sequenced-voice path the load tears down.
