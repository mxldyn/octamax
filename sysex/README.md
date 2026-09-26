# sysex/ — building the patched firmware

This folder does **not** contain a firmware image. It contains the patch — the ~1,175
bytes of ColdFire code authored in this repository — plus a script that applies it to
**your own** copy of the official Elektron OS.

No Elektron binary is redistributed here. You download the stock OS yourself; the
script produces a `.syx` byte-identical to the reference build.

## Requirements

- The **official OS 1.40C for Octatrack MKII** (`OCTATRACK_OS1.40C.syx`), from
  elektron.se. `./fetch-os.sh` in the repo root downloads and extracts it.
- **`elektron-firmware-tool`** — `./setup.sh` clones it into `vendor/`, applies
  `tools/elektron-firmware-tool.patch` and builds it.
  Upstream: <https://github.com/mischa85/elektron-firmware-tool>

  The patch is two small local changes, both required to reproduce this build:
  `set_version()` writes the full 10-character ELEK display field from offset `0x08`
  (upstream only writes from `0x0D`, which fits 5 characters), and `EFT_EMIT_CONTAINER`
  dumps the rebuilt container so `tools/make_bin.py` can wrap it.
- Python 3.8+

## Usage

```sh
./fetch-os.sh                      # downloads the official OS into downloads/
./setup.sh                         # builds elektron-firmware-tool into vendor/

# version 2.0 BETA — everything: 256 STATIC slots, slice playhead, behaviour patches
python3 sysex/apply_patch.py \
    -i downloads/extracted/OCTATRACK_OS1.40C.syx \
    -p sysex/patches/octamax-2.0-beta.json \
    -o OCTAMAX_2c.syx --bin OCTAMAX_2c.bin

# version 1.x — the behaviour patches only (this is the default patch)
python3 sysex/apply_patch.py \
    -i downloads/extracted/OCTATRACK_OS1.40C.syx \
    -o OCTATRACK_MAXOLYDIAN.syx
```

```
[1/5] stock .syx checksum ok
[2/5] extracted section_3_MAIN_OS.bin (1,112,560 bytes)
[3/5] applied 223 hunks (4587 bytes)
[4/5] repacked -> OCTAMAX_2c.syx
      CF image  -> OCTAMAX_2c.bin
[5/5] output checksum ok — byte-identical to the reference build
```

`--bin` also writes the CF-card image for **PROJECT → OS UPGRADE**, which is much faster
than flashing over MIDI. Both files come out of the same container, so they carry the
identical firmware.

The script aborts before writing anything if the stock file's checksum is wrong, if the
original bytes under any hunk don't match (wrong firmware, or already patched), or if
the patched image's checksum is off. `--force` relaxes only the outer file checks — the
per-hunk byte verification always holds.

## What the patches change

| patch | size | contents |
|---|---|---|
| `patches/octamax-2.0-beta.json` | 5,497 B in 227 hunks (0.49%) | everything below **plus the 256 STATIC slots, the slice playhead view and persistent PERSONALIZE toggles** |
| `patches/maxolydian-r10.json` | 1,175 B in 22 hunks (0.11%) | the behaviour patches only |

| id | source | effect |
|---|---|---|
| `static-slots-256` | `tools/build_dual256.py` + `tools/build_persist256.py` | *(2.0 only)* STATIC sample slots 128 → 256, with slices, track assignment, parameter locks and persistence across a power cycle. See [`../DUAL256.md`](../DUAL256.md). |
| `arp-key-scales` | `tools/patch_arp.s` | *(2.0 only)* 10 extra arpeggiator key-scale qualities beyond major/minor. |
| `midi-mode-guard` | `tools/patch_sliceview.s`, `patch_led.s` | *(2.0 only)* The slice playhead hooks and the lazy-transitions LED dimmer stand down in MIDI mode (the view index is shared with the MIDI pages). Fixes the widget over the MIDI arp page, dimmed T1-T8 LEDs on MIDI tracks and an exception on [PAGE] there. |
| `lazy-transitions` | `tools/patch.s`, `patch_enc.s`, `patch_led.s`, `patch_scene2.s` | Sounding tracks keep the previous Part's definition on a pattern change (track LED dimmed) until a trig, a manual trig or an encoder move; A/B scene pointers stay on the same slots. |
| `no-bank-ptn-countdown` | `tools/patch_notimer.s` | SELECT BANK / SELECT PATTERN windows stop expiring. |
| `personalize-options` | `tools/patch_notimer.s` | Both of the above are PERSONALIZE entries, **unchecked by default**, so an unconfigured unit behaves exactly like stock. |
| `boot-branding` | ELEK header (`-V`) | Boot splash and SYSTEM STATUS show `MAXOLYDIAN` instead of `1.40C`. |

The code patches live in a free code cave at `0x400d64e0`–`0x400d697c`, reached by
detours at `0x40009094` (part apply), `0x40052e98` (encoder editor), `0x4003f1b4`
(crossfader), `0x40083fb4` (track LED painter) and `0x40034b5e` (trig painter). Design,
addresses and reverse-engineering notes are in [`../NOTES.md`](../NOTES.md) and
[`../ARCHITECTURE.md`](../ARCHITECTURE.md).

`patches/maxolydian-r10.json` holds each hunk with its load address, the original bytes
and the replacement bytes, so the change is auditable without running anything.

> Only the current revision is published. Earlier ones carried a GUI-in-transition patch
> that crashed the unit; it is gone — the current spec wants an encoder move to *end* the
> transition, the opposite of what that patch did. See `../NOTES.md`.

## Flashing from the CF card

`tools/make_bin.py` wraps the container into an ELUP `.bin` for the OS UPGRADE menu, which
is much faster than MIDI. Its correctness is not assumed: it regenerates Elektron's own
official `.bin` byte-for-byte from that file's container.

```sh
EFT_EMIT_CONTAINER=elek.bin elektron-firmware-tool -i stock.syx -c 3 out/mainos.bin \
    -V MAXOLYDIAN -o out.syx
python3 tools/make_bin.py elek.bin -o OCTATRACK_MAXOLYDIAN.bin
```

## Before you flash

Read [`../FLASHING.md`](../FLASHING.md) first. Short version:

- The upgrade goes over **MIDI DIN, not USB**.
- Keep the **official `.syx`** at hand — `[FUNC]` + power on → `[TRIG 3]` (MIDI UPGRADE)
  recovers the unit even if the OS is corrupt, because the bootloader is not touched.
- Never cut power during `UPDATING FLASH`.
- Your CF card, projects and samples are not affected.

## Disclaimer

This is unofficial, modified firmware, built for personal study of hardware its author
owns. It is not endorsed by or supported by Elektron, and it will not be supported by
them. Validated in a ColdFire emulator and on one MKII unit. **Use at your own risk.**
