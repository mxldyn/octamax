    .cpu 5407
    .text
    .include "tools/patch_ram.inc"
    .if LZ_DEST - LZ_SAVE - 0x400
    .error "restore_stub addresses LZ_DEST as 0x400(LZ_SAVE)"
    .endif
| ===== SAVE_STUB (entrada de FUN_40009094) =====
save_stub:
    | gate: LAZY TRANSITIONS apagado -> comportamiento de fabrica
    tst.l 0x800000d8
    beq.w sv_stock
    | bulk-save buffers de voz: 0x80000a50 -> LZ_SAVE (0x200 B = 128 longs)
    lea 0x80000a50, %a0
    lea LZ_SAVE, %a1
    move.l #128, %d0
sv1:
    move.l (%a0)+, (%a1)+
    subq.l #1, %d0
    bne.b sv1
    | bulk-save per_track (16 B): 0x8000182a -> LZ_PART
    lea 0x8000182a, %a0
    lea LZ_PART, %a1
    moveq #4, %d0
sv2:
    move.l (%a0)+, (%a1)+
    subq.l #1, %d0
    bne.b sv2
    | flags de "sonando" por track -> LZ_PLAYING
    moveq #0, %d1
    lea 0x800049d8, %a0
    lea LZ_PLAYING, %a1
sv3:
    move.b (%a0), %d0
    move.b %d0, (%a1)+
    lea 0xa8(%a0), %a0
    addq.l #1, %d1
    moveq #8, %d0
    cmp.l %d1, %d0
    bne.b sv3
    | instrucciones desplazadas de la entrada + continúa
sv_stock:
    .short 0x4fef, 0xff98
    .short 0x48d7, 0x7cfc
    jmp 0x4000909c
| ===== RESTORE_STUB (rts de FUN_40009094) =====
| Runs at apply_part's only exit (its tail `jmp 0x40000c3c` at 0x40009664 is retargeted here),
| after the epilogue: only d0/d1/a0/a1 are scratch, and post()'s arguments stay on the stack.
| apply_part(bank, part) stored its arguments in 0x80001828/29. A sounding track is kept on its
| SOURCE parameters only when its (bank, part) actually changes: apply_part is also called with
| the active part to re-apply edits (0x4002b59a, 0x4002b8f8, 0x4004a8fc, scene assign), and those
| must stand. A track that never had a part applied (bank byte 0xFF, boot) has nothing to keep.
| LZ_SNAPOK[t] says the track is protected and LZ_DEST[t] holds its destination parameters.
restore_stub:
    tst.l 0x800000d8
    beq.w rs_stock
    moveq #0, %d1
rs0:
    lea LZ_SNAPOK, %a0
    clr.b (0,%a0,%d1:l)
    lea LZ_PLAYING, %a0
    move.b (0,%a0,%d1:l), %d0
    beq.w rs_next
    lea LZ_PART, %a0
    mvs.b (0,%a0,%d1:l), %d0          | saved bank of this track
    bmi.w rs_next                     | 0xFF: never applied -> nothing to keep
    cmp.b 0x80001828, %d0
    bne.b rs_keep                     | bank changes -> protect
    lea LZ_PART_B, %a0
    mvz.b (0,%a0,%d1:l), %d0
    cmp.b 0x80001829, %d0
    beq.w rs_next                     | same bank and part: a re-apply, let it stand
rs_keep:
    lea LZ_SNAPOK, %a0
    moveq #1, %d0
    move.b %d0, (0,%a0,%d1:l)
    | one pass over the track's 0x40 B: park the DESTINATION params (what apply_part just wrote)
    | in LZ_DEST for enc_apply, and put the SOURCE params back. LZ_DEST = LZ_SAVE + 0x400.
    move.l %d2, -(%sp)                | d2 is the caller's: borrow it below the live stack
    move.l %d1, %d0
    lsl.l #6, %d0
    lea 0x80000a50, %a0
    add.l %d0, %a0
    lea LZ_SAVE, %a1
    add.l %d0, %a1
    moveq #16, %d0
rs_cp:
    move.l (%a0), %d2
    move.l %d2, 0x400(%a1)
    move.l (%a1)+, (%a0)+
    subq.l #1, %d0
    bne.b rs_cp
    move.l (%sp)+, %d2
    | and the track's (bank, part), so stock re-applies the destination on its next trig
    lea LZ_PART, %a0
    move.b (0,%a0,%d1:l), %d0
    lea 0x8000182a, %a1
    move.b %d0, (0,%a1,%d1:l)
    lea LZ_PART_B, %a0
    move.b (0,%a0,%d1:l), %d0
    lea 0x80001832, %a1
    move.b %d0, (0,%a1,%d1:l)
rs_next:
    addq.l #1, %d1
    moveq #8, %d0
    cmp.l %d1, %d0
    bne.w rs0
    | tail-call the displaced target (post)
rs_stock:
    jmp 0x40000c3c
