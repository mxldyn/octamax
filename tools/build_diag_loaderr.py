#!/usr/bin/env python3
"""build_diag_loaderr.py -- MEASURING build (fixes nothing). Answers the two open P32 questions.

Q1  Slots >=130 pop "SAMPLE LOAD ERRORS!" although the load visibly succeeds. The popup is emitted by
    finish_load 0x40022b70 -- an async COMPLETION CALLBACK that only reports: it shows the message when
    the result it is handed is negative. The failure happens upstream and every static attempt to find
    the idx=128/129 boundary has come up empty, so capture the FACTS instead: the exact error code and
    the RETURN ADDRESS of whoever invoked the callback.
Q2  Slices never appear on any high slot. Capture what sampleslice 0x40099374 is actually called with.

Both hooks are pure observers: they record and then execute the instructions they replaced.

PROBE 0x40ab65e0 lives inside SETTINGS-B, so the existing sidecar dumps it to <project>/project.256 on
SAVE. It overlaps B slot ~118 (UI slot ~247) -- do not use that slot during the test.
  project.256 offset 0x21000:
    +0x00 magic 0x10ADE111   +0x04 err_count   +0x08 slice_count
    +0x10 err[i]   : [caller_PC][result]           8 B x 16
    +0x90 slice[i] : [slot_idx][arg1]              8 B x 16

Do (one session): boot -> load a sample into slot 130 (expect the error) -> open the AED (slices) -> SAVE.

    python3 tools/build_diag_loaderr.py     # -> out/mainos_diag_loaderr.bin
"""
import subprocess, pathlib, sys
sys.path.insert(0, "tools")
import build_dual256 as bd

SRC = pathlib.Path("out/mainos_persist256.bin")
OUT = pathlib.Path("out/mainos_diag_loaderr.bin")
CODE  = 0x400d6a00                 # free cave (same one the ring diag used)
PROBE = 0x40ab65e0                 # inside SET-B -> dumped by the sidecar
FL_HOOK, FL_BACK = 0x40022b70, 0x40022b76      # 6 B: 2f02 242f 0008
SL_HOOK, SL_BACK = 0x40099374, 0x4009937c      # 8 B: 4fef ffd8 48d7 3cfc

ASM = f"""    .cpu 5407
    .text
| ---- Q1: finish_load(result). On entry sp@(0)=caller PC, sp@(4)=result ----------------------------
fl_probe:
    move.l  %d0,-(%sp)
    move.l  %a0,-(%sp)
    lea     0x{PROBE:x},%a0
    move.l  #0x10ade111,%d0
    move.l  %d0,(%a0)                   | magic
    move.l  4(%a0),%d0                  | err_count
    cmpi.l  #16,%d0
    bcc.b   1f                          | ring full -> just replay
    addq.l  #1,4(%a0)
    lsl.l   #3,%d0
    addi.l  #0x10,%d0
    add.l   %d0,%a0
    move.l  8(%sp),%d0                  | original sp@(0) = caller PC
    move.l  %d0,(%a0)
    move.l  12(%sp),%d0                 | original sp@(4) = result code
    move.l  %d0,4(%a0)
1:  move.l  (%sp)+,%a0
    move.l  (%sp)+,%d0
    move.l  %d2,-(%sp)                  | replaced insn 1
    move.l  8(%sp),%d2                  | replaced insn 2
    jmp     0x{FL_BACK:x}

| ---- Q2: sampleslice(arg1, slot). On entry sp@(4)=arg1, sp@(8)=slot ------------------------------
sl_probe:
    move.l  %d0,-(%sp)
    move.l  %a0,-(%sp)
    lea     0x{PROBE:x},%a0
    move.l  8(%a0),%d0                  | slice_count
    cmpi.l  #16,%d0
    bcc.b   2f
    addq.l  #1,8(%a0)
    lsl.l   #3,%d0
    addi.l  #0x90,%d0
    add.l   %d0,%a0
    move.l  16(%sp),%d0                 | original sp@(8) = slot index
    move.l  %d0,(%a0)
    move.l  12(%sp),%d0                 | original sp@(4) = arg1
    move.l  %d0,4(%a0)
2:  move.l  (%sp)+,%a0
    move.l  (%sp)+,%d0
    lea     -40(%sp),%sp                | replaced insn 1
    movem.l %d2-%d7/%a2-%a5,(%sp)       | replaced insn 2
    jmp     0x{SL_BACK:x}
"""


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC} -- run build_dual256.py && build_persist256.py first")
    img = bytearray(SRC.read_bytes())
    p = "out/_lerr"
    pathlib.Path(p + ".s").write_text(ASM)
    r = subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", p + ".o", p + ".s"], capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr)
    subprocess.run(["m68k-elf-ld", "-Ttext=0x%x" % CODE, "-o", p + ".elf", p + ".o"], capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", p + ".elf", p + ".bin"], check=True)
    blob = pathlib.Path(p + ".bin").read_bytes()
    # symbol table -> VA of sl_probe (fl_probe is at CODE)
    nm = subprocess.run(["m68k-elf-nm", p + ".elf"], capture_output=True, text=True).stdout
    sym = {ln.split()[2]: int(ln.split()[0], 16) for ln in nm.splitlines() if len(ln.split()) == 3}
    for f in (".s", ".o", ".elf", ".bin"):
        pathlib.Path(p + f).unlink(missing_ok=True)

    assert not any(img[bd.off(CODE):bd.off(CODE) + len(blob)]), "cave not empty"
    img[bd.off(CODE):bd.off(CODE) + len(blob)] = blob

    o = bd.off(FL_HOOK)
    assert bytes(img[o:o + 6]) == b"\x2f\x02\x24\x2f\x00\x08", bytes(img[o:o + 6]).hex()
    img[o:o + 6] = b"\x4e\xf9" + sym["fl_probe"].to_bytes(4, "big")

    o = bd.off(SL_HOOK)
    assert bytes(img[o:o + 8]) == b"\x4f\xef\xff\xd8\x48\xd7\x3c\xfc", bytes(img[o:o + 8]).hex()
    img[o:o + 6] = b"\x4e\xf9" + sym["sl_probe"].to_bytes(4, "big")
    img[o + 6:o + 8] = b"\x4e\x71"

    OUT.write_bytes(bytes(img))
    print(f"fl_probe @0x{sym['fl_probe']:08x}   sl_probe @0x{sym['sl_probe']:08x}   blob {len(blob)} B")
    print(f"PROBE 0x{PROBE:08x} = project.256 offset 0x{PROBE - bd.SET_B:05x}")
    print(f"{OUT}: {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
