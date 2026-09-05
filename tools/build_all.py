#!/usr/bin/env python3
"""
build_all.py -- ONE image with every feature this repo has produced.

    maxolydian r10   lazy transitions, no BANK/PTN countdown, PERSONALIZE entries, boot branding
    arp scales       10 extra arpeggiator key-scale qualities
    dual-256         256 STATIC sample slots, with project.256 persistence

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
    0x400d7400 .. 0x400d7788   dual-256 helper family               (unchanged)
    0x400d77c0 / 0x400d7800    load-loop stub / token+AED stubs      (unchanged)
    0x400d7920 ..              arp scales                           (moved from 0x400d7000)

The layout is asserted, not assumed: after the build every maxolydian hunk, the arp blob and the arp
detours are read back out of the finished image and compared byte for byte, so a future stub that
grows into someone else's block fails the build instead of the unit.

    python3 tools/build_all.py            # -> out/mainos_all.bin

Packaging (the release is branded OCTAMAX_2; the ELEK version field holds 10 chars):

    EFT_EMIT_CONTAINER=out/elek_octamax2.bin elektron-firmware-tool \
        -i downloads/extracted/OCTATRACK_OS1.40C.syx -c 3 out/mainos_all.bin \
        -V OCTAMAX_2 -o out/OCTAMAX_2.syx
    python3 tools/make_bin.py out/elek_octamax2.bin -o out/OCTAMAX_2.bin --expect-version OCTAMAX_2

Boot splash and SYSTEM STATUS -> OS VERSION then read OCTAMAX_2 instead of the r10 build's
MAXOLYDIAN, so the combined image is identifiable on the unit.
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
    run_module("build_persist256", {"SRC": STEP_DUAL, "OUT": OUT, "SER_CAVE": SER_CAVE_AT})

    # 5) verify nothing grew into anybody else's block
    print()
    final = OUT.read_bytes()
    for va, end, new in maxo_blocks:
        got = bytes(final[off(va):off(end)])
        assert got == new, (f"maxolydian block 0x{va:08x} was overwritten: "
                            f"{got.hex()[:32]}... != {new.hex()[:32]}...")
    print(f"  verified: all {len(maxo_blocks)} maxolydian hunks intact in the final image")
    got = bytes(final[off(ARP_AT):off(ARP_AT) + len(arp_blob)])
    assert got == arp_blob, "the arp blob was overwritten"
    for site in (0x4009fad2, 0x4009fb74, 0x4003b790):
        assert bytes(final[off(site):off(site) + 2]) == b"\x4e\xf9", f"arp detour 0x{site:08x} lost"
    assert int.from_bytes(final[off(0x400d4096):off(0x400d4096) + 4], "big") == 145, "arp enum count lost"
    print(f"  verified: arp blob ({len(arp_blob)} B) and its 3 detours + enum count intact")

    for f in (STEP_MAXO, STEP_ARP, STEP_DUAL):
        f.unlink(missing_ok=True)
    stock = STOCK.read_bytes()
    changed = sum(1 for a, b in zip(stock, final) if a != b)
    print(f"\n{OUT}: {len(final):,} bytes, {changed:,} changed vs stock")
    print("NEXT: gates ->  python3 tools/emu_check.py out/mainos_all.bin ; "
          "python3 tools/verify_dual256.py ; python3 tools/audit_dual256.py")


if __name__ == "__main__":
    main()
