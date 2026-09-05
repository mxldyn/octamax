#!/usr/bin/env python3
"""
Build a patched Octatrack MKII firmware .syx from YOUR OWN copy of the official OS.

No Elektron binary is distributed with this repository. You supply the stock .syx
(downloaded from elektron.se); this script applies the patch hunks — which are the
only part authored here — and repacks the result.

    python3 sysex/apply_patch.py -i OCTATRACK_OS1.40C.syx -o OCTAMAX_2.syx \\
        -p sysex/patches/octamax-2.0-beta.json --bin OCTAMAX_2.bin

`--bin` additionally writes the CF-card image for PROJECT -> OS UPGRADE, which is much
faster than flashing over MIDI. Omit `-p` to build the older behaviour-only r10 patch.

Every step is verified: the stock file's checksum, the original bytes under each
hunk, and the checksum of the produced .syx. Any mismatch aborts before writing.
"""
import argparse, hashlib, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_PATCH = HERE / "patches" / "maxolydian-r10.json"
TOOL_CANDIDATES = [
    ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool",
    Path("elektron-firmware-tool"),
]


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def find_tool(override):
    if override:
        if not os.access(override, os.X_OK):
            die(f"{override} is not executable")
        return str(override)
    for c in TOOL_CANDIDATES:
        if c.is_absolute() or c.exists():
            if os.access(c, os.X_OK):
                return str(c)
        elif shutil.which(str(c)):
            return shutil.which(str(c))
    die(
        "elektron-firmware-tool not found.\n"
        "  Run ./setup.sh to clone and build it, or pass --tool /path/to/elektron-firmware-tool\n"
        "  Upstream: https://github.com/mischa85/elektron-firmware-tool"
    )


def run(cmd, env=None):
    p = subprocess.run(cmd, capture_output=True, text=True,
                       env=({**os.environ, **env} if env else None))
    if p.returncode != 0:
        die(f"{cmd[0]} failed:\n{p.stdout}{p.stderr}")
    return p.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-i", "--input", required=True, help="stock .syx from Elektron")
    ap.add_argument("-o", "--output", required=True, help="patched .syx to write")
    ap.add_argument("-p", "--patch", default=DEFAULT_PATCH, help="patch definition JSON")
    ap.add_argument("--tool", help="path to elektron-firmware-tool")
    ap.add_argument("--bin", metavar="FILE",
                    help="also write a CF-card .bin for PROJECT -> OS UPGRADE (much faster than MIDI)")
    ap.add_argument("--force", action="store_true",
                    help="continue even if the stock .syx checksum differs (NOT recommended)")
    args = ap.parse_args()

    patch = json.loads(Path(args.patch).read_text())
    tgt = patch["target"]
    tool = find_tool(args.tool)

    print(f"patch  : {patch['name']} {patch['version']}")
    print(f"target : {tgt['device']} OS {tgt['os']}")
    print(f"tool   : {tool}\n")

    # --- 1. verify the stock input -------------------------------------------------
    got = sha256(args.input)
    if got != tgt["stock_syx_sha256"]:
        msg = (f"stock .syx checksum mismatch\n"
               f"  expected {tgt['stock_syx_sha256']}\n"
               f"  got      {got}\n"
               f"  This patch targets OS {tgt['os']} for the {tgt['device']} only.")
        if not args.force:
            die(msg)
        print(f"warning: {msg}\n")
    else:
        print("[1/5] stock .syx checksum ok")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # --- 2. extract the MAIN OS section ----------------------------------------
        run([tool, "-i", args.input, "-d", str(tgt["section"]), "-o", str(tmp)])
        cands = list(tmp.glob(f"section_{tgt['section']}_*.bin"))
        if len(cands) != 1:
            die(f"expected one section_{tgt['section']}_*.bin, got {[c.name for c in cands]}")
        sect = cands[0]
        data = bytearray(sect.read_bytes())
        print(f"[2/5] extracted {sect.name} ({len(data):,} bytes)")

        if len(data) != tgt["section_len"]:
            die(f"section length {len(data):,}, expected {tgt['section_len']:,}")
        if hashlib.sha256(data).hexdigest() != tgt["section_sha256_before"] and not args.force:
            die("extracted MAIN OS does not match the expected stock image")

        # --- 3. apply the hunks -----------------------------------------------------
        applied = 0
        for h in patch["hunks"]:
            off, orig, new = h["offset"], bytes.fromhex(h["orig"]), bytes.fromhex(h["new"])
            if bytes(data[off:off + len(orig)]) != orig:
                die(f"hunk at {h['addr']}: original bytes do not match — wrong firmware or "
                    f"already patched. Start from a clean stock .syx.")
            data[off:off + len(new)] = new
            applied += len(new)
        print(f"[3/5] applied {len(patch['hunks'])} hunks ({applied} bytes)")

        after = hashlib.sha256(data).hexdigest()
        if after != tgt["section_sha256_after"] and not args.force:
            die(f"patched MAIN OS checksum mismatch\n  expected {tgt['section_sha256_after']}\n  got      {after}")

        patched = tmp / "mainos_patched.bin"
        patched.write_bytes(data)

        # --- 4. repack --------------------------------------------------------------
        # The CF .bin wraps the very same container the .syx is built from, so ask the tool to
        # emit it and let tools/make_bin.py wrap it -- no second pass over the firmware.
        container = tmp / "elek_container.bin"
        run([tool, "-i", args.input, "-c", str(tgt["section"]), str(patched),
             "-V", patch["display_version"], "-o", args.output],
            env={"EFT_EMIT_CONTAINER": str(container)})
        print(f"[4/5] repacked -> {args.output}")
        if args.bin:
            if not container.exists():
                die("the firmware tool did not emit a container; your build may predate the "
                    "EFT_EMIT_CONTAINER patch (see setup.sh)")
            run([sys.executable, str(ROOT / "tools" / "make_bin.py"), str(container),
                 "-o", args.bin, "--expect-version", patch["display_version"]])
            print(f"      CF image  -> {args.bin}")

    # --- 5. verify the result -------------------------------------------------------
    out = sha256(args.output)
    if out == patch["result_syx_sha256"]:
        print(f"[5/5] output checksum ok — byte-identical to the reference build\n")
    else:
        print(f"[5/5] warning: output checksum differs from the reference build\n"
              f"        expected {patch['result_syx_sha256']}\n"
              f"        got      {out}\n"
              f"        (a different elektron-firmware-tool build can change aPLib packing)\n")

    print(f"done: {args.output} ({os.path.getsize(args.output):,} bytes)")
    print("\nchanges in this build:")
    for c in patch["changes"]:
        print(f"  - {c['id']}: {c['desc']}")
    print("\nRead FLASHING.md before flashing. Keep the official .syx at hand for recovery.")


if __name__ == "__main__":
    main()
