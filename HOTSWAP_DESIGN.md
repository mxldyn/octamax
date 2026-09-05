# HOT SWAP — live project change without stopping the recorder voice (architectural approach)

After the surgical approach hit its ceiling (see HOTCHANGE_FINDINGS.md — you cannot keep a
DSP-driven recorder voice alive through CHANGE PROJECT's full audio-engine reboot), the path to
the goal is to **not reboot the engine**: build a custom load that brings the sibling's data
(banks + samples + settings) without the voice teardown, so the recorder voice never stops.

Proven building blocks:
- **RELOAD / bank-paging** loads sibling banks with NO audio stop (hardware-validated, S1/S3;
  `tools/patch_bankpage*.s`). The two audio-stoppers (`FUN_400a10c8` pre-step, `FUN_400238a4`
  re-sync) are avoidable.
- **Region separation**: the recorder buffer lives in the HIGH pages of the flex pool; flex
  samples in the LOW pages. Loading flex samples does not physically touch the recorder region.
- **`hot_reinit`** / the `FUN_40096a5c` 0x88→0x80 bound: flex pool (re)init that PRESERVES the
  recorder region.

## The audiopool loader (decompiled — the key find)

`FUN_4009083c(prog_cb, done_cb)` loads a project's samples:
```
FUN_4009395c()                          // init
for slot 0..0x7f:                       // STATIC samples
    if settings[0x100d5b30 + slot*0x448] has a name and is valid:
        FUN_40093980(slot, 1)           // load STATIC slot
FUN_40096a5c()                          // flex pool (re)init  <-- make it recorder-preserving
for slot 0..0x7f:                       // FLEX samples
    if settings[0x100b14f0 + slot*0x448] has a name and is valid:
        FUN_40096548(slot, 1)           // load FLEX slot into the pool
```
So the sample set is driven entirely by the two settings arrays:
- `0x100b14f0` — FLEX sample settings (0x448 per slot; +0 = name, holds path/trim/loop/BPM).
- `0x100d5b30` — STATIC sample settings (same layout).
The per-slot loaders (`FUN_40096548` flex, `FUN_40093980` static) read the name and stream the
`.wav` from `<proj>/AUDIO/<name>.wav` into the pool. The project's sample LIST is parsed from
`<proj>/project.work` (`[SAMPLE] TYPE=FLEX ...`) by `FUN_40088288`.

## Hot-swap sequence (design)

While the recorder voice (track 6 / R7) keeps playing (we run NO voice teardown):
1. **Load the sibling's project data** into RAM:
   - sample list → the `0x100b14f0` / `0x100d5b30` settings arrays (parse sibling `project.work`
     via `FUN_40088288`, redirected to the sibling dir like bank-paging's `g_redirect`).
   - banks (patterns/parts) → the resident bank RAM (RELOAD job, `FUN_4008f0b0`/`FUN_400905d4`).
2. **Load the sibling's samples**: call `FUN_4009083c` with a **recorder-preserving `FUN_40096a5c`**
   (0x88→0x80) so the flex (re)init keeps the recorder pages. This clears the old flex samples
   (low pages) and streams the sibling's — the recorder buffer (high pages) is untouched.
3. **Apply** the new part/pattern to the tracks (the non-recorder tracks pick up new samples; the
   recorder track keeps playing its buffer).
4. Never call the teardown (`FUN_400a10c8`, `FUN_400238a4`, the voice reset) for the recorder voice.

Non-matching audio (flex tracks) may glitch/stop during the swap — acceptable per the goal.

## First validation (before building the whole feature)

**Q: does `FUN_4009083c` (flex/static reload) with a recorder-preserving `FUN_40096a5c` keep the
recorder voice playing?** If yes, the core is sound and we extend to the sibling. If no, the flex
reload itself disturbs the recorder voice and needs more work.

Build: patch `FUN_40096a5c` bound 0x88→0x80 (recorder-preserving) + a trigger (reuse a key/gesture)
that calls `FUN_4009083c(0,0)` on the CURRENT project while R7 plays. Observe: does R7 keep sounding?

## Open questions to resolve while building

- Does `FUN_40096a5c` (stock) reset recorder metadata/voice, or only the flex pages? (RE it.)
- Can the sibling's `project.work` be parsed into `0x100b14f0` without disturbing the running
  engine? (redirect `FUN_40088288`/the project-file read to the sibling dir.)
- Bank + sample + settings must come from the SAME sibling and be consistent at swap time.
- Where to atomically "commit" the swap (project name pointer `0x100f8378`, current bank/pattern).
