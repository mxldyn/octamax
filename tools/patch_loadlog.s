    .cpu 5407
    .text
| =====================================================================
|  LOAD-PHASE breadcrumbs (on 2afix base). Objective: find WHERE the project load
|  hangs when the static settings table lives in DDR (0x40a955e0).
|
|  Two detours, each writes ONE char to /LP.TXT (overwrite mode "w", flushed by close)
|  at a safe, non-audio-tight point:
|    'A'  reload orchestrator FUN_4009083c entry  (start of load, BEFORE per-slot CF reads)
|    'B'  end-of-load re-sync   FUN_400238a4 entry (after the slot loops)
|
|  After a hung load: /LP.TXT == 'A' -> hung inside the reload orchestrator's slot loop;
|  == 'B' -> reached the re-sync (hung in/after it). Each stub saves ALL registers around
|  the CF call, then replicates its 8 displaced bytes and resumes.
|
|  Detours (8 bytes each, jmp+nop):
|   0x4009083c: 4fefffd4 48d77cfc  -> lea -0x2c(sp),sp ; movem.l d2-d7/a2-a6,(sp) ; resume 0x40090844
|   0x400238a4: 2f0a 4eb94009b220  -> move.l a2,-(sp) ; jsr 0x4009b220           ; resume 0x400238ac
| =====================================================================

reload_stub:
    lea     -0x3c(%sp), %sp           | ColdFire movem needs (sp), not -(sp)
    movem.l %d0-%d7/%a0-%a6, (%sp)
    moveq   #0x41, %d0                | 'A'
    jsr     write_marker
    movem.l (%sp), %d0-%d7/%a0-%a6
    lea     0x3c(%sp), %sp
    lea     -0x2c(%sp), %sp           | displaced
    movem.l %d2-%d7/%a2-%a6, (%sp)    | displaced
    jmp     0x40090844

resync_stub:
    lea     -0x3c(%sp), %sp
    movem.l %d0-%d7/%a0-%a6, (%sp)
    moveq   #0x42, %d0                | 'B'
    jsr     write_marker
    movem.l (%sp), %d0-%d7/%a0-%a6
    lea     0x3c(%sp), %sp
    move.l  %a2, -(%sp)               | displaced
    jsr     0x4009b220                | displaced
    jmp     0x400238ac

| ---- write_marker: d0.b -> single char in /LP.TXT (open"w"/write/close) ----
write_marker:
    move.b  %d0, mbuf
    move.l  #0x200, -(%sp)
    move.l  #0x460261e0, -(%sp)
    pea     0x400b328b               | mode "w"
    pea     lppath
    pea     fh
    jsr     0x40016864               | open
    lea     0x14(%sp), %sp
    tst.l   %d0
    blt.b   wm_ret
    move.l  #1, -(%sp)
    pea     mbuf
    pea     fh
    jsr     0x400166b8               | write
    lea     0xc(%sp), %sp
    pea     fh
    jsr     0x4001677c               | close
    addq.l  #4, %sp
wm_ret:
    rts

    .balign 2
lppath: .asciz "/LP.TXT"
    .balign 4
mbuf:   .space 4
fh:     .space 0x40
