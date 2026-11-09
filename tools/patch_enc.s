| enc_* — moving an encoder on a track that is still in transition makes that track adopt
| the destination Part immediately (spec point (c): you hear the jump at that moment).
|
| REPLACES the GUI-in-transition patch, which did the opposite: it wrote edits into the
| SOURCE Part and deliberately kept the track dirty. It also overrode shared globals and
| used a single-slot return hook that crashed the unit. This touches only the edited
| track's voice buffer and its two index bytes, and returns through the normal path.
|
| THERE ARE FIVE ENCODER EDITORS, not one. The first version hooked only FUN_40052e98 and
| the feature appeared dead on hardware, because whichever parameter page the user was on
| routed through a sibling. They are the same shape -- same prologue idiom, args fetched
| from the stack, both DAT_100b14cc (current track) and DAT_100b14cf (displayed pattern) --
| but each reserves a different frame and saves a different register set, so each needs its
| own trampoline replaying its own displaced prologue:
|
|   0x40052e98   lea -0x20,sp ; movem.l d2-d7/a2-a3   -> resume 0x40052ea0
|   0x40052ae8   lea -0x20,sp ; movem.l d2-d7/a2-a3   -> resume 0x40052af0
|   0x40053498   lea -0x24,sp ; movem.l d2-d7/a2-a4   -> resume 0x400534a0
|   0x40053a68   lea -0x2c,sp ; movem.l d2-d7/a2-a6   -> resume 0x40053a70
|   0x4005435c   lea -0x28,sp ; movem.l d2-d7/a2-a5   -> resume 0x40054364
|
| Each is a 6-byte jmp over an 8-byte prologue; the 2 leftover bytes are dead because the
| trampoline resumes at +8.
|
| How the destination parameters are recovered: by the time the encoder moves they no
| longer exist -- apply_part computed them at the pattern change and restore_stub then
| overwrote them, which is exactly how the track stays protected. So restore_stub snapshots
| them on the way past, at the instant the voice buffer still holds the destination values,
| into DEST_SNAP; enc_apply copies them back.
|
| enc_apply saves every register it touches: it runs BEFORE each editor's movem, so a
| clobbered register would be handed to the editor and stored as if it were the caller's.

    .equ F_LAZY,     0x800000d8      | PERSONALIZE: LAZY TRANSITIONS
    .equ CUR_TRACK,  0x100b14cc
    .equ TRK_BANK,   0x8000182a      | per-track bank[8]  (apply_part arg 1, via 0x80001828)
    .equ TRK_PART,   0x80001832      | per-track part[8]  (apply_part arg 2, via 0x80001829)
    .equ ACT_BANK,   0x80000002      | active bank (0..15)
    .equ ACT_PART,   0x80000003      | active part (0..3)
    .equ VOICE,      0x80000a50      | voice buffer, 0x40 per track
    .include "tools/patch_ram.inc"
    .equ DEST_SNAP,  LZ_DEST         | destination params parked by restore_stub (0x200 B)

    .cpu 5407
    .text
    .global _start
_start:

| ---------------- trampolines, one per editor ----------------
    .global enc_e98, enc_ae8, enc_498, enc_a68, enc_35c
enc_e98:
    bsr.w   enc_apply
    .short  0x4fef, 0xffe0          | lea -0x20(a7),a7
    .short  0x48d7, 0x0cfc          | movem.l d2-d7/a2-a3,(a7)
    jmp     0x40052ea0

enc_ae8:
    bsr.w   enc_apply
    .short  0x4fef, 0xffe0
    .short  0x48d7, 0x0cfc
    jmp     0x40052af0

enc_498:
    bsr.w   enc_apply
    .short  0x4fef, 0xffdc          | lea -0x24(a7),a7
    .short  0x48d7, 0x1cfc          | movem.l d2-d7/a2-a4,(a7)
    jmp     0x400534a0

enc_a68:
    bsr.w   enc_apply
    .short  0x4fef, 0xffd4          | lea -0x2c(a7),a7
    .short  0x48d7, 0x7cfc          | movem.l d2-d7/a2-a6,(a7)
    jmp     0x40053a70

enc_35c:
    bsr.w   enc_apply
    .short  0x4fef, 0xffd8          | lea -0x28(a7),a7
    .short  0x48d7, 0x3cfc          | movem.l d2-d7/a2-a5,(a7)
    jmp     0x40054364

| ---------------- shared logic ----------------
| A track is in transition when restore_stub protected it (LZ_SNAPOK) and stock has not
| re-applied it since: its (bank, part) still differs from the active one. Stock tests both
| bytes the same way (0x40052c50); testing only the bank missed every same-bank part change.
enc_apply:
    lea     -0x18(%sp),%sp          | ColdFire: no movem with -(An)
    .short  0x48d7, 0x030f          | movem.l d0-d3/a0-a1,(sp)

    tst.l   F_LAZY
    beq.b   ea_out                  | feature off -> stock editor

    moveq   #0,%d0
    move.b  CUR_TRACK,%d0
    andi.l  #7,%d0                  | 8 tracks; clamp so a stray value cannot index out
    move.l  %d0,%d2
    jsr     LZ_DIRTY                | in the scene block (patch_scene2.s); address from the build
    beq.b   ea_out                  | not in transition -> nothing to do

    move.w  %sr,%d3                 | the pattern change runs in another task: commit the
    move.w  #0x2700,%sr             | track's buffer and index bytes in one piece
    move.l  %d2,%d0
    lsl.l   #6,%d0                  | track * 0x40
    lea     DEST_SNAP,%a0
    adda.l  %d0,%a0
    lea     VOICE,%a1
    adda.l  %d0,%a1
    moveq   #16,%d1                 | 0x40 bytes = 16 longs
ea_copy:
    move.l  (%a0)+,(%a1)+
    subq.l  #1,%d1
    bne.b   ea_copy

    mvz.b   ACT_BANK,%d0
    lea     TRK_BANK,%a0
    move.b  %d0,(%a0,%d2.l)         | the track is now on the active bank ...
    mvz.b   ACT_PART,%d0
    lea     TRK_PART,%a0
    move.b  %d0,(%a0,%d2.l)         | ... and part
    lea     LZ_SNAPOK,%a0
    clr.b   (%a0,%d2.l)             | snapshot consumed
    move.w  %d3,%sr

ea_out:
    .short  0x4cd7, 0x030f          | movem.l (sp),d0-d3/a0-a1
    lea     0x18(%sp),%sp
    rts
