    .cpu 5407
    .text
| =====================================================================
|  OPEN-PATH logger (on blockmove base). The project load now runs (no hang) but reports
|  FILE NOT FOUND and loads nothing. Capture every path passed to open() FUN_40016864 into
|  a DDR ring buffer (fast, no CF during load), then dump it to /OPENLOG.TXT on a CHANGE.
|  The last path logged before the abort is the file that wasn't found.
|
|  LOG_BUF = 0x40ae0000..0x40af0000 (in the reserved DDR window, above the settings block,
|  boot-zeroed). g_logptr walks it. open_hook uses only scratch d0/a0/a1.
|
|  Detours:
|   open        0x40016864 (4fefff f4 48d70c04) -> log path (sp@8), then displaced, resume 0x4001686c
|   CHANGE cfm  0x40063e28 (4aaf0004 6618)       -> dump LOG_BUF, then stock body 0x40063e2e / abort 0x40063e46
| =====================================================================

    .equ LOG_START, 0x40ae0000
    .equ LOG_END,   0x40af0000

| detour of the universal FS open 0x4001b570(path, mode): path = arg0 = sp@(4)
open_hook:
    move.l  4(%sp), %a0             | a0 = path arg (sp@0 ret, sp@4 path)
    move.l  g_logptr, %a1
    move.l  #LOG_END, %d0
    cmp.l   %d0, %a1
    bcc.b   oh_real                 | buffer full -> stop logging
oh_cp:
    move.b  (%a0)+, %d0
    beq.b   oh_nl
    move.b  %d0, (%a1)+
    bra.b   oh_cp
oh_nl:
    moveq   #0x0a, %d0
    move.b  %d0, (%a1)+
    move.l  %a1, g_logptr
oh_real:
    lea     -328(%sp), %sp          | displaced 4fef feb8
    .byte   0x48,0xd7,0x04,0x1c      | displaced movem.l d2-d4/a2,(sp) (exact bytes)
    jmp     0x4001b578

dump_hook:
    tst.l   4(%sp)
    bne.b   dh_abort
    tst.l   g_dumped
    bne.b   dh_body
    moveq   #1, %d0
    move.l  %d0, g_dumped
    lea     -0x3c(%sp), %sp
    movem.l %d0-%d7/%a0-%a6, (%sp)
    jsr     write_log
    movem.l (%sp), %d0-%d7/%a0-%a6
    lea     0x3c(%sp), %sp
dh_body:
    jmp     0x40063e2e
dh_abort:
    jmp     0x40063e46

| ---- write_log: LOG_START..g_logptr -> /OPENLOG.TXT in <=256B chunks ----
write_log:
    move.l  g_logptr, %d7          | snapshot end BEFORE opening (open would log itself)
    movea.l #LOG_START, %a2
    move.l  #0x200, -(%sp)
    move.l  #0x460261e0, -(%sp)
    pea     0x400b328b              | mode "w"
    pea     logpath
    pea     fh
    jsr     0x40016864              | open
    lea     0x14(%sp), %sp
    tst.l   %d0
    blt.b   wl_done
    move.l  %a2, %d6               | d6 = cursor
wl_loop:
    move.l  %d7, %d5
    sub.l   %d6, %d5              | d5 = remaining
    ble.b   wl_close
    move.l  #0x100, %d4
    cmp.l   %d5, %d4
    bls.b   wl_w
    move.l  %d5, %d4
wl_w:
    move.l  %d4, -(%sp)
    move.l  %d6, -(%sp)
    pea     fh
    jsr     0x400166b8            | write
    lea     0xc(%sp), %sp
    add.l   %d4, %d6
    bra.b   wl_loop
wl_close:
    pea     fh
    jsr     0x4001677c            | close
    addq.l  #4, %sp
wl_done:
    rts

    .balign 4
g_logptr: .long LOG_START
g_dumped: .long 0
    .balign 2
logpath:  .asciz "/OPENLOG.TXT"
    .balign 4
fh:       .space 0x40
