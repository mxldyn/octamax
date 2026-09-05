#!/usr/bin/env python3
"""
Wrap a patched ELEK container into an ELUP `.bin` for the CF-card OS UPGRADE path.

Flashing over MIDI SysEx takes several minutes. The manual (8.5.2 OS UPGRADE) describes
the fast alternative: drop a `.bin` in the ROOT of the Compact Flash card, then
PROJECT -> OS UPGRADE -> [YES].

The format was already reversed in Phase 1 (FUN_4007f748) and `tools/bin_decode.py`
decodes the official file and validates its checksum, which proves the algorithm. This is
the forward direction. Decoding showed the payload is simply:

    [4-byte BE length][ELEK container]

i.e. exactly the container elektron-firmware-tool already builds — no new format work.

    word[0]        magic 0x454C5550 "ELUP"
    word[1]        feedback seed
    word[2..n-2]   obfuscated payload
    word[n-1]      obfuscated additive checksum of the plain payload

The cipher is XOR-with-feedback; the per-word variant is chosen by bit 0x800000 of the
PREVIOUS CIPHER word. rot16 and bswap are involutions, so inverting it is direct:

    encode:  x = k ^ mixer ^ p ;  c = rot16(x) ^ XOR_A   (variant 0)
                                  c = bswap(x) ^ XOR_B   (variant 1)

Usage:
    EFT_EMIT_CONTAINER=elek.bin elektron-firmware-tool -i stock.syx -c 3 mainos.bin \\
        -V MAXOLYDIAN -o out.syx
    python3 tools/make_bin.py elek.bin -o OCTATRACK_MAXOLYDIAN.bin
"""
import argparse, struct, sys
from pathlib import Path

MAGIC = 0x454C5550
XOR_A, XOR_B = 0x9E3B16A2, 0x764E28CA
C3, C7 = 0x360FA955, 0xEF4A9AB6
M = 0xFFFFFFFF
DEFAULT_SEED = 0x2F1349D2      # the seed the official 1.40C image uses


def rot16(v):
    return ((v << 16) | (v >> 16)) & M


def bswap(v):
    return (((v & 0xFF) << 24) | ((v & 0xFF00) << 8) |
            ((v & 0xFF0000) >> 8) | (v >> 24)) & M


def encode_word(k, p):
    """Cipher word for plain p, given k = previous cipher word (seed for the first)."""
    x = (k ^ (C3 if (k & 0x800000) == 0 else C7) ^ p) & M
    return (rot16(x) ^ XOR_A) & M if (k & 0x800000) == 0 else (bswap(x) ^ XOR_B) & M


def decode_word(k, c):
    if (k & 0x800000) == 0:
        return (k ^ C3 ^ rot16(c ^ XOR_A)) & M
    return (k ^ C7 ^ bswap(c ^ XOR_B)) & M


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("container", help="ELEK container (EFT_EMIT_CONTAINER output)")
    ap.add_argument("--expect-version", default=None,
                    help="fail unless the container's 10-char version field is exactly this")
    ap.add_argument("-o", "--out", required=True, help="output .bin")
    ap.add_argument("--seed", type=lambda s: int(s, 0), default=DEFAULT_SEED)
    args = ap.parse_args()

    elek = Path(args.container).read_bytes()
    if elek[:4] != b"ELEK":
        sys.exit(f"{args.container} does not start with 'ELEK': {elek[:8]!r}")

    payload = struct.pack(">I", len(elek)) + elek
    pad = (-len(payload)) % 4
    if pad:
        payload += b"\x00" * pad
    words = list(struct.unpack(f">{len(payload)//4}I", payload))
    tag = elek[8:18].decode("ascii", "replace")
    print(f"container : {len(elek):,} bytes  ({elek[:18].decode('ascii', 'replace')})")
    # The elektron-firmware-tool version field is EXACTLY 10 chars. A longer -V is silently DROPPED and
    # the base container's version survives, so the device reports e.g. STOCK140C while running a patched
    # payload -- indistinguishable on the unit, and it breaks the one-unique-name-per-flash rule. The
    # payload itself is unaffected (verified: only the 10 version bytes differ), but refuse to emit an
    # unlabelled image rather than let it reach the CF.
    STOCK_TAGS = ("1.40C", "R0178")          # what survives when -V is dropped
    if any(tag.strip().startswith(s) for s in STOCK_TAGS) or not tag.strip():
        sys.exit(f"REFUSING: container version is {tag!r} -- that is the stock/base tag, so the -V string "
                 f"passed to elektron-firmware-tool was dropped (it must be 10 chars or fewer). The unit "
                 f"would report stock while running a patched payload. Re-run with a shorter -V.")
    if args.expect_version and tag.strip() != args.expect_version:
        sys.exit(f"REFUSING: container version is {tag!r}, expected {args.expect_version!r}.")
    print(f"payload   : {len(payload):,} bytes"
          + (f"  (+{pad} pad bytes to a word boundary)" if pad else ""))

    k, acc, cipher = args.seed, 0, []
    for p in words:
        c = encode_word(k, p)
        cipher.append(c)
        acc = (acc + p) & M
        k = c
    cipher.append(encode_word(k, acc))       # checksum, enciphered like a payload word

    out = struct.pack(">II", MAGIC, args.seed) + struct.pack(f">{len(cipher)}I", *cipher)
    Path(args.out).write_bytes(out)

    # round-trip with the decoder's own logic before claiming success
    k, acc2, plain = args.seed, 0, []
    for c in cipher[:-1]:
        p = decode_word(k, c)
        plain.append(p)
        acc2 = (acc2 + p) & M
        k = c
    ok_payload = struct.pack(f">{len(plain)}I", *plain) == payload
    ok_cksum = decode_word(k, cipher[-1]) == acc2 == acc
    print(f"checksum  : 0x{acc:08x}")
    print(f"round-trip: payload {'ok' if ok_payload else 'MISMATCH'}, "
          f"checksum {'ok' if ok_cksum else 'MISMATCH'}")
    if not (ok_payload and ok_cksum):
        sys.exit("refusing to ship a file that does not decode back to its input")
    print(f"\nwrote {args.out} ({len(out):,} bytes)")
    print("Copy it to the ROOT of the CF card, then PROJECT -> OS UPGRADE -> [YES].")


if __name__ == "__main__":
    main()
