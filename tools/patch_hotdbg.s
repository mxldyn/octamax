    .cpu 5407
    .text
| =====================================================================
|  HOT CHANGE DEBUG INSTRUMENT v4 (on R11) — capture the EXTERNAL recorder state
|  that FUN_40007960 / FUN_40001598 read, PLAYING (at change) vs POST-LOAD (resync).
|
|  Goal: find which piece the load disturbs (beyond metadata, which hot_recmeta fixes)
|  so we preserve ONLY that -- per-frame restore of DSP-read state corrupts (MAXOHT23).
|
|  Logged (BEFORE=playing, AFTER=post-load):
|    ml = recorder metadata length  0x46c939dc  (meta+0x10)
|    ms = recorder metadata state   0x46c939d4  (meta+0x8)
|    t1 = streaming table 0x46c7ff42[6] = 0x46c7ff5a
|    t2 = streaming table 0x46c7fe24[6] = 0x46c7fe3c
|    p5 = voice+0x5c (play pos)      0x80004e24
|    s0 = settings[0] 0x100d52a0
| =====================================================================

hot_dbg_change:
    pea     lbl_before
    jsr     hot_logline
    addq.l  #4, %sp
    tst.l   4(%sp)
    bne.b   hdc_taken
    jmp     0x40063e2e
hdc_taken:
    jmp     0x40063e46

hot_dbg_resync:
    pea     lbl_after
    jsr     hot_logline
    addq.l  #4, %sp
    jsr     hot_flush
    move.l  %a2, -(%sp)
    jsr     0x4009b220
    jmp     0x400238ac

hot_logline:                        | in: 4(sp)=label
    lea     -0x20(%sp), %sp
    movem.l %d2-%d7/%a2, (%sp)
    move.l  0x24(%sp), %a2          | label (7 regs saved = 0x1c, +ret 0x20, +arg 0x24)
    move.l  (0x100d52a0).l, %d2     | s0
    move.l  (0x80004e24).l, %d3     | p5 (voice+0x5c)
    move.l  (0x46c7fe3c).l, %d4     | t2
    move.l  (0x46c7ff5a).l, %d5     | t1
    move.l  (0x46c939d4).l, %d6     | ms (state)
    move.l  (0x46c939dc).l, %d7     | ml (length)
    move.l  (logpos).l, %d0
    lea     logbuf, %a0
    adda.l  %d0, %a0
    move.l  %d2, -(%sp)
    move.l  %d3, -(%sp)
    move.l  %d4, -(%sp)
    move.l  %d5, -(%sp)
    move.l  %d6, -(%sp)
    move.l  %d7, -(%sp)
    move.l  %a2, -(%sp)             | label
    pea     fmt_line
    move.l  %a0, -(%sp)             | dst
    jsr     0x40013a08
    lea     0x24(%sp), %sp
    move.l  (logpos).l, %d1
    add.l   %d0, %d1
    move.l  %d1, (logpos).l
    movem.l (%sp), %d2-%d7/%a2
    lea     0x20(%sp), %sp
    rts

hot_flush:
    move.l  #0x200, -(%sp)
    move.l  #0x460261e0, -(%sp)
    pea     0x400b328b
    pea     logpath
    pea     fh
    jsr     0x40016864
    lea     0x14(%sp), %sp
    tst.l   %d0
    blt.b   hf_done
    move.l  (logpos).l, -(%sp)
    pea     logbuf
    pea     fh
    jsr     0x400166b8
    lea     0xc(%sp), %sp
    pea     fh
    jsr     0x4001677c
    addq.l  #4, %sp
hf_done:
    rts

    .balign 4
logpos:     .long 0
fmt_line:   .asciz "%s ml=%x ms=%x t1=%x t2=%x p5=%x s0=%x\n"
    .balign 2
logpath:    .asciz "/HOTDBG.TXT"
    .balign 2
lbl_before: .asciz "PLAY"
    .balign 2
lbl_after:  .asciz "LOAD"
    .balign 4
fh:         .space 0x40
    .balign 4
logbuf:     .space 0x400
