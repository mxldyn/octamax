    .cpu 5407
    .text
| =====================================================================
|  RAM SCAN probe (Phase A, read-only) — on R11.
|
|  Goal: source a free hole for the STATIC-pool extension (128->256):
|    - 0x448 settings table (0x100d5b30) -> needs 0x44800 (274 KB)
|    - 0x2c  state table    (0x46c90a78) -> needs 0x2c00  (11 KB)
|  NOTES.md prescribes runtime reconnaissance: paint/scan candidate windows,
|  operate normally, report which stay untouched. Phase A does NO writes to RAM
|  under test -- it only READS proven-mapped regions and reports the longest run
|  of all-zero 64 KB blocks (unused BSS that static constant-scans miss).
|
|  Regions scanned (all mapped -> zero bus-fault risk):
|    R1 0x10000000 .. 0x10800000  (128 blk)  metadata region, proven-mapped half
|    R2 0x46000000 .. 0x47000000  (256 blk)  DDR: pool tail + recorder/app structs
|    R3 0x40000000 .. 0x40b00000  (176 blk)  DDR: code + BSS + bank buffers + pool head
|
|  Trigger: RELOAD confirm (FUN_40063bf8). On YES -> scan + write /RAMSCAN.TXT,
|  then return WITHOUT doing the reload (the gesture is repurposed as "dump").
|  Map chars: '.' = all-zero 64 KB block (free candidate), '#' = has nonzero byte.
| =====================================================================

recon_trigger:                  | detour FUN_40063bf8 (entry 4aaf0004 661c)
    tst.l   4(%sp)
    bne.b   rt_orig
    lea     -0x20(%sp), %sp
    movem.l %d2-%d7/%a2-%a3, (%sp)
    jsr     recon_run
    jsr     ram_flush
    movem.l (%sp), %d2-%d7/%a2-%a3
    lea     0x20(%sp), %sp
    clr.l   %d0
    rts
rt_orig:
    jmp     0x40063c16          | original bne target

| ---- run the three region scans, build the text log in logbuf ----
recon_run:
    lea     logbuf, %a3
    | R1
    pea     0x10000000
    pea     fmt_hdr
    move.l  %a3, -(%sp)
    jsr     0x40013a08
    lea     0xc(%sp), %sp
    adda.l  %d0, %a3
    movea.l #0x10000000, %a2
    move.l  #0x80, %d3
    jsr     scan_region
    move.l  %d6, -(%sp)
    move.l  %d5, -(%sp)
    pea     fmt_sum
    move.l  %a3, -(%sp)
    jsr     0x40013a08
    lea     0x10(%sp), %sp
    adda.l  %d0, %a3
    | R2
    pea     0x46000000
    pea     fmt_hdr
    move.l  %a3, -(%sp)
    jsr     0x40013a08
    lea     0xc(%sp), %sp
    adda.l  %d0, %a3
    movea.l #0x46000000, %a2
    move.l  #0x100, %d3
    jsr     scan_region
    move.l  %d6, -(%sp)
    move.l  %d5, -(%sp)
    pea     fmt_sum
    move.l  %a3, -(%sp)
    jsr     0x40013a08
    lea     0x10(%sp), %sp
    adda.l  %d0, %a3
    | R3
    pea     0x40000000
    pea     fmt_hdr
    move.l  %a3, -(%sp)
    jsr     0x40013a08
    lea     0xc(%sp), %sp
    adda.l  %d0, %a3
    movea.l #0x40000000, %a2
    move.l  #0xb0, %d3
    jsr     scan_region
    move.l  %d6, -(%sp)
    move.l  %d5, -(%sp)
    pea     fmt_sum
    move.l  %a3, -(%sp)
    jsr     0x40013a08
    lea     0x10(%sp), %sp
    adda.l  %d0, %a3
    | logpos = a3 - logbuf
    move.l  %a3, %d0
    lea     logbuf, %a0
    sub.l   %a0, %d0
    move.l  %d0, (logpos).l
    rts

| ---- scan_region: a2=base, d3=nblocks, a3=dst ; out d5=best-run, d6=start-blk ----
scan_region:
    clr.l   %d4                 | cur run
    clr.l   %d5                 | best run
    clr.l   %d6                 | best start
    clr.l   %d7                 | block idx
sr_block:
    movea.l %a2, %a0
    move.l  #0x4000, %d1        | 0x10000/4 words
    clr.l   %d2
sr_word:
    or.l    (%a0)+, %d2
    subq.l  #1, %d1
    bne.b   sr_word
    tst.l   %d2
    bne.b   sr_used
    moveq   #0x2e, %d0          | '.'
    move.b  %d0, (%a3)+
    addq.l  #1, %d4
    cmp.l   %d5, %d4
    bls.b   sr_adv
    move.l  %d4, %d5            | best = cur
    move.l  %d7, %d6
    sub.l   %d4, %d6
    addq.l  #1, %d6             | start = idx - cur + 1
    bra.b   sr_adv
sr_used:
    moveq   #0x23, %d0          | '#'
    move.b  %d0, (%a3)+
    clr.l   %d4
sr_adv:
    adda.l  #0x10000, %a2
    addq.l  #1, %d7
    cmp.l   %d3, %d7
    bne.b   sr_block
    rts

| ---- write logbuf[0..logpos] to /RAMSCAN.TXT (CF) ----
ram_flush:
    move.l  #0x200, -(%sp)
    move.l  #0x460261e0, -(%sp)
    pea     0x400b328b          | mode "w"
    pea     logpath
    pea     fh
    jsr     0x40016864
    lea     0x14(%sp), %sp
    tst.l   %d0
    blt.b   rf_done
    move.l  (logpos).l, -(%sp)
    pea     logbuf
    pea     fh
    jsr     0x400166b8
    lea     0xc(%sp), %sp
    pea     fh
    jsr     0x4001677c
    addq.l  #4, %sp
rf_done:
    rts

    .balign 4
logpos:  .long 0
    .balign 2
fmt_hdr: .asciz "\n%x [64k]:\n"
    .balign 2
fmt_sum: .asciz "\nrun=%x @blk%x\n"
    .balign 2
logpath: .asciz "/RAMSCAN.TXT"
    .balign 4
fh:      .space 0x40
    .balign 4
logbuf:  .space 0x300
