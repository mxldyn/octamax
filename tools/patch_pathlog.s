    .cpu 5407
    .text
| =====================================================================
|  PATH logger (on blockmove base). Hook every path-taking FS function at its entry, log
|  arg0 (the path at sp@4) with a 1-char tag to a DDR ring buffer, dumped to /PATHS.TXT on
|  a CHANGE. Whichever open/stat the project load uses, we capture the failing path.
|
|  Tags: O=open(0x4001b570) S=stat(0x4001c1bc) 7=0x4001b724 9=0x40019900
|        E=0x40018e40 C=0x4001858c 4=0x40018444
|  Each stub reads sp@4 BEFORE its prologue (arg0=path for all), logs, replicates the exact
|  displaced bytes, and jumps to the resume address.
| =====================================================================

    .equ LOG_START, 0x40ae0000
    .equ LOG_END,   0x40af0000

| ---- CHANGE-confirm dump ----
dump_hook:
    tst.l   4(%sp)
    bne.b   dh_abort
    lea     -0x3c(%sp), %sp
    movem.l %d0-%d7/%a0-%a6, (%sp)
    jsr     write_log
    move.l  #LOG_START, %d0          | reset -> next capture is fresh (clears boot noise)
    move.l  %d0, g_logptr
    movem.l (%sp), %d0-%d7/%a0-%a6
    lea     0x3c(%sp), %sp
dh_body:
    jmp     0x40063e2e
dh_abort:
    jmp     0x40063e46

| ---- the 7 path-function entry stubs ----
h_b570:
    moveq   #0x4f, %d1              | 'O'
    move.l  4(%sp), %a0
    bsr.w   log_a0
    .byte   0x4f,0xef,0xfe,0xb8, 0x48,0xd7,0x04,0x1c
    jmp     0x4001b578
h_c1bc:
    moveq   #0x53, %d1             | 'S'
    move.l  4(%sp), %a0
    bsr.w   log_a0
    .byte   0x4e,0x56,0xfe,0xc8, 0x48,0x6e,0xfe,0xca
    jmp     0x4001c1c4
h_b724:
    moveq   #0x37, %d1             | '7'
    move.l  4(%sp), %a0
    bsr.w   log_a0
    .byte   0x4e,0x56,0xfe,0xc8, 0x2f,0x02
    jmp     0x4001b72a
h_19900:
    moveq   #0x39, %d1             | '9'
    move.l  4(%sp), %a0
    bsr.w   log_a0
    .byte   0x4e,0x56,0xff,0xe0, 0x48,0xd7,0x0c,0x3c
    jmp     0x40019908
h_18e40:
    moveq   #0x45, %d1             | 'E'
    move.l  4(%sp), %a0
    bsr.w   log_a0
    .byte   0x4f,0xef,0xff,0xe0, 0x48,0xd7,0x0c,0xfc
    jmp     0x40018e48
h_1858c:
    moveq   #0x43, %d1             | 'C'
    move.l  4(%sp), %a0
    bsr.w   log_a0
    .byte   0x4f,0xef,0xff,0xe0, 0x48,0xd7,0x0c,0xfc
    jmp     0x40018594
h_18444:
    moveq   #0x34, %d1             | '4'
    move.l  4(%sp), %a0
    bsr.w   log_a0
    .byte   0x4f,0xef,0xff,0xd8, 0x48,0xd7,0x3c,0xfc
    jmp     0x4001844c

| ---- shared logger: d1=tag, a0=path string -> LOG_BUF ----
log_a0:
    move.l  g_logptr, %a1
    move.l  #LOG_END, %d0
    cmp.l   %d0, %a1
    bcc.b   la_ret
    move.b  %d1, (%a1)+           | tag
    moveq   #0x20, %d0
    move.b  %d0, (%a1)+           | space
la_cp:
    move.b  (%a0)+, %d0
    beq.b   la_nl
    move.b  %d0, (%a1)+
    bra.b   la_cp
la_nl:
    moveq   #0x0a, %d0
    move.b  %d0, (%a1)+
    move.l  %a1, g_logptr
la_ret:
    rts

| ---- write LOG_START..g_logptr -> /PATHS.TXT ----
write_log:
    move.l  g_logptr, %d7
    movea.l #LOG_START, %a2
    move.l  #0x200, -(%sp)
    move.l  #0x460261e0, -(%sp)
    pea     0x400b328b            | "w"
    pea     lppath
    pea     fh
    jsr     0x40016864
    lea     0x14(%sp), %sp
    tst.l   %d0
    blt.b   wl_done
    move.l  %a2, %d6
wl_loop:
    move.l  %d7, %d5
    sub.l   %d6, %d5
    ble.b   wl_close
    move.l  #0x100, %d4
    cmp.l   %d5, %d4
    bls.b   wl_w
    move.l  %d5, %d4
wl_w:
    move.l  %d4, -(%sp)
    move.l  %d6, -(%sp)
    pea     fh
    jsr     0x400166b8
    lea     0xc(%sp), %sp
    add.l   %d4, %d6
    bra.b   wl_loop
wl_close:
    pea     fh
    jsr     0x4001677c
    addq.l  #4, %sp
wl_done:
    rts

    .balign 4
g_logptr: .long LOG_START
g_dumped: .long 0
    .balign 2
lppath:   .asciz "/PATHS.TXT"
    .balign 4
fh:       .space 0x40
