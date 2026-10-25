#!/usr/bin/env python3
"""
build_all.py -- ONE image with every feature this repo has produced.

    maxolydian r10   lazy transitions, no BANK/PTN countdown, PERSONALIZE entries, boot branding
    arp scales       10 extra arpeggiator key-scale qualities
    dual-256         256 STATIC sample slots, with project.256 persistence
    slice playhead   big blinking slice number + progress bar in the SRC>SLICES view
    bank auto ptn 1  a bank pick in SELECT BANK also picks its pattern 1 (PERSONALIZE toggle)

Each of the three was developed against the SAME free code cave, so their stubs overlap. Nothing about
the code conflicts -- the 16 maxolydian detour sites, the 3 arp sites and the 233 dual-256 byte-runs
are pairwise disjoint -- only the cave addresses do. This build keeps the published maxolydian layout
fixed (its hunks are a released, checksummed patch) and relocates the other two around it:

    0x400d64e0 .. 0x400d6ae8   maxolydian r10, six blocks           (fixed, from the JSON)
    0x400d6b00 .. 0x400d6b9e   dual-256 gap stubs                   (unchanged)
    0x400d6ba0 ..              dual-256 boot init                   (moved from 0x400d64e0)
    0x400d6c00 .. 0x400d6f9e   dual-256 sidecar                     (moved from 0x400d6600)
    0x400d7000 .. 0x400d702a   dual-256 allocator stub              (unchanged)
    0x400d7080 ..              serializer 256-extension             (moved from 0x400d6a00)
    0x400d70a8 .. 0x400d73f6   slice playhead                       (build_sliceview.py)
    0x400d7400 .. 0x400d7788   dual-256 helper family               (unchanged)
    0x400d77c0 / 0x400d7800    load-loop stub / token+AED stubs      (unchanged)
    0x400d7920 ..              arp scales                           (moved from 0x400d7000)

The layout is asserted, not assumed: after the build every maxolydian hunk, the arp blob and the arp
detours are read back out of the finished image and compared byte for byte, so a future stub that
grows into someone else's block fails the build instead of the unit.

    python3 tools/build_all.py            # -> out/mainos_all.bin

Packaging (the release is branded OCTAMAX_2d; the ELEK version field holds 10 chars):

    EFT_EMIT_CONTAINER=out/elek_octamax2d.bin vendor/elektron-firmware-tool/elektron-firmware-tool \
        -i downloads/extracted/OCTATRACK_OS1.40C.syx -c 3 out/mainos_all.bin \
        -V OCTAMAX_2d -o out/OCTAMAX_2d.syx
    python3 tools/make_bin.py out/elek_octamax2d.bin -o out/OCTAMAX_2d.bin --expect-version OCTAMAX_2d
    python3 tools/make_patch_json.py --img out/mainos_all.bin --syx out/OCTAMAX_2d.syx \
        --patch sysex/patches/octamax-2.0-beta.json

Boot splash and SYSTEM STATUS -> OS VERSION then read OCTAMAX_2d instead of the r10 build's
MAXOLYDIAN, so the combined image is identifiable on the unit.

Gates after a build: emu_check, verify_dual256, audit_dual256 --img out/mainos_all.bin,
emu_sliceview out/mainos_all.bin, emu_led, emu_autoptn out/mainos_all.bin.
"""
import json, pathlib, subprocess, sys

sys.path.insert(0, "tools")

BASE = 0x40000400
STOCK = pathlib.Path("out/stock_mainos.bin")
R10 = pathlib.Path("sysex/patches/maxolydian-r10.json")
OUT = pathlib.Path("out/mainos_all.bin")

STEP_MAXO = pathlib.Path("out/_all_maxo.bin")      # stock + maxolydian
STEP_ARP = pathlib.Path("out/_all_arp.bin")        # + arp scales
STEP_DUAL = pathlib.Path("out/_all_dual.bin")      # + dual-256
STEP_PERS = pathlib.Path("out/_all_pers.bin")      # + 256 persistence
STEP_SV = pathlib.Path("out/_all_sv.bin")          # + slice playhead

# --- relocations (see the map above) ---
BOOT_STUB_AT = 0x400d6ba0
SIDECAR_AT = 0x400d6c00
SIDECAR_LIMIT = 0x400d7000
SER_CAVE_AT = 0x400d7080
ARP_AT = 0x400d7920
ARP_LIMIT = 0x400d7c3c        # stock data resumes here


def off(va):
    return va - BASE


def apply_maxolydian(img):
    """Apply the published r10 hunks, verifying each original byte string first."""
    j = json.loads(R10.read_text())
    blocks = []
    for h in j["hunks"]:
        va, orig, new = int(h["addr"], 16), bytes.fromhex(h["orig"]), bytes.fromhex(h["new"])
        o = off(va)
        assert bytes(img[o:o + len(orig)]) == orig, (
            f"maxolydian hunk 0x{va:08x}: base is {bytes(img[o:o+len(orig)]).hex()}, expected {h['orig']}")
        img[o:o + len(new)] = new
        blocks.append((va, va + len(new), new))
    print(f"maxolydian r10: {len(j['hunks'])} hunks, "
          f"features {', '.join(c['id'] for c in j['changes'])}")
    return blocks


LED_AT, LED_LIMIT = 0x400d6800, 0x400d6900   # r10 block: patch_led, up to patch_notimer


def rebuild_led_stub(img, maxo_blocks):
    """led_stub ships inside the released r10 hunks, but its source gained a MIDI-mode gate
    (MIDI tracks never take part in a Part transition, so their T1..T8 LEDs must stay at the
    stock level). Reassemble it from tools/patch_led.s over the r10 bytes and swap the block's
    expectation so the byte-for-byte verification checks the new stub instead."""
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", "out/patch_led.o", "tools/patch_led.s"], check=True)
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{LED_AT:x}", "-o", "out/patch_led.elf", "out/patch_led.o"],
                   capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/patch_led.elf", "out/patch_led.bin"], check=True)
    blob = pathlib.Path("out/patch_led.bin").read_bytes()
    assert LED_AT + len(blob) <= LED_LIMIT, f"led_stub {len(blob)} B overruns 0x{LED_LIMIT:08x}"
    idx = [i for i, (va, _, _) in enumerate(maxo_blocks) if va == LED_AT]
    assert len(idx) == 1, "r10 JSON has no hunk at the led_stub address"
    va, end, old = maxo_blocks[idx[0]]
    assert bytes(img[off(va):off(end)]) == old, "led_stub block is not the r10 bytes"
    assert not any(img[off(end):off(LED_LIMIT)]), "bytes after the r10 led_stub are not free"
    img[off(LED_AT):off(LED_AT) + len(blob)] = blob
    assert int.from_bytes(img[off(0x40083fb4) + 2:off(0x40083fb4) + 6], "big") == LED_AT, "led detour lost"
    maxo_blocks[idx[0]] = (LED_AT, LED_AT + len(blob), blob)
    print(f"led_stub rebuilt from source: {len(blob)} B @ 0x{LED_AT:08x} (r10 had {len(old)} B), MIDI-mode gate")


def run_module(modname, overrides):
    """Import a builder, override its module-level constants, run its main()."""
    mod = __import__(modname)
    for k, v in overrides.items():
        assert hasattr(mod, k), f"{modname} has no attribute {k}"
        setattr(mod, k, v)
    mod.main()
    return mod


def main():
    if not STOCK.exists():
        sys.exit(f"missing {STOCK} — run ./fetch-os.sh and ./analyze.sh first")
    img = bytearray(STOCK.read_bytes())

    # 1) the published behaviour patch, at its released addresses
    maxo_blocks = apply_maxolydian(img)
    rebuild_led_stub(img, maxo_blocks)
    STEP_MAXO.write_bytes(bytes(img))

    # 2) arp scales, relocated out of the dual-256 allocator stub's cave
    print()
    import build_arp
    arp = run_module("build_arp", {"STOCK": STEP_MAXO, "OUT": STEP_ARP, "ARP_AT": ARP_AT})
    arp_blob = pathlib.Path("out/patch_arp.bin").read_bytes()
    assert ARP_AT + len(arp_blob) <= ARP_LIMIT, (
        f"arp blob {len(arp_blob)} B ends 0x{ARP_AT + len(arp_blob):08x} past 0x{ARP_LIMIT:08x}")

    # 3) dual-256, with its boot stub and sidecar moved clear of the maxolydian blocks
    print()
    run_module("build_dual256", {
        "SRC": STEP_ARP, "OUT": STEP_DUAL,
        "BOOT_STUB": BOOT_STUB_AT, "SIDECAR_AT": SIDECAR_AT, "SIDECAR_LIMIT": SIDECAR_LIMIT,
    })

    # 4) the 256-slot persistence half, with the serializer extension moved as well
    print()
    run_module("build_persist256", {"SRC": STEP_DUAL, "OUT": STEP_PERS, "SER_CAVE": SER_CAVE_AT})

    # 5) the SLICE PLAYHEAD view (needs the maxolydian PERSONALIZE arrays already in place)
    print()
    sv = run_module("build_sliceview", {"SRC": STEP_PERS, "OUT": STEP_SV})
    sv_blob = pathlib.Path("out/patch_sliceview.bin").read_bytes()

    # 6) BANK AUTO PTN 1 (claims the 20th, last PERSONALIZE entry; cave after the arp blob)
    print()
    ap = run_module("build_autoptn", {"SRC": STEP_SV, "OUT": OUT})
    ap_blob = pathlib.Path("out/patch_autoptn.bin").read_bytes()
    assert ARP_AT + len(arp_blob) <= ap.CAVE, "the arp blob runs into the autoptn cave"

    # 7) verify nothing grew into anybody else's block
    print()
    final = OUT.read_bytes()
    for va, end, new in maxo_blocks:
        got = bytes(final[off(va):off(end)])
        # sliceview and autoptn legitimately write inside two r10 hunks (the appended
        # PERSONALIZE entries and the item-count immediate); fold their recorded writes, in
        # build order, into the expectation
        new = bytearray(new)
        for wa, wb in sv.APPLIED + ap.APPLIED:
            for i, b in enumerate(wb):
                if va <= wa + i < end:
                    new[wa + i - va] = b
        new = bytes(new)
        assert got == new, (f"maxolydian block 0x{va:08x} was overwritten: "
                            f"{got.hex()[:32]}... != {new.hex()[:32]}...")
    print(f"  verified: all {len(maxo_blocks)} maxolydian hunks intact in the final image")
    got = bytes(final[off(ARP_AT):off(ARP_AT) + len(arp_blob)])
    assert got == arp_blob, "the arp blob was overwritten"
    for site in (0x4009fad2, 0x4009fb74, 0x4003b790):
        assert bytes(final[off(site):off(site) + 2]) == b"\x4e\xf9", f"arp detour 0x{site:08x} lost"
    assert int.from_bytes(final[off(0x400d4096):off(0x400d4096) + 4], "big") == 145, "arp enum count lost"
    print(f"  verified: arp blob ({len(arp_blob)} B) and its 3 detours + enum count intact")
    import build_sliceview as sv
    got = bytes(final[off(sv.CAVE):off(sv.CAVE) + len(sv_blob)])
    assert got == sv_blob, "the sliceview blob was overwritten"
    for site, _, _ in sv.DETOURS:
        assert bytes(final[off(site):off(site) + 2]) == b"\x4e\xf9", f"sliceview detour 0x{site:08x} lost"
    print(f"  verified: sliceview blob ({len(sv_blob)} B) and its {len(sv.DETOURS)} detours intact")
    import build_autoptn as ap
    got = bytes(final[off(ap.CAVE):off(ap.CAVE) + len(ap_blob)])
    assert got == ap_blob, "the autoptn blob was overwritten"
    for site, _, _ in ap.DETOURS:
        assert bytes(final[off(site):off(site) + 2]) == b"\x4e\xf9", f"autoptn detour 0x{site:08x} lost"
    assert bytes(final[off(ap.COUNT_SITE):off(ap.COUNT_SITE) + 4]) == b"\x72\x14\x4e\x71", "menu count lost"
    for table in (ap.MENU_LBL, ap.MENU_GET, ap.MENU_SET):
        for idx in range(16, 20):
            assert any(final[off(table + idx * 4):off(table + idx * 4) + 4]), f"menu entry {idx} empty"
    print(f"  verified: autoptn blob ({len(ap_blob)} B), its detour, the menu count (20) and entries 17-20")

    for f in (STEP_MAXO, STEP_ARP, STEP_DUAL, STEP_PERS, STEP_SV):
        f.unlink(missing_ok=True)
    stock = STOCK.read_bytes()
    changed = sum(1 for a, b in zip(stock, final) if a != b)
    print(f"\n{OUT}: {len(final):,} bytes, {changed:,} changed vs stock")
    print("NEXT: gates ->  python3 tools/emu_check.py out/mainos_all.bin ; "
          "python3 tools/verify_dual256.py ; python3 tools/audit_dual256.py --img out/mainos_all.bin ; "
          "python3 tools/emu_sliceview.py out/mainos_all.bin ; python3 tools/emu_led.py ; "
          "python3 tools/emu_autoptn.py out/mainos_all.bin")


if __name__ == "__main__":
    main()
