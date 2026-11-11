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
    0x400d6996 .. 0x400d6a00   ptnrestart .ra (rs_pick)             (build_ptnrestart.py)
    0x400d7000 .. 0x400d702a   dual-256 allocator stub              (unchanged)
    0x400d702a .. 0x400d7080   ptnrestart .rb (rs_same, rs_take)    (build_ptnrestart.py)
    0x400d7080 ..              serializer 256-extension             (moved from 0x400d6a00)
    0x400d70a8 .. 0x400d73f6   slice playhead                       (build_sliceview.py)
    0x400d7400 .. 0x400d7788   dual-256 helper family               (unchanged)
    0x400d7788 .. 0x400d77c0   ptnrestart .rd (rs_pend, RS_FLAG)    (build_ptnrestart.py)
    0x400d77c0 / 0x400d7800    load-loop stub / token+AED stubs      (unchanged)
    0x400d7920 ..              arp scales                           (moved from 0x400d7000)
    0x400d7be6 .. 0x400d7c3c   ptnrestart .rc (rs_entry, rs_led)    (build_ptnrestart.py)

The layout is asserted, not assumed: after the build every maxolydian hunk, the arp blob and the arp
detours are read back out of the finished image and compared byte for byte, so a future stub that
grows into someone else's block fails the build instead of the unit.

    python3 tools/build_all.py            # -> out/mainos_all.bin

Packaging (the release is branded OCTAMAX_2i; the ELEK version field holds 10 chars):

    EFT_EMIT_CONTAINER=out/elek_octamax2i.bin vendor/elektron-firmware-tool/elektron-firmware-tool \
        -i downloads/extracted/OCTATRACK_OS1.40C.syx -c 3 out/mainos_all.bin \
        -V OCTAMAX_2i -o out/OCTAMAX_2i.syx
    python3 tools/make_bin.py out/elek_octamax2i.bin -o out/OCTAMAX_2i.bin --expect-version OCTAMAX_2i
    python3 tools/make_patch_json.py --img out/mainos_all.bin --syx out/OCTAMAX_2i.syx \
        --patch sysex/patches/octamax-2.0-beta.json

Boot splash and SYSTEM STATUS -> OS VERSION then read OCTAMAX_2i instead of the r10 build's
MAXOLYDIAN, so the combined image is identifiable on the unit.

Gates after a build: emu_check, verify_dual256, audit_dual256 --img out/mainos_all.bin,
emu_sliceview out/mainos_all.bin, emu_led, emu_autoptn out/mainos_all.bin,
emu_aedkey out/mainos_all.bin, emu_ptnrestart out/mainos_all.bin, emu_scene2, emu_image out/mainos_all.bin,
emu_lazy out/mainos_all.bin.
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
STEP_AP = pathlib.Path("out/_all_ap.bin")          # + bank auto ptn 1
STEP_AK = pathlib.Path("out/_all_ak.bin")          # + AED key fix

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


LED_AT, LED_LIMIT = 0x400d6800, 0x400d6860   # r10 block: patch_led; aedkey owns 0x400d6860..0x400d6900

# The LAZY TRANSITIONS blocks ship inside the released r10 hunks but are reassembled from source:
# their RAM moved out of the stock analysis-task buffer (tools/patch_ram.inc, OCTAMAX_2h) and
# led_stub gained a MIDI-mode gate. (source, address, limit, a detour that must point at it)
R10_SOURCES = [
    ("patch",        0x400d64e0, 0x400d6600, None),
    ("patch_scene2", 0x400d6700, 0x400d6800, 0x40009094),   # before enc/led: it hosts lz_dirty
    ("patch_enc",    0x400d6600, 0x400d6700, None),
    ("patch_led",    LED_AT,     LED_LIMIT,  0x40083fb4),
]
# Entry points the released r10 detours jump to: a rebuilt block must keep each one in place.
R10_ENTRIES = {
    "patch": {"save_stub": 0x400d64e0, "restore_stub": 0x400d6542},
    "patch_scene2": {"scene_stub": 0x400d6700, "xf_stub": 0x400d6712},
    "patch_enc": {"enc_e98": 0x400d6600, "enc_ae8": 0x400d6612, "enc_498": 0x400d6624,
                  "enc_a68": 0x400d6636, "enc_35c": 0x400d6648},
    "patch_led": {"led_stub": 0x400d6800},
}
OLD_RAM = (0x80006964, 0x80007574)   # the analysis task's buffer: no patch may reference it


def assemble_at(name, at, defsyms=None):
    defs = [f"--defsym={k}=0x{v:x}" for k, v in (defsyms or {}).items()]
    subprocess.run(["m68k-elf-as", "-mcpu=5407", *defs, "-o", f"out/{name}.o", f"tools/{name}.s"],
                   check=True)
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{at:x}", "-o", f"out/{name}.elf", f"out/{name}.o"],
                   capture_output=True, check=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "-j", ".text", f"out/{name}.elf",
                    f"out/{name}.bin"], check=True)
    nm = subprocess.run(["m68k-elf-nm", f"out/{name}.elf"], capture_output=True, text=True).stdout
    syms = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    return pathlib.Path(f"out/{name}.bin").read_bytes(), syms


def rebuild_r10_blocks(img, maxo_blocks):
    """Reassemble the r10 LAZY blocks over the released bytes and swap each block's expectation,
    so the byte-for-byte verification checks the rebuilt code instead."""
    defsyms = {}
    for name, at, limit, detour in R10_SOURCES:
        blob, syms = assemble_at(name, at, defsyms)
        if "lz_dirty" in syms:
            defsyms["LZ_DIRTY"] = syms["lz_dirty"]
        for sym, want in R10_ENTRIES[name].items():
            assert syms.get(sym) == want, f"{name}: {sym} moved to {syms.get(sym)} (r10 detour wants 0x{want:08x})"
        assert at + len(blob) <= limit, f"{name} {len(blob)} B overruns 0x{limit:08x}"
        idx = [i for i, (va, _, _) in enumerate(maxo_blocks) if va == at]
        assert len(idx) == 1, f"r10 JSON has no hunk at 0x{at:08x} ({name})"
        va, end, old = maxo_blocks[idx[0]]
        assert bytes(img[off(va):off(end)]) == old, f"{name} block is not the r10 bytes"
        assert not any(img[off(end):off(limit)]), f"bytes after the r10 {name} block are not free"
        top = max(end, at + len(blob))
        img[off(va):off(top)] = blob.ljust(top - va, b"\0")
        if detour is not None:
            assert int.from_bytes(img[off(detour) + 2:off(detour) + 6], "big") == at, f"{name} detour lost"
        maxo_blocks[idx[0]] = (va, va + len(blob), blob)
        same = "identical" if blob == old else f"changed ({len(old)} -> {len(blob)} B, limit {limit - at})"
        print(f"  r10 {name:13s} rebuilt from source @ 0x{at:08x}: {same}")
    # apply_part's exit: the jmp at 0x40009664 must land on restore_stub
    assert int.from_bytes(img[off(0x40009666):off(0x4000966a)], "big") == 0x400d6542, "exit detour lost"


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
    rebuild_r10_blocks(img, maxo_blocks)
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
    ap = run_module("build_autoptn", {"SRC": STEP_SV, "OUT": STEP_AP})
    ap_blob = pathlib.Path("out/patch_autoptn.bin").read_bytes()
    assert ARP_AT + len(arp_blob) <= ap.CAVE, "the arp blob runs into the autoptn cave"

    # 7) the AED key publishes the current track's slot before opening (track copy -> stale editor)
    print()
    ak = run_module("build_aedkey", {"SRC": STEP_AP, "OUT": STEP_AK})
    ak_blob = pathlib.Path("out/patch_aedkey.bin").read_bytes()
    assert LED_LIMIT <= ak.CAVE, "led_stub's limit runs into the aedkey cave"

    # 8) [PTN] + the playing pattern cues a restart (four small holes of the main cave)
    print()
    rs = run_module("build_ptnrestart", {"SRC": STEP_AK, "OUT": OUT})
    rs_blobs = {s: pathlib.Path(f"out/patch_ptnrestart{s.replace('.', '_')}.bin").read_bytes()
                for s in rs.SECTIONS}

    # 9) verify nothing grew into anybody else's block
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
    got = bytes(final[off(ak.CAVE):off(ak.CAVE) + len(ak_blob)])
    assert got == ak_blob, "the aedkey blob was overwritten"
    for site, sym, _, _ in ak.DETOURS:
        op = b"\x4e\xb9" if sym in ak.CALLS else b"\x4e\xf9"
        assert bytes(final[off(site):off(site) + 2]) == op, f"aedkey detour 0x{site:08x} lost"
    print(f"  verified: aedkey blob ({len(ak_blob)} B) and its {len(ak.DETOURS)} detours intact")
    for sec, (lo, _) in rs.SECTIONS.items():
        blob = rs_blobs[sec]
        assert bytes(final[off(lo):off(lo) + len(blob)]) == blob, f"ptnrestart block {sec} was overwritten"
    for site, _, _, _, op in rs.DETOURS:
        assert bytes(final[off(site):off(site) + 2]) == op, f"ptnrestart detour 0x{site:08x} lost"
    print(f"  verified: ptnrestart blocks ({sum(map(len, rs_blobs.values()))} B in {len(rs_blobs)}) "
          f"and its {len(rs.DETOURS)} detours intact")

    stock = STOCK.read_bytes()
    clash = [i + BASE for i in range(0, len(final) - 3, 2)
             if final[i:i + 4] != stock[i:i + 4]
             and OLD_RAM[0] <= int.from_bytes(final[i:i + 4], "big") < OLD_RAM[1]]
    assert not clash, f"patch code still references the analysis buffer: {[hex(c) for c in clash]}"
    print(f"  verified: no patch operand points into 0x{OLD_RAM[0]:08x}..0x{OLD_RAM[1]:08x}")

    for f in (STEP_MAXO, STEP_ARP, STEP_DUAL, STEP_PERS, STEP_SV, STEP_AP, STEP_AK):
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
