#!/usr/bin/env python3
"""
make_patch_json.py -- regenerate a sysex/patches/*.json from the built MAIN OS image.

    python3 tools/make_patch_json.py --img out/mainos_all.bin --syx out/OCTAMAX_2_mf1.syx \
        --patch sysex/patches/octamax-2.0-beta.json

Diffs the image against out/stock_mainos.bin into hunks (changed runs, merged across gaps of up
to GAP unchanged bytes -- the same granularity the published files use), keeps the JSON's
name/version/changes, and refreshes the checksums so sysex/apply_patch.py can verify its output
against the .syx that was actually built.
"""
import argparse, hashlib, json, pathlib

BASE = 0x40000400
GAP = 7


def hunks(stock, img):
    runs, start = [], None
    for i, (a, b) in enumerate(zip(stock, img)):
        if a != b:
            if start is None:
                start = i
            last = i
        elif start is not None and i - last > GAP:
            runs.append((start, last + 1)); start = None
    if start is not None:
        runs.append((start, last + 1))
    return [{"addr": f"0x{BASE + s:08x}", "offset": s, "len": e - s,
             "orig": stock[s:e].hex(), "new": img[s:e].hex()} for s, e in runs]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--img", required=True)
    ap.add_argument("--syx", required=True, help="the .syx packaged from --img (for result_syx_sha256)")
    ap.add_argument("--patch", required=True, help="JSON to rewrite in place (metadata kept)")
    ap.add_argument("--stock", default="out/stock_mainos.bin")
    a = ap.parse_args()
    stock = pathlib.Path(a.stock).read_bytes()
    img = pathlib.Path(a.img).read_bytes()
    assert len(stock) == len(img), "image length differs from stock"
    p = pathlib.Path(a.patch)
    j = json.loads(p.read_text())
    assert hashlib.sha256(stock).hexdigest() == j["target"]["section_sha256_before"], "stock image mismatch"
    j["hunks"] = hunks(stock, img)
    j["target"]["section_sha256_after"] = hashlib.sha256(img).hexdigest()
    j["result_syx_sha256"] = hashlib.sha256(pathlib.Path(a.syx).read_bytes()).hexdigest()
    p.write_text(json.dumps(j, indent=1) + "\n")
    print(f"{p}: {len(j['hunks'])} hunks, {sum(h['len'] for h in j['hunks'])} bytes; "
          f"section_after {j['target']['section_sha256_after'][:12]}.. syx {j['result_syx_sha256'][:12]}..")


if __name__ == "__main__":
    main()
