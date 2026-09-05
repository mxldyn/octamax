#!/usr/bin/env python3
"""hookcheck.py -- HARD SAFETY CHECK for patch/probe builds: no address strictly INSIDE a hook hole
may be reachable as a branch/jump target.

Replacing N bytes at a hook site silently assumes the whole run of N bytes is entered only at its first
address. That assumption is invisible in a disassembly and false surprisingly often: P39's four `-2`
probes each swallowed a run whose SECOND instruction was a separate branch target (e.g. four `bra.b`
land on 0x4008498e, the success path that skips the `moveq #-2`). Any such branch lands mid-`jmp` and
raises VEC:04 illegal instruction -- exactly the exception P39 threw on hardware.

    from hookcheck import check_holes
    check_holes(image_bytes, [(va, nbytes), ...])       # raises SystemExit on any interior target

Also usable standalone for an ad-hoc check:
    python3 tools/hookcheck.py out/mainos_persist256.bin 0x4008498c:10 0x40022b50:6
"""
import sys

BASE = 0x40000400
_BR = {0x60: "bra", 0x61: "bsr", 0x62: "bhi", 0x63: "bls", 0x64: "bcc", 0x65: "bcs", 0x66: "bne",
       0x67: "beq", 0x68: "bvc", 0x69: "bvs", 0x6a: "bpl", 0x6b: "bmi", 0x6c: "bge", 0x6d: "blt",
       0x6e: "bgt", 0x6f: "ble"}


def find_interior_targets(img, holes):
    """holes = [(va, nbytes)]. Returns [(source_va, kind, target_va)] for every branch, jump or stored
    pointer that lands strictly inside a hole (i.e. anywhere but its first byte)."""
    interior = set()
    for va, n in holes:
        interior.update(range(va + 2, va + n, 2))
        interior.update(range(va + 1, va + n))          # odd addresses too: a target mid-word is worse
    hits = []
    for i in range(0, len(img) - 6, 2):
        va = BASE + i
        b0, b1 = img[i], img[i + 1]
        if b0 in _BR:
            if b1 not in (0x00, 0xff):                   # Bcc.b
                disp = b1 - 256 if b1 > 127 else b1
                t = va + 2 + disp
                if t in interior:
                    hits.append((va, f"{_BR[b0]}.b", t))
            elif b1 == 0x00:                             # Bcc.w
                w = int.from_bytes(img[i + 2:i + 4], "big")
                t = va + 2 + (w - 65536 if w > 32767 else w)
                if t in interior:
                    hits.append((va, f"{_BR[b0]}.w", t))
        two = bytes(img[i:i + 2])
        if two in (b"\x4e\xf9", b"\x4e\xb9"):            # jmp/jsr abs.l
            t = int.from_bytes(img[i + 2:i + 6], "big")
            if t in interior:
                hits.append((va, "jmp/jsr abs", t))
        if two in (b"\x4e\xfa", b"\x4e\xba"):            # jmp/jsr pc@(d16)
            w = int.from_bytes(img[i + 2:i + 4], "big")
            t = va + 2 + (w - 65536 if w > 32767 else w)
            if t in interior:
                hits.append((va, "jmp/jsr pc@", t))
    # stored pointers: jump tables, callback fields, anything holding the address as data
    for a in sorted(interior):
        b = a.to_bytes(4, "big")
        j = 0
        while True:
            j = img.find(b, j)
            if j < 0:
                break
            hits.append((BASE + j, "LITERAL/table", a))
            j += 1
    return hits


def check_holes(img, holes):
    hits = find_interior_targets(img, holes)
    if not hits:
        print(f"  hookcheck: OK -- no branch, jump or stored pointer lands inside any of the "
              f"{len(holes)} hook holes")
        return
    print("REFUSING: a hook hole swallows an address that is itself a branch/jump target.")
    print("A branch there lands mid-instruction -> VEC:04 illegal instruction on hardware.\n")
    for va, kind, t in sorted(hits, key=lambda x: x[2]):
        print(f"  0x{va:08x}  {kind:16} -> 0x{t:08x}")
    print("\nShrink the hole so it covers ONE entry point, or hook a different site.")
    sys.exit(1)


if __name__ == "__main__":
    import pathlib
    img = bytes(pathlib.Path(sys.argv[1]).read_bytes())
    holes = []
    for a in sys.argv[2:]:
        va, n = a.split(":")
        holes.append((int(va, 16), int(n)))
    check_holes(img, holes)
