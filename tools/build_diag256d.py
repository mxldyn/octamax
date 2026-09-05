#!/usr/bin/env python3
"""build_diag256d.py -- bisect P11's two additions over the booting P9: is the hang the LOADLOOP
migration, or the T24 table migration (+ HOLE/SLICE_SCRATCH relocation)? Build P11 with the loadloop
DISABLED (bd.MIGRATE_LOADLOOP=False) but T24 + zero-init + HOLE changes ON. That is "P9 + T24".

  RESULT:
    * BOOTS (like P9) -> the LOADLOOP migration is the sole cause (loop-to-256 mechanics), even with
                         slot 128's body skipped (PF). Scrutinize the stub / 129..255 iteration.
    * STILL hangs     -> the T24 migration or the HOLE/SLICE_SCRATCH relocation broke the load itself
                         (affects low slots / overall), independent of the loadloop.

    python3 tools/build_diag256d.py   # -> out/mainos_persist256.bin (loadloop OFF); package as DUAL256PG
"""
import sys
sys.path.insert(0, "tools")
import build_dual256 as bd
import build_persist256 as bp

bd.MIGRATE_LOADLOOP = False      # <-- the only change vs the P11 build

if __name__ == "__main__":
    print("diag4: MIGRATE_LOADLOOP=False (T24 + zero-init + HOLE changes stay ON) -> 'P9 + T24'")
    bp.main()
