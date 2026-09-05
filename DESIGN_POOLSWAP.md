# DESIGN — Live audiopool swap, recorder-preserving

**Status:** design complete, pre-implementation. RE fully mapped (see NOTES.md
"Live pool swap — RECORDER-PRESERVING design"). Hardware verification pending.

## Goal & contract

Let the user change the project (a full audiopool swap — different flex 0-127 AND
different static, any project) **without cutting the 8 recording buffers**. An audio cut
for everything else is acceptable.

**User contract:** during the swap, nothing is sounding except recording-buffer audio.
The user records the live audio into a recorder, mutes all other tracks, changes project
(the recorder bridges the gap), then fades into the new project's tracks.

**Hard requirement:** the target project must share the **flex FORMAT** (RESERVE RECORDINGS
config, `DAT_80000051..56`) so the reserved recorder pages stay at the same RAM addresses
and no DSP reformat runs. Documented as a sibling constraint (like the shared-pool one).

## Why it works (from RE)

- The flex pool is PAGED: 0x1800-byte pages from a pool at `0x40a955e0`.
- Flex slots 0-127 are (re)packed by a page/bump allocator on every project load ->
  touching them under a sounding voice glitches. This is the physical reason for the stop.
- **Recorders 0x80-0x87 live in a SEPARATE RESERVED page range** (`(rec+2)*0x390a`), sized
  by the flex format, managed by `FUN_40095a90`/`FUN_400948cc` — independent of the flex-slot
  packing. If the format is unchanged, their pages are fixed and untouched by a flex reload.
- So: preserve the recorder pages + keep their voices alive, reload everything else.

## Hooks (3 changes + 1 gate)

All gated on a PERSONALIZE toggle **LIVE POOL SWAP** (OFF by default), read in the change path.

1. **Spare active voices in the kill.** `do_project_change` FUN_40063e28(0) calls
   `FUN_40008fe4(0xffffffff)` (kill all 8) + `FUN_400a10c8` (panic). Replace the blanket
   kill with a masked kill that SKIPS currently-active voices (`FUN_40000e50(t)[0] != 0`,
   optionally also `[0x14]==4`). Ensure FUN_400a10c8's panic path doesn't stop them either
   (it clears mailboxes/MIDI/arp; the DSP keeps reading the recorder pages).
   - Voice active test: `(&DAT_800049d8)[t*0xa8] != 0`.
   - Recorder-type refine (optional): voice `[0x14] == 4`; `_DAT_461054ec` is a live
     recorder-track bitmask maintained by FUN_4000672c.

2. **Preserve recorder pages.** Flex prep `FUN_40096a5c` unloads all 136 slots
   unconditionally via `FUN_40096300(slot)`. SKIP slots 0x80-0x87 (recorders) so their pages
   are not reclaimed. The load loop `FUN_4009083c` already skips recorders (they have no path
   in the 0x448 table), so no change needed there.

3. **Leave flex 0-127 + static + banks/parts/patterns loading normally** (the cut is fine).
   Their reload won't touch reserved recorder pages (format unchanged).

4. **Gate + pre-load format check (safety net).** If LIVE POOL SWAP is OFF, use the stock
   change. If ON, BEFORE committing the load, peek the target project's format from its
   text settings file and compare to the live format:
   - Open `<set>/<project>/project.work` (fmt `%s/%s/project.work` @0x400b5ccd) via the
     file-open primitive `FUN_40016864` (same non-invasive file-peek proven in bank paging).
   - Read into a scratch buffer; extract the 5 format values by substring `KEY=` + atoi:
     `RESERVED_RECORDER_COUNT`, `RESERVED_RECORDER_LENGTH`, `DYNAMIC_RECORDERS`,
     `RECORD_24BIT`, `LOAD_24BIT_FLEX` (all serialized as text — confirmed in FUN_40088288).
   - Compare to the live format `DAT_80000051..56` (persistent mirror `DAT_100b14b1..b6`).
   - MATCH -> live swap (preserve recorders + spare voices).
   - MISMATCH -> follow STOCK behavior: show "PLAYBACK WILL BE STOPPED. CONTINUE?" (the
     existing popup) -> YES: stock teardown + normal load; NO: abort, keep playing.
     (User's decision: no custom keep-playing path; just defer to stock warn+choose.)
   This makes the format requirement a safety net, not a trap: no silent glitch, no
   unexpected stop.

### Structural implication — teardown must be DEFERRED past the picker
Stock flow kills audio UP FRONT, before you pick the target:
  `change_project_handler` FUN_40063e48 -> (popup) -> `FUN_40063e28(0)` = FUN_400a10c8() +
  FUN_40008fe4(0xffffffff) [KILL] + FUN_400647a0() [open CHOOSE PROJECT picker].
So at kill-time the target project (and its format) is unknown. The live path must defer:
- When LIVE POOL SWAP is ON, `FUN_40063e28` SKIPS the up-front FUN_400a10c8 + FUN_40008fe4
  and just opens the picker -> audio stays alive while browsing.
- At the actual load (once the target is known — the picker's select-confirm -> load entry;
  exact fn still to pinpoint, NOT FUN_40063ee4 which only closes/redraws the picker), read
  the target format and branch:
    MATCH   -> recorder-preserving load (voices were never killed; skip recorder unload).
    MISMATCH-> now run the stock "PLAYBACK WILL BE STOPPED. CONTINUE?" -> YES teardown+load,
               NO abort (audio keeps playing).
- NOTE for the MINIMAL de-risk build: testing hypothesis #1 needs only "skip the up-front
  kill + skip recorder unload" (the user manually picks a same-format sibling). Not killing
  already keeps audio alive through the picker, so the picker restructure + format check are
  NOT required for the first hardware test — they are polish for graceful mismatch handling.

## Key addresses (from RE)

| What | Address |
|---|---|
| do_project_change | `FUN_40063e28` |
| kill all voices / one voice | `FUN_40008fe4` / `FUN_40008f84(t)` -> `FUN_4000672c(t)` |
| panic/reset | `FUN_400a10c8` |
| flex pool prep (unload x136) | `FUN_40096a5c` -> `FUN_40096300(slot)` |
| flex/static reload loop | `FUN_4009083c` (flex `FUN_40096548`, static `FUN_40093980`) |
| voice struct | `0x800049d8 + t*0xA8`; `[0]`=active, `[0x14]`=type |
| recorder-track bitmask | `_DAT_461054ec` |
| flex PCM pool / page | `0x40a955e0 + page*0x1800` |
| flex format (recorder reserve) | `DAT_80000051..56` |
| recorder reserved page range | `(rec+2)*0x390a` in `0x46c2e9c0` table |

## Open unknowns (hardware only)

- Does a recorder voice keep sounding across the sequencer stop + FUN_400a10c8 panic if we
  spare its voice? (Workflow implies a held/looping recorder playback that survives.)
- Confirm the non-reformat load path doesn't reset the DSP in a way that glitches the spared
  voice (format-identical requirement should prevent the reformat DSP teardown).
- Whether to spare all active voices (trust the contract) or gate on `[0x14]==4`.

## Rollout

Incremental de-risk builds (branded MAXODIAG/MAXO), like arp & bank paging:
1. Minimal: PERSONALIZE toggle + spare-active-voices + skip recorder unload; test that a
   held recorder buffer survives a project change to a same-format sibling.
2. Refine detection (type gate) and add the format-mismatch guard/fallback.
3. Ship as an optional PERSONALIZE feature in a new release.
