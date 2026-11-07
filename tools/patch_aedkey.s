| patch_aedkey -- the [AUDIO EDITOR] key opens the editor on the current track's slot.
|
| The AED edits whatever (type, slot) was last handed to the publisher 0x4006de34. Every way of
| opening it publishes first -- the slot list (0x4003d434), the recorder (0x4002ee2c), the file
| browser (0x40078a94), [TRACK]+AED (0x40083dae) -- EXCEPT the plain AED key toggle 0x4006e274 and
| the open-on-the-slices-page shortcut 0x4006e250. Those reuse the slot published when the track
| was last SELECTED (0x40083bf8 -> 0x40083c64). Anything that changes the current track's slot
| without a re-select -- a track copy/paste, a part reload -- leaves the editor on the old slot:
| the title names it and the waveform/slices are its, while the track plays another sample
| (HW-measured 2026-11-07 with build_diag_wave1: T5 slot 4 -> 28 by a copy, AED opened STATIC 004
| and built slot 4's waveform; the open itself succeeded).
|
| Fix: when either key OPENS the editor (it is closed), publish the track's (type, slot) first,
| byte for byte the way 0x40083c64 does. Closing, and every other way in, is stock.

    .equ AEDOPEN,  0x460e5e4c       | non-zero = the editor is open (its window handle)
    .equ BANKPTR,  0x46c82456       | -> bank base
    .equ G_PART,   0x100b14cf       | current part
    .equ G_TRACK,  0x100b14cc       | current audio track
    .equ PUBLISH,  0x4006de34       | (type, slot): the editor's current-slot setter
    .equ OPEN,     0x4006e160
    .equ CLOSE,    0x4006dd18
    .equ PAGEOK,   0x4006db58       | (page) -> page available for the published type
    .equ SLICES_RESUME, 0x4006e258  | after the displaced pea 1 ; jsr PAGEOK

    .text
    .global _start
_start:

| 0x4006e274 (key-table entry at 0x400c080e). Stock: tstl AEDOPEN ; beqs open ; bra CLOSE ; bra OPEN
    .global ak_toggle
ak_toggle:
    tst.l   AEDOPEN
    bne.b   1f
    bsr.b   ak_publish
    jmp     OPEN
1:  jmp     CLOSE

| 0x4006e250 (key-table entry at 0x400bf9b8): pea 1 ; jsr PAGEOK ; addq ; tst ; beq ; jsr OPEN ; ...
| Publish before the page check so it judges the track's own machine type.
    .global ak_slices
ak_slices:
    tst.l   AEDOPEN
    bne.b   1f
    bsr.b   ak_publish
1:  pea     1                       | displaced: pea 1 ; jsr PAGEOK
    jsr     PAGEOK
    jmp     SLICES_RESUME

| ak_publish: PUBLISH(type, slot) of the current track, as 0x40083c64..0x40083cac. Preserves all
| registers.
ak_publish:
    lea     -20(%sp),%sp
    movem.l %d0-%d1/%a0-%a2,(%sp)
    movea.l BANKPTR,%a2
    moveq   #0,%d0
    move.b  G_PART,%d0
    moveq   #0,%d1
    move.b  G_TRACK,%d1
    movea.l %d1,%a1                 | a1 = track
    move.l  #6322,%d1
    muls.l  %d1,%d0                 | d0 = part * 6322
    lea     (%a2,%d0.l),%a0
    adda.l  %a1,%a0
    adda.l  #0x8eda2,%a0
    mvs.b   (%a0),%d1               | d1 = machine type (signed, as stock)
    lea     (%a1,%a1.l*4),%a1       | track * 5
    adda.l  %d0,%a1
    adda.l  %a1,%a2
    adda.l  %d1,%a2
    adda.l  #0x8f04a,%a2
    moveq   #0,%d0
    move.b  (%a2),%d0               | slot byte for that type (zero-extended: >= 128 survives)
    move.l  %d0,-(%sp)
    move.l  %d1,-(%sp)
    jsr     PUBLISH
    addq.l  #8,%sp
    movem.l (%sp),%d0-%d1/%a0-%a2
    lea     20(%sp),%sp
    rts
