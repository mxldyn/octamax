    .cpu 5407
    .text
| =====================================================================
|  CANARY confirm probe (on R11) — verify the DDR free window is truly unused.
|
|  Scans found a ~10.7 MB free window 0x47510000..0x47FC0000. This paints a canary at
|  the exact spot the relocated static tables would live (0x40a955e0, 512 KB = 8x64 KB)
|  and, on a later CHANGE, checks whether it survived operation -> proves nothing else
|  (heap/pool/allocator) uses it.
|
|  Two-phase, state in g_state (cave, resets on reflash):
|   - CHANGE #1 (g_state==0): PAINT 0x5A5A5A5A across 0x40a955e0..0x47880000, set g_state=1.
|   - CHANGE #2+ (g_state==1): CHECK each 64 KB block (all words still 0x5A5A5A5A?) -> map
|     ('.'=intact, '#'=modified) + longest intact run, write /CANARY.TXT at the resync.
|  All in mapped DDR -> no bus-fault; paint/check are ~2 ms -> no timing issue.
|
|  Use: flash -> CHANGE to a sibling (paints) -> operate hard (record, load samples,
|  change patterns) -> CHANGE again (checks + writes /CANARY.TXT). "........" = fully
|  survived = the table home is safe.
| =====================================================================

| Pool base is moved 0x40a955e0 -> 0x40af55e0 (in the builder, blanket 4-byte replace)
| + page count 0x390A -> 0x38CA, so the pool physically starts 384 KB higher and
| [0x40a955e0, 0x40af55e0) is below it, referenced by nothing = reserved. The canary
| below paints/checks that reserved region to confirm it stays untouched.

dump_arm:                       | detour FUN_40063e28 (CHANGE confirm, entry 4aaf0004 6618)
    tst.l   4(%sp)
    bne.b   da_abort
    lea     -0x3c(%sp), %sp
    movem.l %d0-%d7/%a0-%a6, (%sp)
    tst.l   g_state
    bne.b   da_check
    jsr     paint_canary
    moveq   #1, %d0
    move.l  %d0, g_state
    bra.b   da_done
da_check:
    jsr     check_canary
    moveq   #1, %d0
    move.l  %d0, g_dump
da_done:
    movem.l (%sp), %d0-%d7/%a0-%a6
    lea     0x3c(%sp), %sp
    jmp     0x40063e2e          | stock CHANGE confirm body
da_abort:
    jmp     0x40063e46

dump_resync:                    | detour FUN_400238a4 (resync, entry 2f0a 4eb9 4009b220)
    tst.l   g_dump
    beq.b   dz_cont
    clr.l   g_dump
    lea     -0x3c(%sp), %sp
    movem.l %d0-%d7/%a0-%a6, (%sp)
    jsr     write_map
    movem.l (%sp), %d0-%d7/%a0-%a6
    lea     0x3c(%sp), %sp
dz_cont:
    move.l  %a2, -(%sp)
    jsr     0x4009b220
    jmp     0x400238ac

paint_canary:                   | write 0x5A5A5A5A to 0x40a955e0..0x47880000 (512 KB)
    movea.l #0x40a955e0, %a0
    move.l  #0x18000, %d0       | 0x80000/4 longwords
    move.l  #0x5a5a5a5a, %d1
pc_lp:
    move.l  %d1, (%a0)+
    subq.l  #1, %d0
    bne.b   pc_lp
    rts

check_canary:                   | build survivor map for 0x40a955e0, 8 blocks -> logbuf
    lea     logbuf, %a3
    pea     0x40a955e0
    pea     fmt_hdr
    move.l  %a3, -(%sp)
    jsr     0x40013a08
    lea     0xc(%sp), %sp
    adda.l  %d0, %a3
    movea.l #0x40a955e0, %a2
    move.l  #6, %d3
    jsr     scan_canary
    move.l  %d6, -(%sp)
    move.l  %d5, -(%sp)
    pea     fmt_sum
    move.l  %a3, -(%sp)
    jsr     0x40013a08
    lea     0x10(%sp), %sp
    adda.l  %d0, %a3
    move.l  %a3, %d0
    lea     logbuf, %a0
    sub.l   %a0, %d0
    move.l  %d0, (logpos).l
    rts

| ---- scan_canary: a2=base, d3=nblocks, a3=dst ; block intact = all words==0x5A5A5A5A ----
| out d5=best intact run, d6=start block
scan_canary:
    clr.l   %d4
    clr.l   %d5
    clr.l   %d6
    clr.l   %d7
sc_block:
    movea.l %a2, %a0
    move.l  #0x4000, %d1
    clr.l   %d2
sc_word:
    move.l  (%a0)+, %d0
    eori.l  #0x5a5a5a5a, %d0
    or.l    %d0, %d2
    subq.l  #1, %d1
    bne.b   sc_word
    tst.l   %d2
    bne.b   sc_mod
    moveq   #0x2e, %d0          | '.' intact
    move.b  %d0, (%a3)+
    addq.l  #1, %d4
    cmp.l   %d5, %d4
    bls.b   sc_adv
    move.l  %d4, %d5
    move.l  %d7, %d6
    sub.l   %d4, %d6
    addq.l  #1, %d6
    bra.b   sc_adv
sc_mod:
    moveq   #0x23, %d0          | '#' modified
    move.b  %d0, (%a3)+
    clr.l   %d4
sc_adv:
    adda.l  #0x10000, %a2
    addq.l  #1, %d7
    cmp.l   %d3, %d7
    bne.b   sc_block
    rts

| ---- write_map: logbuf[0..logpos] -> /CANARY.TXT in <=256 B chunks ----
write_map:
    move.l  #0x200, -(%sp)
    move.l  #0x460261e0, -(%sp)
    pea     0x400b328b          | mode "w"
    pea     canarypath
    pea     fh
    jsr     0x40016864
    lea     0x14(%sp), %sp
    tst.l   %d0
    blt.b   wm_done
    lea     logbuf, %a2
    move.l  (logpos).l, %d7
wm_loop:
    tst.l   %d7
    beq.b   wm_close
    move.l  #0x100, %d6
    cmp.l   %d7, %d6
    bls.b   wm_w
    move.l  %d7, %d6
wm_w:
    move.l  %d6, -(%sp)
    move.l  %a2, -(%sp)
    pea     fh
    jsr     0x400166b8
    lea     0xc(%sp), %sp
    adda.l  %d6, %a2
    sub.l   %d6, %d7
    bra.b   wm_loop
wm_close:
    pea     fh
    jsr     0x4001677c
    addq.l  #4, %sp
wm_done:
    rts

    .balign 4
g_state: .long 0
g_dump:  .long 0
logpos:  .long 0
    .balign 2
fmt_hdr: .asciz "\n%x canary:\n"
    .balign 2
fmt_sum: .asciz "\nintact_run=%x @blk%x\n"
    .balign 2
canarypath: .asciz "/CANARY.TXT"
    .balign 4
fh:      .space 0x40
    .balign 4
logbuf:  .space 0x300
