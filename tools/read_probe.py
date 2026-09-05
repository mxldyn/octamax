#!/usr/bin/env python3
"""read_probe.py -- decode a diagnostic build's probe block out of <project>/project.256.

Probe builds park their records in SETTINGS-B at 0x40ab65e0, which is project.256 offset 0x21000, so a
SAVE on the device carries them off the card. This decodes them, and resolves every recorded pointer
back to a table and a UI slot -- which is usually the whole answer, since a per-slot record address
names the slot outright.

The layout is imported from the build script that produced the image (its `LAYOUT` dict), so the
decoder cannot drift from the build. That mattered: rounds of this investigation were decoded by
hand-retyped offsets, and one round silently read a stale array offset after the layout shifted.

    python3 tools/read_probe.py /Volumes/OCTATRACK/universi/<proj>/project.256
    python3 tools/read_probe.py <file> --build build_diag_loaderr11     # default

ALWAYS `diskutil unmount` + `mount` the CF before reading: while the OT has written the card, macOS
can serve a stale copy (it once returned 0 bytes for a 636 KB file and produced a flatly wrong
conclusion).
"""
import importlib, pathlib, sys

PROBE_OFF = 0x21000                 # PROBE 0x40ab65e0 - SET_B 0x40a955e0
MAGIC = 0x10ade111
SET_A, SET_B, STRIDE = 0x100d5b30, 0x40a955e0, 0x448
ST_A, ST_B, ST_STRIDE = 0x46c90a78, 0x40ab79e0, 44


def tag(p):
    """Resolve a recorded pointer to a table and UI slot. SET-B[i] is UI slot 129+i."""
    if p == 0:
        return "NULL"
    if SET_A <= p < SET_A + 128 * STRIDE:
        i = (p - SET_A) // STRIDE
        return f"SET-A[{i}] = UI slot {i + 1}" + ("" if (p - SET_A) % STRIDE == 0 else f" +{(p-SET_A)%STRIDE}")
    if SET_B <= p < SET_B + 128 * STRIDE:
        i = (p - SET_B) // STRIDE
        return f"SET-B[{i}] = UI slot {129 + i}" + ("" if (p - SET_B) % STRIDE == 0 else f" +{(p-SET_B)%STRIDE}")
    if ST_A <= p < ST_A + 128 * ST_STRIDE:
        return f"STATE-A[{(p - ST_A) // ST_STRIDE}]"
    if ST_B <= p < ST_B + 128 * ST_STRIDE:
        return f"STATE-B[{(p - ST_B) // ST_STRIDE}]"
    return "not a per-slot table"


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    path = pathlib.Path(sys.argv[1])
    build = sys.argv[sys.argv.index("--build") + 1] if "--build" in sys.argv else "build_diag_loaderr11"
    sys.path.insert(0, "tools")
    mod = importlib.import_module(build)
    if not hasattr(mod, "LAYOUT"):
        sys.exit(f"{build} declares no LAYOUT. Add one (see build_diag_loaderr11.py) so the decoder "
                 f"stays tied to the build, or pass --build <the script that made this image>.")
    layout = mod.LAYOUT
    d = path.read_bytes()
    O = PROBE_OFF
    u32 = lambda o: int.from_bytes(d[o:o + 4], "big")
    s32 = lambda o: u32(o) - (1 << 32) if u32(o) >> 31 else u32(o)

    print(f"{path}  ({len(d):,} B)   layout from {build}")
    magic = u32(O)
    if magic != MAGIC:
        print(f"  magic = 0x{magic:08x}, expected 0x{MAGIC:08x} -- no probe ever fired, or this save "
              f"predates the build. Everything below will be empty.")
    for name, spec in layout.items():
        cnt = u32(O + spec["counter"])
        tot = f"  (total seen: {u32(O + spec['total'])})" if "total" in spec else ""
        capped = "  <-- RING FULL, later records were DROPPED" if cnt >= spec["cap"] else ""
        print(f"\n-- {name}: {cnt} recorded{tot}{capped}")
        for i in range(spec["cap"]):
            o = O + spec["array"] + i * spec["entry"]
            if not any(d[o:o + spec["entry"]]):
                continue
            parts = []
            for fname, foff, kind in spec["fields"]:
                if kind == "str":
                    b = d[o + foff:o + spec["entry"]]
                    z = b.find(b"\0")
                    parts.append(f"{fname}={(b[:z] if z >= 0 else b).decode('ascii', 'replace')!r}")
                elif kind == "ptr":
                    p = u32(o + foff)
                    parts.append(f"{fname}=0x{p:08x} [{tag(p)}]")
                elif kind == "s32":
                    parts.append(f"{fname}={s32(o + foff)}")
                elif kind == "hex":
                    parts.append(f"{fname}=0x{u32(o + foff):08x}")
                else:
                    parts.append(f"{fname}={u32(o + foff)}")
            print(f"  [{i}] " + "  ".join(parts))

    print("\n-- populated SETTINGS-B records (the rest of project.256) --")
    any_rec = False
    for i in range(128):
        r = d[i * STRIDE:(i + 1) * STRIDE]
        if not r or r[:1] == b"\x00":
            continue
        z = r.find(b"\0")
        # the probe block overlaps a high slot's record; say so rather than printing garbage
        note = "  (overlapped by the probe block)" if i * STRIDE < O + 0x300 and (i + 1) * STRIDE > O else ""
        print(f"  SET-B[{i}] UI slot {129 + i}: {r[:z].decode('ascii', 'replace')!r}"
              f"  slicecount(+1092)={int.from_bytes(r[0x444:0x448], 'big')}{note}")
        any_rec = True
    if not any_rec:
        print("  none")


if __name__ == "__main__":
    main()
