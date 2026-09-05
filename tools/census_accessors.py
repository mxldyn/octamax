#!/usr/bin/env python3
"""
census_accessors.py — the PRECISE map of every code site that turns a static-settings slot
reference into a pointer, so the dual-table redirect (idx>=128 -> table B) can be surgical and
provably complete. Missing one site = a wrong pointer at runtime; over-redirecting a load/save/walk
site = breakage. So we enumerate ALL of them from the BYTES (objdump renders addi/cmpi immediates
in decimal, so text-grep misses the folded-offset refs -- the byte scan is authoritative).

Three reference forms to the static-settings region are catalogued:
  (1) EXACT base 0x100d5b30 in operand position (lea/pea/addi/cmpi/move#/adda/cmpa/movea).
  (2) FOLDED base+field: an operand value in [0x100d5b30, 0x100d5b30+0x448) -- a field offset baked
      into the immediate (e.g. addi.l #(base+0x10e),dN). These are per-field accessors.
  (3) FLEX base 0x100b14f0 and the block-relative combined refs (context only -- flex stays SRAM).

For each hit we print: VA, the opcode class, the raw value (and folded field offset), and the
enclosing function (nearest preceding `link`/prologue) so it can be classified by hand as
  LOAD/SAVE/WALK  (sequential, base-literal, whole-block -> LEAVE on SRAM), or
  RANDOM-ACCESS   (index-driven base+idx*0x448 -> candidate for the idx>=128 redirect).

    python3 tools/census_accessors.py
"""
import pathlib

BASE = 0x40000400
IMG = pathlib.Path("out/stock_mainos.bin").read_bytes()
N = len(IMG)

STATIC = 0x100d5b30      # static-settings base (also flex-walk END marker)
FLEX = 0x100b14f0        # flex-settings base
SLOT = 0x448             # per-slot stride
STATIC_END = 0x100f7f30  # static end (== global base above)


def opname(b0, b1):
    if b1 == 0xf9 and b0 in (0x41, 0x43, 0x45, 0x47, 0x49, 0x4b, 0x4d): return "lea"
    if (b0 << 8 | b1) == 0x4879: return "pea"
    if (b0 << 8 | b1) in (0x4eb9, 0x4ef9): return "jsr/jmp"
    if b1 == 0x7c and b0 in range(0x20, 0x2d, 2): return "movea#"
    if b1 == 0x3c and b0 in range(0x20, 0x2f, 2): return "move.l#"
    if (b0 << 8 | b1) == 0x23fc: return "move.l#abs"
    if b1 == 0xfc and b0 in (0xd1, 0xd3, 0xd5, 0xd7, 0xd9, 0xdb, 0xdd, 0xdf): return "adda#"
    if b1 == 0xfc and b0 in (0x91, 0x93, 0x95, 0x97, 0x99, 0x9b, 0x9d, 0x9f): return "suba#"
    if b1 == 0xfc and b0 in (0xb1, 0xb3, 0xb5, 0xb7, 0xb9, 0xbb, 0xbd, 0xbf): return "cmpa#"
    if b0 == 0x06 and 0x80 <= b1 <= 0x87: return "addi.l#d%d" % (b1 & 7)
    if b0 == 0x0c and 0x80 <= b1 <= 0x87: return "cmpi.l#d%d" % (b1 & 7)
    if b0 in (0x00, 0x02, 0x04, 0x0a) and 0x80 <= b1 <= 0x87: return "immarith"
    return None


def val(k):
    return (IMG[k] << 24) | (IMG[k + 1] << 16) | (IMG[k + 2] << 8) | IMG[k + 3]


# crude function boundary: scan backward for a `link` (0x4e56) or `linkw`/prologue marker.
LINKS = []
for k in range(0, N - 1):
    if IMG[k] == 0x4e and IMG[k + 1] == 0x56:       # link.w a6,#imm
        LINKS.append(BASE + k)
LINKS.sort()
import bisect
def func_of(va):
    i = bisect.bisect_right(LINKS, va) - 1
    return LINKS[i] if i >= 0 else 0


def scan():
    exact, folded, flex = [], [], []
    for k in range(2, N - 3):
        if BASE + k >= 0x400e0000:
            break
        v = val(k)
        op = opname(IMG[k - 2], IMG[k - 1])
        if op is None:
            continue
        va = BASE + k
        if v == STATIC:
            exact.append((va, op, v, 0))
        elif STATIC < v < STATIC + SLOT:
            folded.append((va, op, v, v - STATIC))
        elif v == FLEX:
            flex.append((va, op, v, 0))
    return exact, folded, flex


def show(title, hits, note):
    print(f"\n=== {title} ({len(hits)}) — {note} ===")
    for va, op, v, fld in hits:
        f = func_of(va)
        extra = f"  field+0x{fld:03x}" if fld else ""
        print(f"  0x{va:08x}  {op:<12} #0x{v:08x}{extra}   fn~0x{f:08x}")


def main():
    exact, folded, flex = scan()
    show("STATIC base EXACT 0x100d5b30", exact, "index-mul base-add & walk-end compares")
    show("STATIC base FOLDED base+field", folded, "per-FIELD accessors (offset baked in)")
    show("FLEX base 0x100b14f0", flex, "context only — flex stays in SRAM")

    # group the static (exact+folded) sites by enclosing function -> the true accessor count
    from collections import defaultdict
    byfn = defaultdict(list)
    for va, op, v, fld in exact + folded:
        byfn[func_of(va)].append((va, op, fld))
    print(f"\n=== STATIC accessors grouped by function ({len(byfn)} distinct functions) ===")
    for f in sorted(byfn):
        sites = byfn[f]
        ops = ",".join(sorted({o for _, o, _ in sites}))
        print(f"  fn~0x{f:08x}  {len(sites):2} site(s)  [{ops}]")


if __name__ == "__main__":
    main()
