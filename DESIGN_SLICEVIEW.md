# DESIGN: SLICE PLAYHEAD — a readable SLICES view

> **STATUS: implemented, emulator-green, packaged as OMAX2SV01 — awaiting HW test.**
> `tools/patch_sliceview.s` + `tools/build_sliceview.py`, integrated as build_all step 5.
> The periodic-repaint question (§5.1) was answered better than planned: the timer task
> at `0x40056c40` calls the countdown tick for every type-1 timer message, and the 6-byte
> `tstl 0x46104ca8` right after that call (`0x40056c92`) is a clean hole that runs even
> with NO TIMER enabled. The stub posts event 78 (handler `0x40062d04` → `jsr 0x4004581c`
> = view header+content redraw) to the UI queue — the same post the stock timer task
> makes — throttled to one outstanding message (flag cleared by the renderer, retried
> after 64 ticks so a modal can't wedge it). Renderer detours `0x40044cf0` in the SLICES
> arm; flag off replays the displaced `pea` byte-for-byte. HW will decide the tick rate
> (blink divider = BLINKCTR bit 3) and the final look.

Replace the 4×16 slice-grid area of the SRC SLICES view (FUNC+[down] → SLICES)
with: the currently-playing slice number drawn large and blinking, a progress
bar for playback position inside the slice, and a loop marker when the slice
has a loop point configured. Gated behind a new PERSONALIZE toggle, OFF by
default (stock behaviour byte-for-byte when off).

Feasibility verdict: **HIGH**. All three pillars are already resolved against
the stock image; one small RE item remains (periodic repaint tick, §5).

---

## 1. Data: everything is readable CPU-side

The playback position engine (window bounds, live position, loop wrap,
ping-pong, one-shot end) runs on the ColdFire in `FUN_40007960` — not on the
DSP. Per-track voice struct at `0x800049d8`, stride `0xA8` (8 voices; voice
index ≡ track for sample machines):

| field | meaning |
|---|---|
| `voice@0` (b) | active: `0xFF` playing, `0` free (one-shot end clears it, `0x40008ea6`) |
| `voice@8` (l) | SETTINGS ptr — already slot-resolved (works for any slot) |
| `voice@23` (b) | resolved loop mode: 0 one-shot, 1 loop, 2 ping-pong (W `0x40007b8e`) |
| `voice@32` (b) | **current slice index**, signed, `-1` = no slice (W `0x4000f67c`, re-bound every audio frame → tracks p-locks/scenes live) |
| `voice@36` (w) | signed rate, `0x4000` = 1.0×; negative ⇒ reverse |
| `voice@48/52` (l) | ACTIVE window start / end |
| `voice@68` (l) | **live integer play position** (`addql #1` @`0x40008898` fwd, `subql #1` @`0x40008e6e` rev) |

Slice table, via `SETTINGS = voice@8`:
- entry `n` at `SETTINGS + 312 + n*12` = `{start, end, loop}`; loop `< 0`
  (0xFFFFFFFF) ⇒ **no loop point** for that slice
- count at `SETTINGS + 1092`
- firmware indexes as `+300 + (slice+1)*12` (entry −1 = whole-sample trim)

Progress formula (denominator from the live window so it stays right after a
loop wrap):

```
pct = (voice@68 - voice@48) * 100 / (voice@52 - voice@48)   ; if @52 > @48
```

Loop marker: slice entry `+8 >= 0`, or simply `voice@23 != 0` for the resolved
answer (also distinguishes ping-pong).

Torn reads: `@48/@52/@68` are rewritten as six longs inside the audio path on a
loop wrap (`0x400088dc..0x40008902`). Mitigation: read, clamp `pos` into
`[lo, hi]`, and reject/redraw-next-tick if outside. No interrupt masking
needed for a cosmetic display.

Helper: `FUN_40000e50(voice) → 0x800049d8 + voice*168` (safe resolver).
Current track byte: `0x100b14cc`.

## 2. Rendering: primitives and geometry are mapped

Screen surface descriptor `0x400bf10a` = 128×64, column-major, 32 px/longword.
All primitives cdecl, `mode`: 1=set, 0=clear, −1=XOR.

| fn | signature |
|---|---|
| `0x40012254` | `fillrect(surf, x0, y0, x1, y1, mode)` — bar + clearing |
| `0x40012bd8` | `drawtext(font, surf, x, y, mode, str)` |
| `0x40013904` | `drawfmt(font, surf, x, y, align, mode, measureStr, fmt, ...)` |
| `0x40011b94` | `vline(surf, x, y0, y1, mode)` |
| `0x400128a8` | `blit(bitmapDesc, surf, x, y)` |

Fonts: `0x400ba876` (default 6 px), **`0x400ba89e` (12 px — the big slice
number)**. Dirty flag to request a flush: `move.l #1, 0x46c7c72c`.

The stock SLICES content renderer is the view-3 arm of `0x40044920`
(`0x40044cda..0x40044f06`): blits the 57×15 grid bitmap `0x400beafa` at
(61,10), resolves track → machine type → slot → SETTINGS out of the project
blob, reads the slice count at `0x40044e28` (`SETTINGS+1092`), draws empty
markers and the page ticks. Grid area to reclaim: x 61..117, y 10..24.
Header ("SLICES 1-16") is separate (`0x40035f78`) and stays.

## 3. Hook plan

- **Content replacement** — 6-byte detour at **`0x40044cf0`**
  (`pea 0x400beafa`, first instruction of the SLICES arm; hookcheck OK).
  Stub: `tst.l FLAG ; beq stock` → replay + resume for stock. Flag on: run the
  custom renderer (reuse the same project-blob math the stock arm uses, read
  the voice struct, draw number/bar/loop mark) then `jmp 0x400453e2` (dirty +
  epilogue), skipping the grid entirely.
- Alternative append-only site (keep grid, add overlay): `0x40044eaa`
  (`movel 0x460d16f4,%d0`, hookcheck OK).
- View/state guards the stub must respect: `0x460d16f0 == 3` (SLICES view),
  `0x460d1aec == 0` (no modal) — both already checked upstream of the arm, so
  hooking inside the arm inherits them. **Plus `0x80000012 == 0` (not MIDI
  mode)**: the view index is shared with the MIDI pages (the MIDI ARP setup page
  is view 3 too), so every hook checks the MIDI flag itself (2026-09-26 fix).
- **Reentrancy rule** (patch_gui VEC:0B lesson): the renderer keeps no
  per-call globals, or guards them.

## 4. Preference toggle (recipe already proven by NO TIMER / LAZY)

- Flag word: `0x800000a8` or `0x800000dc` (last two free words in the
  battery-backed PERSONALIZE block; zero refs in the image). 0 = off = stock.
  Persists across power cycles, cleared by EMPTY RESET / OS upgrade — no file
  format change.
- Menu: grow the relocated arrays at `0x400d6a00/0x400d6a50/0x400d6aa0` from
  18 → 19 entries (stride 0x50 allows 20), append label/getter/setter symbols
  (copy `patch_notimer.s:77-95`: glyphs `0x400b5e90`/`0x400b5e8e`, setter
  `(flag + 4(%sp)) & 1`), bump `0x40068fb2` `moveq #17` → `moveq #18`.
  The five table refs already point into the cave — no further repointing.
- Suggested label: `SLICE PLAYHEAD`.

## 5. Open items (the only real RE left)

1. **Periodic repaint.** The UI loop is event-driven: it blocks on the message
   queue and flushes (`jsr 0x40013abc` @ `0x40062d46`) only when dirty
   (`0x46c7c72c`) is set. Playback does not set dirty, so the bar would
   freeze between events. Plan A: piggyback the countdown tick
   `FUN_40056ab8` (already detoured by NO TIMER — it is a proven periodic UI
   tick): when flag on ∧ view==3 ∧ no modal, set dirty. Measure its rate on
   HW; if too slow/fast, Plan B: decode the 78-entry UI event table at
   `0x40061cfa` and find the timer event. Blink phase = a patch-owned counter
   in free RAM `0x80006c66+`, toggled by the same tick (no RTC needed).
2. **Flush-suppression interaction**: `0x460d1a54 == 2` suppresses flushes;
   the tick hook must not fight it (just set dirty, never call the compositor
   directly).
3. Units of `voice@68` (frames vs samples) don't matter for a ratio — both
   numerator and denominator share the domain.
4. Dual-256 high slots: `SETTINGS+1092 == 0` there (known open bug), so
   `voice@32` reads −1 and the view shows "no slice". Orthogonal; fixing
   slices-on-high-slots is its own line of work.

## 6. Cave budget

Combined OCTAMAX_2 image is nearly solid. Free gaps: **862 B at `0x400d70a2`**
(target — renderer + tick stub + menu strings fit comfortably), 484 B at
`0x400d6e1c`, 249 B at `0x400d7b43`. `build_all.py` read-back assertions and
`build.py` overlap/zero checks gate collisions.

## 7. Verification path (before any flash)

1. `tools/emu_recvoice.py` (Unicorn, runs `FUN_40007960`) — prove the progress
   formula against emulated wraps, forward and reverse.
2. `tools/emu_voicebind.py` — assert `voice@32` for sliced/unsliced binds.
3. New `emu_sliceview.py` (pattern: `emu_bankpage.py`) — seed globals, force
   flag both ways, execute the detour: flag off ⇒ byte-identical stock flow;
   flag on ⇒ draw calls land with sane args.
4. `tools/hookcheck.py` on every hole; `tools/emu_image.py` with the new
   detour + stub span registered; `emu_check` / `verify_dual256` / `audit`
   stay green.
5. HW: reuse `tools/build_diag256_voicedump.py` to validate `@32/@68/@23`
   live, then flash a versioned build (unique name) and eyeball the view.

## 8. UI sketch (area x 61..117, y 10..24, header untouched)

```
┌ SLICES ─────────── 1-16 ┐   header (stock)
│  ██  ██   ▐███████▌     │   12px font: slice number (blinks while voice
│  ██████   ▐██▌↻         │   active, XOR toggled by tick counter)
│      ██   [======   ]   │   progress bar ~40×5 px, fillrect
└─────────────────────────┘   ↻ = loop glyph when entry+8 >= 0 (▐▌ ping-pong)
```

No slice playing (`voice@0==0` or `voice@32<0`): dimmed "--" + empty bar.
Reverse (`voice@36<0`): bar fills right→left.
