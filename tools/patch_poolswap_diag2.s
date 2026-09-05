    .cpu 5407
    .text
| =====================================================================
|  MAXODIAG #2 — spare recorder voices from the per-track voice-stop.
|
|  Tests whether FUN_40006820 (clears voice active flag 0x800049d8[t*0xA8])
|  is the dominant silencer during a project load. When a project change is
|  armed (g_swap), FUN_40006820 SKIPS stopping any track whose voice is a
|  recorder/pickup (voice[0x14]==4). Combined with recorder-page preservation
|  (FUN_40096a5c 0x88->0x80, applied in the build script).
|
|  Also: FUN_40063e28 arms g_swap + skips the picker-open teardown (keeps
|  audio alive through the picker), same as diag #1 but now setting the flag.
|
|  DIAG caveat: g_swap is armed on the change and NOT cleared -> after the
|  change, pickup voices stay unstoppable until reboot. Fine for one test;
|  reflash R11 afterwards.
| =====================================================================

| ---- FUN_40063e28 hook: arm swap + skip teardown, open picker ----
ps_change:
    tst.l   4(%sp)                | param_1 (YES = 0)
    bne.b   pc_ret
    moveq   #1, %d0
    move.l  %d0, g_swap           | arm swap
    jmp     0x400647a0            | open CHOOSE PROJECT picker (skip a10c8 + 8fe4)
pc_ret:
    rts

| ---- FUN_40006820 hook: spare recorder/pickup voices while swapping ----
ps_stop:
    move.l  4(%sp), %d0           | track (0..7) or 0xffffffff
    cmpi.l  #8, %d0
    bcc.b   ps_stock              | >=8 (all): stock recurses per-track back through here
    tst.l   g_swap
    beq.b   ps_stock              | not swapping -> stock
    move.l  #0xa8, %d1
    mulu.l  %d1, %d0              | d0 = track * 0xa8
    move.l  #0x800049d8, %a0
    add.l   %d0, %a0              | a0 = voice struct
    mvz.b   0x14(%a0), %d0        | voice type
    cmpi.l  #4, %d0
    bne.b   ps_stock              | not recorder/pickup -> stock stop
    rts                           | recorder + swapping -> SPARE (no stop)
ps_stock:
    move.l  %a2, -(%sp)           | replicate displaced prologue (push A2/D2; param -> D1)
    move.l  %d2, -(%sp)
    move.l  0xc(%sp), %d1
    jmp     0x40006828            | resume FUN_40006820 after the move.l (moveq #7,D0)

    .balign 4
g_swap:     .long 0
