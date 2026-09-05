    .cpu 5407
    .text
| =====================================================================
|  BLOCK dumper (on blockmove base). After a (failed) project load, dump the relocated
|  settings block from DDR to /BLK.BIN on a CHANGE, to see if the load populated it.
|  Dumps [0x40ab9c20, +0x4000) = the STATIC table start (relocated 0x100d5b30), where the
|  static sample slots live -> readable filenames = parse OK; zeros = parse never ran.
|
|  Detour CHANGE-confirm 0x40063e28 (4aaf0004 6618) -> dump, then stock body / abort.
| =====================================================================

    .equ DUMP_SRC, 0x40ab9c20      | static table base in DDR
    .equ DUMP_LEN, 0x4000

dump_hook:
    tst.l   4(%sp)
    bne.b   dh_abort
    tst.l   g_dumped
    bne.b   dh_body
    moveq   #1, %d0
    move.l  %d0, g_dumped
    lea     -0x3c(%sp), %sp
    movem.l %d0-%d7/%a0-%a6, (%sp)
    jsr     write_blk
    movem.l (%sp), %d0-%d7/%a0-%a6
    lea     0x3c(%sp), %sp
dh_body:
    jmp     0x40063e2e
dh_abort:
    jmp     0x40063e46

write_blk:
    move.l  #0x200, -(%sp)
    move.l  #0x460261e0, -(%sp)
    pea     0x400b328b              | mode "w"
    pea     blkpath
    pea     fh
    jsr     0x40016864              | open
    lea     0x14(%sp), %sp
    tst.l   %d0
    blt.b   wb_done
    movea.l #DUMP_SRC, %a2
    move.l  #DUMP_LEN, %d7
wb_loop:
    tst.l   %d7
    ble.b   wb_close
    move.l  #0x100, %d6
    cmp.l   %d7, %d6
    bls.b   wb_w
    move.l  %d7, %d6
wb_w:
    move.l  %d6, -(%sp)
    move.l  %a2, -(%sp)
    pea     fh
    jsr     0x400166b8              | write
    lea     0xc(%sp), %sp
    add.l   %d6, %a2
    sub.l   %d6, %d7
    bra.b   wb_loop
wb_close:
    pea     fh
    jsr     0x4001677c              | close
    addq.l  #4, %sp
wb_done:
    rts

    .balign 4
g_dumped: .long 0
    .balign 2
blkpath:  .asciz "/BLK.BIN"
    .balign 4
fh:       .space 0x40
