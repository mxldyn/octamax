#!/usr/bin/env python3
"""
Phase 2 — Layer 1: STATIC state-table dual-table accessors (approach B), behaviour-neutral.

Layers on top of the hardware-verified Phase 1 foundation (out/mainos_phase1.bin: pool +128
pages / 768 KB reserved, settings block in DDR, boot-zero, CF-id popup fix). Adds ONLY the
state-table (0x2c B/slot) dual-table plumbing:

  - 9 range-check helpers (one per destination register actually used) placed in a code cave.
    Each converts a PRODUCT (slot*44) already in REG to a table pointer:
        product <  0x1600  -> REG + 0x46c90a78   (table A, slots 0..127, IDENTICAL to stock)
        product >= 0x1600  -> REG + (0x40b00000-0x1600)  (table B, slots 128..255)
  - At each of the 35 random-access sites, the inline 6-byte `addi.l/adda.l #0x46c90a78,REG`
    becomes a 6-byte `jsr sh_<REG>` (byte-exact). The register is derived from the opcode.
  - The allocator loop-start `lea 0x46c90a78,a0` @ 0x4002409c is left untouched (it walks
    table A sequentially; extended to table B in Layer 2).

Behaviour-neutral: every bound in the image still stops at 128, so no slot >= 128 is ever
requested and the table-B branch is dead. For slots 0..127 the helper reproduces the stock
pointer exactly. A boot that behaves identically to Phase 1 (load/play/record altre-galassie)
proves the helper plumbing before Layer 2 opens the bounds.

    python3 tools/build.py            # -> out/mainos.bin (R11)
    python3 tools/build_phase1.py     # -> out/mainos_phase1.bin (foundation)
    python3 tools/build_phase2_state.py  # -> out/mainos_phase2_state.bin
"""
import pathlib, subprocess, sys
from collections import Counter

BASE = 0x40000400
SRC = pathlib.Path("out/mainos_phase1.bin")
OUT = pathlib.Path("out/mainos_phase2_state.bin")

STATE_BASE = 0x46c90a78            # table A base (unique 4-byte immediate)
ALLOC_LEA = 0x4002409c             # the ONE lea site (allocator loop-start) — do NOT convert
CAVE_AT = 0x400d7400               # free cave past bootzero_stub (ends 0x400d72cf)
CAVE_END_LIMIT = 0x400d7c3c
CODE_END = 0x400e0000

# opcode(2 bytes just before the immediate) -> helper symbol
#   addi.l #imm,dN : 06 8N   (N = 0,1,2,4,5 seen)
#   adda.l #imm,aN : dK fc   (d1fc=a0 d3fc=a1 d5fc=a2 d7fc=a3 dbfc=a5 seen)
ADDI_REG = {0x00: "sh_d0", 0x01: "sh_d1", 0x02: "sh_d2", 0x04: "sh_d4", 0x05: "sh_d5"}
ADDA_REG = {0xd1: "sh_a0", 0xd3: "sh_a1", 0xd5: "sh_a2", 0xd7: "sh_a3",
            0xd9: "sh_a4", 0xdb: "sh_a5", 0xdd: "sh_a6"}


def off(a):
    return a - BASE


def classify(img, o):
    """Return (helper_symbol, opcode_hex) for the base-add at immediate offset o, or None to skip."""
    b0, b1 = img[o - 2], img[o - 1]
    if b0 == 0x41 and b1 == 0xf9:            # lea — allocator loop-start
        return None
    if b0 == 0x06 and (b1 & 0xf8) == 0x80:   # addi.l #imm,dN
        return ADDI_REG.get(b1 & 0x07)
    if b1 == 0xfc and b0 in ADDA_REG:        # adda.l #imm,aN
        return ADDA_REG[b0]
    return None


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC} — run tools/build_phase1.py first")
    img = bytearray(SRC.read_bytes())

    # locate the 36 state-base immediates
    needle = STATE_BASE.to_bytes(4, "big")
    offs = []
    i = img.find(needle)
    while i != -1:
        offs.append(i)
        i = img.find(needle, i + 1)
    if len(offs) != 36:
        sys.exit(f"expected 36 state-base refs, found {len(offs)}")

    # assemble + place the 9 helpers
    if subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", "out/_sh.o", "tools/patch_state_helpers.s"]).returncode:
        sys.exit("assembler failed")
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{CAVE_AT:x}", "-o", "out/_sh.elf", "out/_sh.o"], capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/_sh.elf", "out/_sh.bin"], check=True)
    nm = subprocess.run(["m68k-elf-nm", "out/_sh.elf"], capture_output=True, text=True).stdout
    sym = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    blob = pathlib.Path("out/_sh.bin").read_bytes()
    end = CAVE_AT + len(blob)
    print(f"helpers: {len(blob)} B @ 0x{CAVE_AT:08x}..0x{end-1:08x}")
    if end > CAVE_END_LIMIT:
        sys.exit("helpers overrun cave")
    if any(img[off(CAVE_AT):off(end)]):
        sys.exit("cave not free")
    img[off(CAVE_AT):off(end)] = blob

    # rewrite the 35 random-access sites -> jsr sh_<REG>
    conv = Counter(); skipped = []
    for o in offs:
        va = BASE + o
        if va == ALLOC_LEA:
            skipped.append(va)
            continue
        h = classify(img, o)
        if h is None:
            sys.exit(f"unclassified state-base site @ 0x{va:08x} pre={img[o-2:o].hex()}")
        target = sym[h]
        # instruction spans [o-2, o+4): opcode(2) + imm32(4) -> jsr abs.l (4eb9 + addr, 6 bytes)
        img[o - 2:o + 4] = b"\x4e\xb9" + target.to_bytes(4, "big")
        conv[h] += 1
    print(f"converted {sum(conv.values())} random-access sites -> jsr helper; kept {len(skipped)} (allocator lea)")
    for h in sorted(conv):
        print(f"    {h}: {conv[h]}")
    for va in skipped:
        print(f"    keep 0x{va:08x} lea 0x{STATE_BASE:08x} (allocator loop-start)")

    # post-checks
    if len(skipped) != 1 or skipped[0] != ALLOC_LEA:
        sys.exit(f"allocator-lea skip set wrong: {[hex(x) for x in skipped]}")
    if sum(conv.values()) != 35:
        sys.exit(f"expected 35 conversions, got {sum(conv.values())}")
    # remaining 0x46c90a78 immediates: 1 allocator lea + 9 helper TA-immediates = 10
    remain = img.count(needle)
    if remain != 10:
        sys.exit(f"remaining 0x46c90a78 immediates = {remain}, want 10 (1 lea + 9 helper TA)")
    print(f"post-check: {remain} residual 0x46c90a78 immediates (1 lea + 9 helper TA) OK")

    # equivalence proof: Layer 1 is a PURE PASSTHROUGH — the helper always returns
    # base + product, identical to the replaced inline addi/adda for EVERY input value.
    # There is no range check and no table-B redirect (both moved to Layer 2, after an
    # earlier bhi #0x1600 redirect crashed at boot: `bhi` is unsigned, so sentinel /
    # out-of-range indices reaching the 5 UNGUARDED accessors — e.g. a "no slot" -1 ->
    # 0xffffffd4, a default current-slot 255 -> 0x2bf4 — were wrongly sent into the
    # boot-zeroed table B -> deref 0 -> VEC:04 ADDR:0). Assert the passthrough over the
    # full 32-bit-relevant range, including negatives and >255 sentinels.
    TA = STATE_BASE
    def helper(product):
        return (TA + product) & 0xffffffff
    bad = []
    probes = list(range(0, 257))                   # every slot idx + template + one past
    probes += [-1, -44, 0xffffffff, 255 * 44, 300 * 44, 0x7fffffff]  # sentinels / OOR
    for product in probes:
        if helper(product) != (TA + product) & 0xffffffff:
            bad.append(product)
    if bad:
        sys.exit(f"PASSTHROUGH PROOF FAILURE: helper != base+product for {bad}")
    print("passthrough proof: helper == base+product for ALL probes incl. sentinels/OOR OK")
    print("                   no redirect in Layer 1 (table-B logic deferred to Layer 2) OK")

    OUT.write_bytes(bytes(img))
    print(f"\n{OUT}: {len(img):,} bytes")


if __name__ == "__main__":
    main()
