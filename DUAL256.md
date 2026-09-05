# DUAL-256 — 256 STATIC sample slots

An optional patch that raises the Octatrack MKII's **STATIC sample slots from 128 to 256**.
Slots 129–256 behave like the stock ones: they load samples, keep their slices, are assignable to
tracks, accept parameter locks, survive a project save/reload and a power cycle, and play immediately.

Built and verified against **OS 1.40C**. Reproducible: the same official image in gives the same
bytes out.

    mainos_persist256.bin   sha256 cf93d99c3477dfd63ceafcddb6e3629b7804f53ad2999e94382b82a9bd11e7fd

---

## What it does

| | stock | with dual-256 |
|---|---|---|
| STATIC slots | 128 | **256** |
| slice grids on high slots | — | yes, including `.ot` sidecar files |
| track → slot assignment | 1–128 | 1–256, survives save / reload / power cycle |
| parameter locks | slots 1–128 | slots 1–255 (see limitations) |
| project file | `project.work` | `project.work` + a `project.256` sidecar |

FLEX slots and the recorder buffers are untouched, and every byte outside the patched sites is
identical to stock.

## How it works

The stock OS keeps its per-slot tables at fixed addresses with a hard bound of 128. Rather than move
those tables, dual-256 adds a **second set** ("SET-B") for slots 129–256 and redirects the per-slot
address arithmetic through a small family of helpers that pick A or B by index.

* **Where SET-B lives.** The flex sample pool's physical base is moved up, which frees a 384 KB
  reserve at `[0x40a955e0, 0x40af55e0)` that the pool never reuses. SET-B's four tables live there:
  SETTINGS-B, STATE-B and the two stride-4 tables. An earlier home inside the heap tail was
  overwritten by the OS at runtime — see [`dual256-setb-pool-clobber`](#) in the project notes.
* **Redirects, not rewrites.** Each per-slot `base + idx*stride` site becomes a 6-byte `jsr` to a
  helper that returns the A or B pointer; each `#128` bound is raised to `#255`/`#256`. An audit pass
  proves no reachable per-slot add can still land out of bounds, and a harness checks all 20 helpers
  across 10 indices on every build.
* **Persistence.** The native `project.work` gains `SLOT=129..256` records (the serializer walks
  A then B), and a sidecar file `project.256` carries the full SET-B records — including the slice
  grids — next to the project.

## Known limitations

* **LOCK TRIG popup stops at 128.** The value list in that popup cannot dial a high slot. Authoring
  works: select the high slot on the track first, then place trigs (they may point at different
  slices). Deferred to a later release.
* **Slot 256 takes no parameter lock.** The lock encoding reserves that value; slots 1–255 are fine.
* **A project saved with high slots needs this firmware.** Stock OS ignores `project.256` and the
  `SLOT=129..256` records, so those slots come back empty — the project still opens.

## Development notes

The interesting part of this patch was not raising the bounds; it was the defects that only appeared
on hardware, each of which needed a probe build to locate. Briefly, in the order they were found:

* **Slices never drew on a high slot**, and loading one raised `-2 SAMPLE LOAD ERRORS!`. The `.ot`
  reader was the last unmigrated per-slot function, and its bail path returned `-2`.
* **Parameter locks refused high slots.** Three write bounds, one of which the original survey had
  missed.
* **A high slot on a track reverted to a low one after RELOAD.** A load-time validator read the slot
  as a *signed* byte, so anything ≥ 128 looked negative and was zeroed. Found with a hardware
  watchpoint via the ColdFire debug module.
* **After a power cycle the high slots came up empty** — and saving from that state wrote an empty
  sidecar, destroying the data. The boot path loads a project through a *different* function than
  RELOAD does, and the sidecar restore was hooked only on the RELOAD one.
* **High slots stayed silent until the AED was opened.** The voice binder needs a generation token to
  match the slot's state; the token is committed mid-load, while the value it copies is still 0, and
  nothing re-commits afterwards. Opening the editor re-ran the chain, which is why that "fixed" it.
* **The AED opened on slot 1 after a load**, cached that waveform and so blocked slice editing. Pure
  ordering: the page is drawn before the slot is published, and 0 renders as `STATIC 001`. Invisible
  on stock, where a track on slot 1 makes 0 accidentally correct.

Every fix ships with an emulator proof (Unicorn) that drives the installed hook on the built image and
checks the stack, the registers and the replicated instructions, so the gate suite catches a
regression without flashing. The probe builds used to find these live in `tools/build_diag_*.py`.

**Two rules learned the hard way**, both worth keeping for future work on this machine:

1. The hardware watchpoint is only safe on *cold* fields. Pointed at a streaming field, its
   level-sensitive interrupt fires continuously, starves the CPU and truncates a CF write — which
   corrupted a bank file and made the OS declare the project corrupt.
2. Probe state must live in the code cave. The obvious scratch block sits inside SET-B, which the
   sidecar restores on every load, so live counters were silently overwritten by the previous
   session's file values.

## Building and flashing

Same flow as the rest of the toolkit — see [`README.md`](README.md) and [`FLASHING.md`](FLASHING.md):

```sh
python3 tools/build_dual256.py       # -> out/mainos_dual256.bin   (the slot extension)
python3 tools/build_persist256.py    # -> out/mainos_persist256.bin (adds project.work persistence)

python3 tools/emu_check.py out/mainos_persist256.bin   # gate: must be ALL GREEN
python3 tools/verify_dual256.py                        # 20 helpers x 10 indices
python3 tools/audit_dual256.py                         # no reachable OOB per-slot add
```

Then wrap the image into a CF `.bin` (`tools/make_bin.py`) and flash with
**PROJECT → OS UPGRADE**. Give every build a unique filename: the Octatrack's clock can run behind,
so verify what you flashed by content, not by timestamp.
