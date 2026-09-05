#!/usr/bin/env python3
"""
build_probe256b.py -- diagnose WHY FN-VIEW (0x40093980) fails for STATIC slot 129 (idx 128) during
load, which clears the slot (P7 regression). FN-VIEW writes its failure code into STATE[idx]@8 (status,
3=error) and STATE[idx]@12 (errcode: -16 filename-invalid, -30 bad-magic, else file open/read error).
For idx=128 STATE[128]=STATE-B[0]=0x40ab79e0. The stock sidecar dumps only SETTINGS-B, so here we
EXTEND the sidecar dump a little past SETTINGS-B to also capture STATE-B[0..3] -> project.256.

  Full P7 build (on-SELECT chain migrated) + sidecar SETB_HI extended to 0x40ab7c00 so the dump covers
  SETTINGS-B (0x22400 B) AND the first STATE-B records. After LOAD + SAVE, read:
    project.256[0x22400 + 0] = STATE-B[0] record; @8 = status (3=err), @12 = errcode.

    python3 tools/build_probe256b.py   # -> out/mainos_persist256.bin (repackage as DUAL256P8)
"""
import sys
sys.path.insert(0, "tools")
import build_dual256 as bd
import build_persist256 as bp

# extend the sidecar SETTINGS-B dump to also cover STATE-B[0..N] (STATE-B starts at 0x40ab79e0)
bd.SETB_HI = 0x40ab7c00        # +0x800 past SETTINGS-B end -> includes STATE-B[0..~46]

if __name__ == "__main__":
    print(f"probe: sidecar dump extended to [0x{bd.SETB_LO:08x},0x{bd.SETB_HI:08x}) "
          f"-> project.256 covers SETTINGS-B + STATE-B[0] @ off 0x22400")
    bp.main()
