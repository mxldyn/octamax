```
 ██████╗  ██████╗████████╗ █████╗ ███╗   ███╗ █████╗ ██╗  ██╗
██╔═══██╗██╔════╝╚══██╔══╝██╔══██╗████╗ ████║██╔══██╗╚██╗██╔╝
██║   ██║██║        ██║   ███████║██╔████╔██║███████║ ╚███╔╝
██║   ██║██║        ██║   ██╔══██║██║╚██╔╝██║██╔══██║ ██╔██╗
╚██████╔╝╚██████╗   ██║   ██║  ██║██║ ╚═╝ ██║██║  ██║██╔╝ ██╗
 ╚═════╝  ╚═════╝   ╚═╝   ╚═╝  ╚═╝╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝
    ▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
   ▐░░░░░░░░░░░░  E L E K T R O N   O C T A T R A C K  ░░░░▌
   ▐░░  a firmware study toolkit · for educational use  ░░▌
    ▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀
      READY.
      LOAD "OCTAMAX",8,1
      █
```

# OCTAMAX

**An educational toolkit for understanding how the firmware of the Elektron
Octatrack works.**

OCTAMAX is a reverse-engineering workspace built to *study* the Octatrack MKII
operating system: how the update files are packed, how the code is laid out in
memory, how the microkernel schedules tasks, how the sequencer drives the audio
DSP — and, as a hands-on way of proving that understanding, how a few small,
optional, entirely reversible behavior changes can be added to the OS image.

Everything here is for **educational purposes only**. No Elektron binary is
redistributed. You bring your own copy of the official OS; the tools analyze it
and, if you ask them to, produce a modified image byte-for-byte reproducibly from
that copy.

---

## Motivation

> Hi, I'm **Maxolydian**, an electronic artist based in Palermo, Italy.
>
> For many years Elektron's instruments have been a cornerstone of my live
> performances. A big part of my artistic search is bringing my compositions to
> the stage while always leaving the door open to improvisation. The central
> challenge in that search has always been striking the right balance between
> automation and hands-on control. Too much automation makes things rigid and
> takes away the freedom to step off the script. At the same time, getting
> consistent results — in performance and in sound — demands a setup that is
> reliable and predictable, something a purely hardware rig makes genuinely
> difficult.
>
> On that front Elektron hardware offers exceptional reliability and sound
> quality — qualities recognized the world over, and the reason each of their
> machines has been so successful. And yet the Octatrack is now more than 16
> years old, and while its firmware has been updated several times, the way it
> *works for live performance* hasn't evolved substantially. Elektron's
> developers must surely feel swamped by all the feature requests from their
> users, and it must be hard to decide where to invest the team's precious time
> to deliver the most value.
>
> That's why I started this project: to open up the possibility of experimenting
> with changes and small modifications that make my artistic search easier — and
> at the same time to feed my passion for the hardware and my hunger to learn
> from the best. In other words, **for strictly educational purposes.** I hope it
> proves useful to other artists on a similar search.

---

## ⚠️ Warning — read before doing anything

**This project is strictly for personal use, and I honestly do not recommend
updating the firmware of any Elektron unit with anything other than official
firmware.** It is a risky operation: it puts the product warranty in question and
it can leave the unit unusable.

Nothing in this repository is endorsed by, supported by, or affiliated with
Elektron. If you flash a modified OS you do so entirely at your own risk. The
study of the firmware (static analysis) is harmless; *writing* a non-official OS
to real hardware is not. If in doubt, don't flash — just read, disassemble, and
learn.

---

## What has been investigated

Everything below was verified against the official **OS 1.40C for Octatrack
MKII** — either from the firmware's own checksums, byte-exact decompilation, or
direct disassembly. Full write-ups live in [`ARCHITECTURE.md`](ARCHITECTURE.md)
(consolidated architecture) and [`NOTES.md`](NOTES.md) (chronological log).

### Hardware
- **CPU:** Freescale/NXP **ColdFire** (likely MCF5445x, 32-bit, big-endian,
  ~266 MHz) — a 68000-family core, *not* ARM. The firmware corroborates it: it
  drives the on-chip ATA controller in the MBAR region (`0xFC04_51xx`) that
  characterizes the MCF5445x.
- **Audio DSP:** Freescale **DSP56xxx**, confirmed by the 24-bit word size used
  when the boot loader uploads the DSP program 3 bytes at a time.
- **Storage:** **CompactFlash** (FAT16/32) over the ColdFire's on-chip ATA
  controller, reached through the FlexBus.

### Memory map
Two RAM chips, recovered from a static scan of every real address-operand reference in the
MAIN OS: a **128 MB main DDR** at `0x40000000` and a **separate ~1 MB metadata SRAM** at
`0x10000000` (a different chip-select). Full derivation in [`NOTES.md`](NOTES.md).

| Segment | Range | Size | Use |
|---|---|---|---|
| Metadata SRAM | `0x10000000`–`~0x10100000` | ~1 MB | Sample **settings** tables (0x448 B/slot: flex `0x100b14f0`, static `0x100d5b30`) + project globals. Separate small chip — **reads past its end bus-fault**; full, cannot grow in place. |
| DDR — code + BSS | `0x40000000`–`~0x40200000` | ~2 MB | OS image (`@0x40000400`) + BSS + the free **code cave** (`0x400d64da`–`0x400d7c3b`) the patches live in |
| DDR — bank buffers | `0x400e21e0`–`0x40a955e0` | ~10 MB | 16 resident banks (stride `0x9b340`) |
| DDR — flex pool | `0x40a955e0`–`~0x46000000` | ~85 MB | Flex sample RAM + recorder buffers (the shared 85.5 MB budget) |
| DDR — app structs | `0x46000000`–`~0x46ceb400` | ~13 MB | Recorder metadata, sample **state** tables (0x2c B/slot), streaming tables |
| DDR — reserved | `0x40a955e0`–`0x40af55e0` | 384 KB | Reclaimed by moving the flex pool +64 pages; canary-confirmed untouched — a fixed home for relocated tables |
| DSP shared RAM | `0x80000000`–`~0x80010000` | ~64 KB | Voice state (`0x80004dc8`, stride `0xA8`), double-buffered DSP frames, mailboxes |
| DSP coprocessor | `0x20000000` | — | Command / status / frame-index MMIO |
| Peripherals (MBAR) | `0xFC000000` | — | ColdFire on-chip: DDR controller `0xFC0B8000`, ATA host `0xFC0451xx`, IRQ ctrl `0xFC04C010` |

### Firmware format and update chain
Elektron ships a ZIP with **two transports of the same OS** — a `.bin` and a
`.syx` — both wrapping the same compressed container:

```
.bin  = [ELUP hdr][seed] + XOR-feedback( [len] + ELEK( aPLib( MAIN OS ) ) ) + checksum
.syx  = SysEx 7-bit(              ELEK( aPLib( MAIN OS ) )              )
```

- **ELUP layer** (`.bin` only): XOR obfuscation with feedback plus an additive
  checksum. Reimplemented in `tools/make_bin.py` / `tools/bin_decode.py` and
  validated by regenerating Elektron's own official `.bin` byte-for-byte.
- **ELEK layer:** a proprietary container whose payload is compressed with
  **aPLib**; it decompresses to the **MAIN OS** (1,112,560 bytes, loaded at base
  `0x40000400`).
- **No cryptographic signature** on any layer — the OS is analyzable and, with
  recalculated checksums, rebuildable. That's *why* the format can be repacked at
  all; it is not a security bypass.
- The updater validates the OS (`FUN_4007f748`) with explicit error codes:
  `-2` not a valid OS · `-3` length · `-4` checksum · `-5` MK1 not allowed ·
  `-6` no downgrade.

### Operating system
- A **proprietary preemptive microkernel** (not MQX/ThreadX/VxWorks — banner
  `ElektronOctatrack DPS-1`). Task Control Blocks, per-priority ready queues,
  context switch via `TRAP #0`, blocking message queues, and a time slice driven
  by the ColdFire PIT timer (`0xFC08_0000`).
- The same message-queue pattern unifies the whole firmware: the ATA "async
  queues" and the audio "voice mailboxes" *are* kernel message queues.

### Audio engine and sequencer
- 8 track voices in the `0x80000000` shared-RAM window (base `0x800049d8`,
  stride `0xA8`).
- Control path: a sequencer trig writes a voice mailbox → a control-rate frame
  builder assembles a parameter frame into a **double buffer** → handshake to the
  **DSP56xxx** over MMIO at `0x20000000`, which does the real-time synthesis.
- Work split: **ColdFire = control** (RTOS, sequencer, parameter assembly);
  **DSP = signal** (playback, time-stretch, filters, FX).

### Practical outcome — the optional patches
As a demonstration of the above, OCTAMAX can build an image with a few behavior
changes, **all OFF by default** and toggled from the **PERSONALIZE** menu, so a
freshly flashed unit is indistinguishable from stock until you opt in:

| feature | effect |
|---|---|
| **Lazy transitions** | On a pattern change to a different Part, sounding tracks keep the previous Part's sound (no volume jump). The track LED dims while the track hasn't been re-trigged since the change; a trig commits it to the destination Part. Also keeps the A/B scene pointers on the same slots across the change. |
| **No BANK/PTN countdown** | The SELECT BANK / SELECT PATTERN windows stop expiring after four seconds. |
| **Arp key scales** | The MIDI arpeggiator's key-scale (ARP SETUP, F knob) gains 10 extra qualities beyond the stock major/minor: the five Greek modes (Dorian, Phrygian, Lydian, Mixolydian, Locrian) plus blues, phrygian-dominant, melodic-minor, octatonic and hirajoshi — 12 qualities × 12 roots. `OFF`/`maj`/`min` stay byte-identical to stock, so the extra scales only appear if you scroll the F knob past them. |
| **PERSONALIZE options** | The two behavior switches (lazy transitions, no countdown), added to the PERSONALIZE menu, unchecked by default. |
| **Boot branding** | Boot splash and SYSTEM STATUS show `MAXOLYDIAN` instead of `1.40C`. |

A separate, larger patch raises the **STATIC sample slots from 128 to 256** — high slots load
samples, keep their slices, are assignable to tracks, accept parameter locks, survive a save/reload
and a power cycle, and play immediately. It is built by its own tools and written up in
[`DUAL256.md`](DUAL256.md).

The code changes live in a free code cave and are reached by 6-byte jump detours.
The arp-scales work is written up in [`NOTES.md`](NOTES.md) (search "ARP key-scale");
the behavior patches have a per-hunk table in [`sysex/README.md`](sysex/README.md).

---

## Repository layout

```
ARCHITECTURE.md      consolidated architecture (hardware, OS, memory map)
NOTES.md             chronological reverse-engineering log
FLASHING.md          safe-flashing guide + recovery net (read before flashing)
sysex/               the patch (source + JSON hunks) and the reproducible patcher
tools/               analysis + build scripts (Ghidra headless, emulators, packers)
fetch-os.sh          download + extract the official OS
setup.sh             clone/build elektron-firmware-tool into vendor/
analyze.sh           entropy + binwalk + strings + container unpack -> out/
```

Downloaded Elektron binaries (`downloads/`, `out/`, `vendor/*.bin`, `*.syx`,
`*.bin`, `*.pdf`) are **git-ignored on purpose** — none of them are redistributed.

---

## Building a `.syx` or `.bin` from scratch

You need your own copy of the official OS. The build is fully reproducible: given
the same stock file it emits a `.syx` byte-identical to the reference build.

### 0. Prerequisites

- **Python 3.8+**
- **A cross-assembler for the ColdFire** (only needed to rebuild the stubs from
  source): `m68k-elf-as`, `m68k-elf-ld`, `m68k-elf-objcopy` (targeting
  `-mcpu=5407`).
- **`elektron-firmware-tool`** — cloned and built by `setup.sh` into `vendor/`.
  It's patched locally (see `tools/elektron-firmware-tool.patch`) so it can write
  the full 10-character version field and emit the rebuilt container.

```sh
./fetch-os.sh     # downloads the official OS 1.40C into downloads/ and extracts it
./setup.sh        # clones + patches + builds elektron-firmware-tool into vendor/
```

### 1. The fast path — apply the pre-built patch

The 1,175 bytes of ColdFire code are already assembled and captured, hunk by
hunk, in `sysex/patches/maxolydian-r10.json` (each hunk carries its load address,
the original bytes it expects, and the replacement bytes). To produce a `.syx`:

```sh
python3 sysex/apply_patch.py \
    -i downloads/extracted/OCTATRACK_OS1.40C.syx \
    -o OCTATRACK_MAXOLYDIAN.syx
```

```
[1/5] stock .syx checksum ok
[2/5] extracted section_3_MAIN_OS.bin (1,112,560 bytes)
[3/5] applied 22 hunks (1175 bytes)
[4/5] repacked -> OCTATRACK_MAXOLYDIAN.syx
[5/5] output checksum ok — byte-identical to the reference build
```

The script **aborts before writing anything** if the stock checksum is wrong, if
the original bytes under any hunk don't match (wrong firmware, or already
patched), or if the patched image's checksum is off.

### 2. The full path — rebuild the stubs from source

If you want to change the behavior (or just verify the JSON), rebuild the patched
MAIN OS from the assembly sources. `tools/build.py` assembles every stub
(`tools/patch*.s`), places them in the free code cave, and derives **every**
detour target from the linker's symbol table (never hardcoded — a stale detour
once froze the unit on the logo screen), verifying the original bytes at each
site first:

```sh
python3 tools/build.py            # assembles the stubs -> out/mainos.bin
```

Then wrap `out/mainos.bin` back into a transport with the patched
`elektron-firmware-tool`. Section 3 is the MAIN OS; `-V MAXOLYDIAN` sets the
10-character version field:

```sh
# -> .syx (for MIDI upgrade, or the reference artifact)
vendor/elektron-firmware-tool/elektron-firmware-tool \
    -i downloads/extracted/OCTATRACK_OS1.40C.syx \
    -c 3 out/mainos.bin -V MAXOLYDIAN \
    -o OCTATRACK_MAXOLYDIAN.syx
```

### 3. Making a `.bin` for the CF-card OS UPGRADE

The `.bin` transport (flashed from the CF card via **PROJECT → OS UPGRADE**) is
much faster than trickling the `.syx` over MIDI at 31250 baud. `tools/make_bin.py`
wraps the ELEK container into an ELUP `.bin`. Its correctness is not assumed — it
regenerates Elektron's own official `.bin` byte-for-byte before writing yours:

```sh
# dump the rebuilt ELEK container, then wrap it as an ELUP .bin
EFT_EMIT_CONTAINER=elek.bin vendor/elektron-firmware-tool/elektron-firmware-tool \
    -i downloads/extracted/OCTATRACK_OS1.40C.syx \
    -c 3 out/mainos.bin -V MAXOLYDIAN -o OCTATRACK_MAXOLYDIAN.syx

python3 tools/make_bin.py elek.bin -o OCTATRACK_MAXOLYDIAN.bin
```

### 4. Flashing

**Read [`FLASHING.md`](FLASHING.md) first** — it covers the recovery net in
detail. In short:

- The upgrade goes over **MIDI DIN, not USB** (the `.syx` path), or from the
  **CF card** (the `.bin` path, faster).
- Keep the **official `.syx`** at hand. `[FUNC]` + power on → `[TRIG 3]`
  (MIDI UPGRADE) recovers the unit even if the OS is corrupt — the bootloader is
  never touched by an OS update, which is why a brick here is soft and
  recoverable.
- Never cut power during **`UPDATING FLASH`**.
- Your CF card, projects and samples are not affected by an OS update.
- An OS upgrade **resets the PERSONALIZE settings**, so the unit comes back stock
  (all features off) until you re-enable them.

---

## Legality (not legal advice)

- Static analysis of the publicly distributed OS carries **zero risk to the
  hardware** and is the whole point of this project.
- EU: Directive 2009/24/EC Art. 5 (observe/study/test a program you lawfully use)
  and Art. 6 (decompilation for interoperability). Elektron's EULA may contain
  anti-RE clauses — a contractual matter separate from copyright.
- Private and educational use is low-risk. Redistributing modified binaries is a
  different question; this repo deliberately redistributes **no** Elektron
  binary.

---

*OCTAMAX is an independent, unofficial, educational project. "Elektron" and
"Octatrack" are trademarks of Elektron Music Machines MAV AB, used here only to
identify the hardware under study. Not affiliated with or endorsed by Elektron.*
