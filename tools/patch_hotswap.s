    .cpu 5407
    .text
| =====================================================================
|  HOT SWAP validation #1 (on R11).
|
|  Core question: does calling FUN_4009083c (the flex/static sample RELOADER) keep the
|  recorder voice (track 6 / R7) playing? FUN_4009083c reloads samples and calls
|  FUN_40096a5c (which unloads slots 0..0x87 via FUN_40096300). Our hot_unload gates
|  FUN_40096300 for recorder slots 0x80-0x87 -> recorders preserved. Critically,
|  FUN_4009083c runs NO voice teardown (no FUN_400a10c8 / FUN_400238a4). So the recorder
|  voice should keep sounding while the flex samples reload.
|
|  Trigger: the RELOAD confirm (FUN_40063bf8) -> instead of a bank reload, arm g_hot and
|  reload the CURRENT project's samples, then disarm. CHANGE PROJECT (FUN_40063e28) is left
|  STOCK, so the project picker still works to load the test project first.
|  Test: load the test project via CHANGE (picker), get R7 playing, then RELOAD. Watch R7.
| =====================================================================

hs_trigger:                     | detour FUN_40063bf8 (RELOAD confirm)
    tst.l   4(%sp)
    bne.b   hst_orig
    | confirm path: reload samples (validation) instead of the bank reload
    moveq   #1, %d0
    move.l  %d0, g_hot          | arm -> hot_unload preserves recorders during FUN_40096a5c
    clr.l   -(%sp)              | FUN_4009083c(0, 0, 0)
    clr.l   -(%sp)
    clr.l   -(%sp)
    jsr     0x4009083c
    lea     12(%sp), %sp
    clr.l   g_hot
    rts
hst_orig:
    jmp     0x40063c16          | original bne target (displaced tst.l 4(sp); bne.b)

| ---- FUN_40096300 hook: while armed, skip UNLOAD of recorder slots 0x80-0x87 ----
hot_unload:
    tst.l   g_hot
    beq.b   hu_stock
    move.l  4(%sp), %d0
    subi.l  #0x80, %d0
    cmpi.l  #8, %d0
    bcc.b   hu_stock
    moveq   #1, %d0
    rts
hu_stock:
    lea     -0x28(%sp), %sp
    movem.l %d2-%d7/%a2-%a5, (%sp)
    jmp     0x40096308

    .balign 4
g_hot:      .long 0
