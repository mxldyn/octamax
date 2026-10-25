| patch_autoptn.s — BANK AUTO PTN 1: picking a bank in SELECT BANK also picks its pattern 1.
|
|   BANK AUTO PTN 1   0x800000a8   bank trig in SELECT BANK -> (bank, P1), no SELECT PTN wait
|
| Cleared by default, so an unconfigured unit behaves exactly like stock.
|
| Stock state machine (FUN_4007b2fc = trig press while the bank window owns the trig keys,
| FUN_4007b434 = trig release; phase 0x460e73c6: 0 pick bank, 1 pick pattern, 2 pattern picked):
|
|   [BANK]            FUN_4007af80  phase 0, "SELECT BANK", trig handlers registered
|   trig N (phase 0)  FUN_4007b2fc  bank = N, FUN_4007b26c -> phase 1, "BANK N: SELECT PTN"
|   trig M (phase 1)  FUN_4007b2fc  close window (if [BANK] is up), FUN_400a1030(bank, M),
|                                   held-key mask |= 1<<M, phase 2
|   release M         FUN_4007b434  mask &= ~(1<<M); when the mask empties and [BANK] is up:
|                                   unregister the trig handlers, LED cleanup
|
| The hook sits on the last instruction of the phase-0 path (`move.l D2,(0x460e73b8)`, the
| bank store at 0x4007b344). With the toggle off it replays the stock epilogue and tail-calls
| FUN_4007b26c, byte-for-byte what the function did. With it on, after FUN_4007b26c has put the
| machine in phase 1 exactly as stock, it feeds FUN_4007b2fc a synthetic press of trig 1
| (pattern index 0): the window closes, (bank, P1) is requested through the same
| FUN_400a1030 a real key press uses, and the machine lands in phase 2. The key the player is
| physically holding is the bank's trig, not trig 1, so the held-key mask is set to that
| bit: its release then runs the stock FUN_4007b434 cleanup like any pattern key's would.
| The mask is cleared before the synthetic press: in phase 0 any bit in it is stale (stock
| never clears it, so a trig still held across a [BANK] re-press leaves its bit behind and
| the next pattern press would chain instead of select — a stock quirk this path does not
| inherit). Nothing else is touched — the PTN key, the [BANK]-held gesture (the window stays
| until [BANK] is released, as stock) and pattern chaining (hold the bank trig, press more
| trigs) all keep their stock code paths.
|
| Flag: 0x800000a8, the one remaining free word of the battery-backed PERSONALIZE block
| (zero references in the firmware; inside the stock 0x64-byte boot restore, so it persists
| through the existing mechanism). Shadow 0x100fff38 = 0x100fff00 + (runtime - 0x80000070).
| The firmware never re-defaults the ANDY payload on an OS version bump, so whatever an older
| OS once kept in that word survives: ON therefore means the value 1 exactly (any other value
| reads as OFF) and the setter normalises — 1 -> 0, anything else -> 1.

    .equ F_AUTOPTN,  0x800000a8
    .equ SH_AUTOPTN, 0x100fff38

    .equ BANK_SEL,   0x460e73b8     | long: bank picked in SELECT BANK (0..15)
    .equ BANK_MASK,  0x460e73c0     | word: trig keys held since the pattern pick
    .equ SELECT_PTN, 0x4007b26c     | FUN_4007b26c: phase 1 + "BANK %c: SELECT PTN" window
    .equ TRIG_PRESS, 0x4007b2fc     | FUN_4007b2fc(trig): the bank window's trig-press handler

    .equ GLYPH_ON,   0x400b5e90
    .equ GLYPH_OFF,  0x400b5e8e

    .text
    .global _start
_start:

| ---- hook: tail of the phase-0 (bank picked) path of FUN_4007b2fc ----
| Site 0x4007b344: `23c2 460e 73b8  move.l D2,(0x460e73b8).l` — 6 bytes, one instruction, then
| the stock epilogue `move.l (SP)+,D2 ; movea.l (SP)+,A2 ; bra.w FUN_4007b26c`.
    .global ap_stub
ap_stub:
    move.l  %d2,BANK_SEL            | displaced instruction: the chosen bank
    move.l  (%sp)+,%d2              | stock epilogue
    movea.l (%sp)+,%a2
    moveq   #1,%d0
    cmp.l   F_AUTOPTN,%d0           | ON = exactly 1 (d0 is scratch here)
    beq.b   ap_on
    jmp     SELECT_PTN              | stock: tail-call into "BANK %c: SELECT PTN"

ap_on:
    jsr     SELECT_PTN              | phase 1, window, handlers, countdown — all stock
    clr.w   BANK_MASK               | phase 0: any held-key bit is stale -> select, not chain
    clr.l   -(%sp)                  | pattern index 0 = P1
    jsr     TRIG_PRESS              | synthetic press of trig 1 in phase 1 (stock code)
    addq.l  #4,%sp
    | the mask now carries bit 0 for the synthetic key; the key really held is the bank's
    | trig. Put the bit there so that trig's release runs the stock cleanup.
    move.l  BANK_SEL,%d1
    moveq   #1,%d0
    lsl.l   %d1,%d0                 | 1 << bank  (bank is 0..15: the trig index)
    move.w  %d0,BANK_MASK
    rts                             | back to the key dispatcher (d2/a2 restored above)

| ---- PERSONALIZE entry ----
    .global lbl_autoptn, get_autoptn, set_autoptn
lbl_autoptn:
    .asciz  "BANK AUTO PTN 1"
    .align  2

get_autoptn:
    move.l  #GLYPH_ON,%d0
    moveq   #1,%d1
    cmp.l   F_AUTOPTN,%d1           | checked only when the word is exactly 1
    beq.b   ga_ret
    move.l  #GLYPH_OFF,%d0
ga_ret:
    rts

| Normalising toggle: 1 -> 0, anything else -> 1 (the delta at 4(sp) is +-1 either way, so
| this matches the stock (v + delta) & 1 on a clean word and still lands on a defined state
| on a stale one). Stored to the runtime word AND its battery shadow; the PERSONALIZE
| dispatcher re-checksums the block after every setter (jmp 0x4001f23c).
set_autoptn:
    moveq   #1,%d1
    moveq   #0,%d0
    cmp.l   F_AUTOPTN,%d1
    beq.b   sa_store                | was exactly 1 -> 0
    move.l  %d1,%d0                 | anything else -> 1
sa_store:
    move.l  %d0,F_AUTOPTN
    move.l  %d0,SH_AUTOPTN
    rts
