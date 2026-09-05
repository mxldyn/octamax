#!/usr/bin/env python3
"""
build_trace_acc.py -- NON-DESTRUCTIVE accessor-logging diagnostic build.

The slot PASTE writes SETTINGS-A[129] (0x100f8378) via DIRECT STORES through an un-migrated
settings accessor (proven: memcpy trace TOTAL=186 / settings-touching=0; SET-B dump all zero).
This build reroutes EVERY `addi/adda #0x100d5b30,reg` settings base-add (all 31 sites, CORE and
non-CORE) to a per-register LOGGING helper that, when idx in [128,256), records [caller_PC][product]
into a ring at TRACE_CAP and then does the STOCK add (returns SETTINGS-A -- exactly what the paste
already does, so RAM behavior is unchanged, zero risk). STATE / stride4 stay redirected to B (safe,
as in the working build) so the paste's non-settings writes never hit the OS working region.

Boot is zero-init (ring starts empty). Clamps opened + list cap raised so slot 129 is reachable.
Sidecar dumps SETTINGS-B (incl. the ring) to <project>/project.256. After COPY 57 -> PASTE 129 ->
SAVE, read project.256[0:528]: the entry whose caller_PC lands in the paste path is the exact
accessor to migrate.

    python3 tools/build_trace_acc.py    # -> out/mainos_trace_acc.bin
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd

OUT = pathlib.Path("out/mainos_trace_acc.bin")
LOG_AT = bd.TRACE_STUB          # 0x400d6900 cave (unused when the memcpy hook is off)
SET_A = 0x100d5b30
LO, HI = 0x22400, 0x44800       # 128*0x448 , 256*0x448  (product bounds)
CAP = bd.TRACE_CAP              # 0x47701a00  ring: [count][.. entries [PC][product] 8B ..]

DATA_REGS = ["d0", "d1", "d2", "d3"]
ADDR_REGS = ["a1", "a2", "a3", "a4"]


def collect_set_sites():
    """every addi.l #SET,dN / adda.l #SET,aN in the image -> (va_of_instr, reg)."""
    img = bd.SRC.read_bytes()
    tgt = SET_A.to_bytes(4, "big")
    AREG = {0xd1: "a0", 0xd3: "a1", 0xd5: "a2", 0xd7: "a3", 0xd9: "a4", 0xdb: "a5", 0xdd: "a6"}
    DREG = {0x80: "d0", 0x81: "d1", 0x82: "d2", 0x83: "d3", 0x84: "d4", 0x85: "d5", 0x86: "d6"}
    sites = []
    i = 0
    while True:
        k = img.find(tgt, i)
        if k < 0:
            break
        b0, b1 = img[k - 2], img[k - 1]
        if b0 == 0x06 and b1 in DREG:          # (imm addr = k; redirect_site subtracts 2)
            sites.append((bd.BASE + k, DREG[b1]))
        elif b1 == 0xfc and b0 in AREG:
            sites.append((bd.BASE + k, AREG[b0]))
        i = k + 1
    return sites


def build_loggers():
    """assemble one logging helper per register used by the SET add-sites."""
    def dfn(r):
        return f"""h_lset_{r}:
    cmpi.l  #0x{LO:x},%{r}
    blo.b   9f
    cmpi.l  #0x{HI:x},%{r}
    bhs.b   9f
    move.l  %d7,-(%sp)
    move.l  %a0,-(%sp)
    movea.l #0x{CAP:x},%a0
    move.l  (%a0),%d7
    addq.l  #1,%d7
    move.l  %d7,(%a0)
    subq.l  #1,%d7
    andi.l  #63,%d7
    lsl.l   #3,%d7
    lea     16(%a0),%a0
    adda.l  %d7,%a0
    move.l  %sp@(8),(%a0)+
    move.l  %{r},(%a0)
    move.l  %sp@+,%a0
    move.l  %sp@+,%d7
9:  addi.l  #0x{SET_A:x},%{r}
    rts
"""
    def afn(r):
        return f"""h_lset_{r}:
    cmpa.l  #0x{LO:x},%{r}
    blo.b   9f
    cmpa.l  #0x{HI:x},%{r}
    bhs.b   9f
    move.l  %d7,-(%sp)
    move.l  %a0,-(%sp)
    movea.l #0x{CAP:x},%a0
    move.l  (%a0),%d7
    addq.l  #1,%d7
    move.l  %d7,(%a0)
    subq.l  #1,%d7
    andi.l  #63,%d7
    lsl.l   #3,%d7
    lea     16(%a0),%a0
    adda.l  %d7,%a0
    move.l  %sp@(8),(%a0)+
    move.l  %{r},(%a0)
    move.l  %sp@+,%a0
    move.l  %sp@+,%d7
9:  adda.l  #0x{SET_A:x},%{r}
    rts
"""
    asm = "    .cpu 5407\n    .text\n" + "".join(dfn(r) for r in DATA_REGS) + "".join(afn(r) for r in ADDR_REGS)
    p = "out/_lg"
    pathlib.Path(p + ".s").write_text(asm)
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", p + ".o", p + ".s"], check=True)
    subprocess.run(["m68k-elf-ld", "-Ttext=0x%x" % LOG_AT, "-o", p + ".elf", p + ".o"], capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", p + ".elf", p + ".bin"], check=True)
    nm = subprocess.run(["m68k-elf-nm", p + ".elf"], capture_output=True, text=True).stdout
    sym = {q[2]: int(q[0], 16) for q in (l.split() for l in nm.splitlines()) if len(q) == 3}
    blob = pathlib.Path(p + ".bin").read_bytes()
    for f in (".s", ".o", ".elf", ".bin"):
        pathlib.Path(p + f).unlink(missing_ok=True)
    return blob, sym


def main():
    img = bytearray(bd.SRC.read_bytes())

    # 1) B-family helpers (STATE/stride4 CORE redirects stay -> B, safe)
    blob, sym = bd.assemble_helpers()
    img[bd.off(bd.HELP_AT):bd.off(bd.HELP_AT) + len(blob)] = blob

    # 2) logging helpers in the (memcpy-trace) cave
    lg, lsym = build_loggers()
    assert not any(img[bd.off(LOG_AT):bd.off(LOG_AT) + len(lg)]), "logger cave not empty"
    img[bd.off(LOG_AT):bd.off(LOG_AT) + len(lg)] = lg
    print(f"loggers: {len(lg)} B @0x{LOG_AT:08x}  ({', '.join('h_lset_'+r for r in DATA_REGS+ADDR_REGS)})")

    # 3) zero-init boot (ring at CAP starts empty) -- reuse build_dual256's TRACE-mode stub
    bd.TRACE = True
    stub = bd.build_boot_stub()
    img[bd.off(bd.BOOT_STUB):bd.off(bd.BOOT_STUB) + len(stub)] = stub
    o = bd.off(bd.BOOT_HOOK)
    assert bytes(img[o:o + 6]) == b"\x41\xf9\x10\x00\x00\x00", img[o:o + 6].hex()
    img[o:o + 6] = b"\x4e\xf9" + bd.BOOT_STUB.to_bytes(4, "big")
    print(f"boot-init(zero): {len(stub)} B @0x{bd.BOOT_STUB:08x}; zero [0x{bd.HOLE_LO:08x},0x{bd.HOLE_HI:08x})")

    # 4) sidecar (dump SETTINGS-B incl. ring -> project.256)
    sc, scsym = bd.build_sidecar()
    img[bd.off(bd.SIDECAR_AT):bd.off(bd.SIDECAR_AT) + len(sc)] = sc
    o = bd.off(bd.SAVE_HOOK); assert bytes(img[o:o + 6]) == b"\x4a\x8b\x67\x02\x4e\x93", img[o:o + 6].hex()
    img[o:o + 6] = b"\x4e\xf9" + scsym["sidecar_save"].to_bytes(4, "big")
    o = bd.off(bd.LOAD_HOOK); assert bytes(img[o:o + 6]) == b"\x4c\xee\x1c\x7c\xfd\xc0", img[o:o + 6].hex()
    img[o:o + 6] = b"\x4e\xf9" + scsym["sidecar_load"].to_bytes(4, "big")
    print(f"sidecar: save 0x{bd.SAVE_HOOK:08x}->0x{scsym['sidecar_save']:08x}; load 0x{bd.LOAD_HOOK:08x}->0x{scsym['sidecar_load']:08x}")

    # 5) CORE: keep STATE/stride4 -> B ; open clamps ; raise the list cap (reach slot 129)
    nset = nb = nclamp = 0
    for fn, spec in bd.CORE.items():
        for imm_va, hn in spec["sites"]:
            if hn.startswith("h_set"):          # SETTINGS site -> logger (return A) instead of B
                reg = hn.split("_")[-1]
                bd.redirect_site(img, imm_va, lsym[f"h_lset_{reg}"]); nset += 1
            else:                                # STATE / stride4 -> B (safe, unchanged)
                bd.redirect_site(img, imm_va, sym[hn]); nb += 1
        for cva in spec["clamps"]:
            bd.raise_clamp(img, cva); nclamp += 1
    for cap_va, (old, new) in bd.CAPS.items():
        o = bd.off(cap_va); assert bytes(img[o:o + len(old)]) == old, img[o:o+len(old)].hex()
        img[o:o + len(new)] = new

    # 6) ALL remaining (non-CORE) SETTINGS add-sites -> loggers (return A, non-destructive)
    core_set = {imm for spec in bd.CORE.values() for imm, hn in spec["sites"] if hn.startswith("h_set")}
    for va, reg in collect_set_sites():
        if va in core_set:                       # already handled in step 5
            continue
        bd.redirect_site(img, va, lsym[f"h_lset_{reg}"]); nset += 1
    print(f"redirects: {nset} SETTINGS->logger, {nb} STATE/stride4->B, {nclamp} clamps opened, cap raised")

    OUT.write_bytes(bytes(img))
    print(f"\n{OUT}: {len(img):,} bytes")
    print("NEXT: emu_check ; then package (-V DUAL256ACC) ; read project.256[0:528]")


if __name__ == "__main__":
    main()
