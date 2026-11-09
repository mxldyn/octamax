| patch_ptnrestart -- [PTN] + the playing pattern restarts it at the next CHAIN BEHAVIOR window.
|
| Stock keeps the current pattern in 0x800065bd/be (bank/ptn) and the cued one in 0x800065bf/c0;
| "nothing cued" is cued == current. Cueing the playing pattern is therefore a no-op (and is how
| a cue gets cancelled). Each step the sequencer (0x400a4310..0x400a43a0) computes pending =
| cued != current: pending and step % window == 0 -> switch 0x400a43a0; not pending -> switch
| only at the pattern end. The loop restart is itself that switch with cued == current, and the
| switch reloads the step counter from the start offset (0x400a483a), so a switch to the same
| pattern IS a restart.
|
| This patch adds one byte, RS_FLAG ("restart cued"):
|   rs_pick   [PTN] trig handler, the select call (0x40056b68 jsr 0x400a1030). A pick of the
|             playing pattern while playing, not in arranger mode, with nothing cued toggles the
|             flag (a second press cancels it); any other pick clears it. Stock call untouched.
|   rs_entry  entry of the cue function 0x400a0570: every other cue (stop, MIDI program change,
|             bank window, arranger, project load) clears the flag. rs_pick's own call keeps it.
|   rs_pend   the pending test of the switch decision: pending |= RS_FLAG.
|   rs_take   the switch itself: consumes the flag (the window or the natural end, whichever first).
|   rs_led    the pattern-trig LED painter: while the flag is set the playing pattern's trig is
|             painted exactly like a cued pattern's trig.

    .equ CUR_BANK,  0x800065bd
    .equ CUR_PTN,   0x800065be
    .equ CUE_BANK,  0x800065bf
    .equ CUE_PTN,   0x800065c0
    .equ PLAYING,   0x800065b8      | 1 = sequencer running
    .equ ARRANGER,  0x460d1aec      | non-zero = arranger mode
    .equ UI_BANK,   0x80000002      | bank whose patterns the trig keys show
    .equ SELECT,    0x400a1030      | (bank, ptn): cue / select a pattern
    .equ CUE_BODY,  0x400a0578      | 0x400a0570 after its displaced prologue
    .equ PEND_DONE, 0x400a4352      | after the stock pending computation (d6)
    .equ TAKE_RES,  0x400a43a6      | after the displaced switch head
    .equ LED_CUE,   0x400354b8      | paint d5's trig as cued
    .equ LED_RES,   0x400354a4      | stock: cmpl d5,d0 (cued vs shown pattern)

| ------------------------------------------------------------------ block A (0x400d6996)
    .section .ra,"ax"

| 0x40056b68: jsr SELECT with (bank, ptn) pushed by the caller at 4(sp)/8(sp).
    .global rs_pick
rs_pick:
    bsr.w   rs_same                 | d0 = 1: pick == playing pattern, nothing cued
    lea     RS_FLAG,%a0             | +0 RS_FLAG, +1 RS_SAME
    move.b  %d0,1(%a0)              | rs_entry leaves the flag alone during our own call
    move.l  8(%sp),-(%sp)           | SELECT clobbers its argument slots: give it copies
    move.l  8(%sp),-(%sp)
    jsr     SELECT
    addq.l  #8,%sp
    lea     RS_FLAG,%a0
    moveq   #0,%d0
    tst.b   1(%a0)
    beq.b   2f
    tst.b   (%a0)
    bne.b   2f                      | already cued: this press cancels it
    moveq   #1,%d0
2:  move.b  %d0,(%a0)
    clr.b   1(%a0)
    rts

| ------------------------------------------------------------------ block B (0x400d702a)
    .section .rb,"ax"

| rs_same: called from rs_pick, so the pick's (bank, ptn) sit at 8(sp)/12(sp). Returns d0.
rs_same:
    moveq   #0,%d0
    moveq   #1,%d1
    cmp.l   PLAYING,%d1
    bne.b   1f
    tst.l   ARRANGER
    bne.b   1f
    lea     CUR_BANK,%a0            | +0 cur bank, +1 cur ptn, +2 cued bank, +3 cued ptn
    mvs.b   (%a0),%d1
    cmp.l   8(%sp),%d1
    bne.b   1f
    mvs.b   2(%a0),%d1
    cmp.l   8(%sp),%d1
    bne.b   1f
    mvs.b   1(%a0),%d1
    cmp.l   12(%sp),%d1
    bne.b   1f
    mvs.b   3(%a0),%d1
    cmp.l   12(%sp),%d1
    bne.b   1f
    moveq   #1,%d0
1:  rts

| 0x400a43a0 (replaces movel (a2),d0 ; moveq #1,d2 ; orl d2,d0): the switch happens.
    .global rs_take
rs_take:
    clr.b   RS_FLAG
    move.l  (%a2),%d0
    moveq   #1,%d2
    or.l    %d2,%d0
    jmp     TAKE_RES

| ------------------------------------------------------------------ block D (0x400d7788)
    .section .rd,"ax"

| 0x400a432a (replaces mvsb CUR_PTN,d1). Stock d6 = (cued != current) as 0/1; d0/d1 are dead
| after it.
    .global rs_pend
rs_pend:
    mvs.b   CUR_PTN,%d1
    mvs.b   CUE_PTN,%d0
    cmp.l   %d1,%d0
    bne.b   1f
    mvs.b   CUR_BANK,%d0
    mvs.b   CUE_BANK,%d1
    cmp.l   %d0,%d1
    bne.b   1f
    moveq   #0,%d6
    tst.b   RS_FLAG
    beq.b   2f
1:  moveq   #1,%d6
2:  jmp     PEND_DONE

    .global RS_FLAG
RS_FLAG: .byte 0
RS_SAME: .byte 0

| ------------------------------------------------------------------ block C (0x400d7be6)
    .section .rc,"ax"

| 0x400a0570 (replaces lea -20(sp),sp ; moveml d2-d6,(sp)).
    .global rs_entry
rs_entry:
    tst.b   RS_SAME
    bne.b   1f
    clr.b   RS_FLAG
1:  lea     -20(%sp),%sp
    movem.l %d2-%d6,(%sp)
    jmp     CUE_BODY

| 0x4003549e (replaces mvsb CUE_PTN,d5). d0 = the pattern shown as current, d4 = 1; d1 is
| overwritten by the stock code that follows either way.
    .global rs_led
rs_led:
    tst.b   RS_FLAG
    beq.b   1f
    moveq   #1,%d5
    cmp.l   PLAYING,%d5
    bne.b   1f
    mvs.b   CUR_BANK,%d5
    mvz.b   UI_BANK,%d1
    cmp.l   %d1,%d5
    bne.b   1f
    mvs.b   CUR_PTN,%d5
    jmp     LED_CUE
1:  mvs.b   CUE_PTN,%d5
    jmp     LED_RES
