#!/usr/bin/env python3
"""
build_dumpA.py -- read-only diagnostic on top of the PROVEN working dual-256 build.

The STATIC serializer walks the settings table by pointer (`lea a3@(0x448)`, base `lea 0x100d5c59`
= SET+0x129) and reads each slot's PATH from settings[idx] offset 0 -> a slot's sample assignment
lives at SET-A[idx]. SET-A is 128 slots wide [0x100d5b30,0x100f7f30); slot 129 lands at 0x100f8378.
This build = the working dual-256 image (helpers, copy-fill boot, CORE->B, clamps, cap: stable nav to
129), but its sidecar is replaced by a SAVE-ONLY dump of [0x100f7f30, 0x1011a330) (= SET-A[128..255])
to <project>/project.256. NO load hook -> never writes back -> cannot corrupt. After COPY 57 -> PASTE
129 -> SAVE, read project.256[(129-128)*0x448 : +0x448]: if the paste wrote SET-A[129], yok-vox.aif
appears at offset 0.
"""
import pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd

OUT = pathlib.Path("out/mainos_dumpA.bin")
DUMP_LO, DUMP_HI = 0x100f7f30, 0x100f7f30 + 128 * bd.SET_STRIDE   # SET-A[128..255]


def main():
    img = bytearray(bd.SRC.read_bytes())

    # 1) B-family helpers (for CORE STATE/stride4/settings -> B)
    blob, sym = bd.assemble_helpers()
    img[bd.off(bd.HELP_AT):bd.off(bd.HELP_AT) + len(blob)] = blob

    # 2) copy-fill boot (stable B for nav) -- TRACE=False keeps the fill
    bd.TRACE = False
    stub = bd.build_boot_stub()
    img[bd.off(bd.BOOT_STUB):bd.off(bd.BOOT_STUB) + len(stub)] = stub
    o = bd.off(bd.BOOT_HOOK)
    assert bytes(img[o:o + 6]) == b"\x41\xf9\x10\x00\x00\x00", img[o:o + 6].hex()
    img[o:o + 6] = b"\x4e\xf9" + bd.BOOT_STUB.to_bytes(4, "big")

    # 3) SAVE-ONLY sidecar dumping SET-A[128..255]
    bd.SETB_LO, bd.SETB_HI = DUMP_LO, DUMP_HI
    sc, scsym = bd.build_sidecar()
    img[bd.off(bd.SIDECAR_AT):bd.off(bd.SIDECAR_AT) + len(sc)] = sc
    o = bd.off(bd.SAVE_HOOK)
    assert bytes(img[o:o + 6]) == b"\x4a\x8b\x67\x02\x4e\x93", img[o:o + 6].hex()
    img[o:o + 6] = b"\x4e\xf9" + scsym["sidecar_save"].to_bytes(4, "big")
    # deliberately NO load hook -> sidecar_load never runs -> no write-back
    print(f"dump-save: [0x{DUMP_LO:08x},0x{DUMP_HI:08x}) SET-A[128..255] -> project.256 (save-only)")

    # 4) CORE redirects -> B, open clamps, raise list cap (stable navigation to 129)
    nb = nclamp = 0
    for fn, spec in bd.CORE.items():
        for imm_va, hn in spec["sites"]:
            bd.redirect_site(img, imm_va, sym[hn]); nb += 1
        for cva in spec["clamps"]:
            bd.raise_clamp(img, cva); nclamp += 1
    for cap_va, (old, new) in bd.CAPS.items():
        o = bd.off(cap_va); assert bytes(img[o:o + len(old)]) == old, img[o:o+len(old)].hex()
        img[o:o + len(new)] = new
    print(f"working build: {nb} sites -> B, {nclamp} clamps opened, cap raised")

    OUT.write_bytes(bytes(img))
    print(f"\n{OUT}: {len(img):,} bytes  (package -V DUAL256DMP -> OCTATRACK_DMP1.bin)")


if __name__ == "__main__":
    main()
