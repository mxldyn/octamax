| patch_sliceview — SLICE PLAYHEAD: a readable SRC>SLICES view.
|
|   SLICE PLAYHEAD   0x800000dc   big slice number + progress bar + loop marker
|
| Replaces the 4x16 slice-grid area (x 61..117, y 10..24) of the FUNC+[down] SLICES view
| with: the currently-playing slice number in the 12 px font (centred on x=72), a
| progress bar for the playback position inside the slice, and an XOR vline
| marking the slice's loop point when one is configured. Flag cleared (default) = the
| stock grid, byte for byte.
|
| Data source is the per-track voice struct at 0x800049d8 (stride 0xA8); voice index ==
| track for sample machines. voice@8 is the slot-resolved SETTINGS pointer, so high
| (dual-256) slots need no special handling here. The slice table is SETTINGS+300+
| (slice+1)*12 = {start,end,loop}; entry -1 is the whole-sample trim triple, which makes
| the no-slice case (voice@32 == -1) the same code path. loop < 0 means no loop point.
|
| Redraw: the UI task is event-driven, so playback alone never repaints. The timer task
| (0x40056c40) calls the countdown tick for every type-1 timer message; the 6-byte
| `tstl 0x46104ca8` that follows that call (0x40056c92) is our periodic hook. The stub
| bumps a blink counter and, when the feature is live on screen, posts the 8-byte message
| sv_msg (event 78 -> handler 0x40062d04 -> jsr 0x4004581c = view header+content redraw)
| to the UI queue with the same 0x40000c3c the stock timer task uses. At most one post is
| outstanding (POSTED, cleared by the renderer in the UI task); if the renderer never ran
| (modal open when the event landed), a retry is allowed after 64 ticks so the view can't
| wedge. Posting from this task is stock behaviour (see 0x40056b12 et al).
|
| The render detour sits on `pea 0x400beafa` at 0x40044cf0, AFTER three blit args are on
| the stack: the flag-off path replays the pea and resumes at 0x40044cf6; the flag-on
| path drops those 12 bytes and exits through 0x400453e2 (dirty flag + epilogue), which
| restores d2-d7/a2-fp — so the renderer may clobber callee-saved registers freely.

    .equ F_SLICEVIEW, 0x800000dc    | free word in the battery-backed PERSONALIZE block

    .equ BLINKCTR,  0x80006c68      | long: timer ticks (paces the post retry)
    .equ POSTED,    0x80006c6c      | byte: one redraw message outstanding
    .equ POSTTIME,  0x80006c70      | long: BLINKCTR at last post, for the retry

    .equ VIEW,      0x460d16f0      | FUNC+[down] view index, 3 = SLICES
    .equ MODAL,     0x460d1aec      | non-zero = popup/overlay open
    .equ UIQ,       0x460d17ae      | the UI task's message queue
    .equ POST,      0x40000c3c      | post(queue, msg) — interrupt-masked ring insert

    .equ VOICES,    0x800049d8      | 8 voice structs, stride 0xA8
    .equ CURTRACK,  0x100b14cc      | current audio track byte, 0..7

    .equ SURF,      0x400bf10a      | the 128x64 screen surface
    .equ FONT12,    0x400ba89e      | 12 px font (the big number)
    .equ FILLRECT,  0x40012254      | (surf,x0,y0,x1,y1,mode)
    .equ VLINE,     0x40011b94      | (surf,x,y0,y1,mode)
    .equ DRAWTEXT,  0x40012bd8      | (font,surf,x,y,mode,str)
    .equ DRAWFMT,   0x40013904      | (font,surf,x,y,align,mode,measure,fmt,...)

    .equ RENDER_RESUME, 0x40044cf6  | back into the stock arm, after the replayed pea
    .equ ARM_EXIT,      0x400453e2  | dirty flag + movem-epilogue + rts
    .equ TICK_TSTL,     0x46104ca8  | displaced: tstl TICK_TSTL (flags feed a beq)
    .equ TICK_RESUME,   0x40056c98

    .equ GLYPH_ON,  0x400b5e90
    .equ GLYPH_OFF, 0x400b5e8e

    .equ PAGE,      0x460d16f4      | SLICES page 0..3 (slice = page*16 + trig)
    .equ LEDSETPAIR,0x400131f4      | (id): set both dies of a bicolor pair
    .equ LEDBRIGHT2,0x4001360c      | (id, level): brightness of both dies
    .equ LEDFLASH,  0x40013784      | (id, n): XOR-invert die for n timer ticks (self-flushing)
    .equ LED_RESUME,  0x40044502    | after the displaced moveb at the refresher tail
    .equ BEAT_RESUME, 0x40056f2a    | after the displaced tempo-LED jsr

| bar geometry: box x 84..116, y 13..21; interior x 85..115 (31 px), y 14..20
    .equ BAR_X0,  84
    .equ BAR_X1,  116
    .equ BAR_Y0,  13
    .equ BAR_Y1,  21
    .equ BAR_IW,  31

    .text
    .global _start
_start:

| =============================== renderer ===============================
| Entered from 0x40044cf0 with (y, x, surf) already pushed for the grid blit.
    .global sv_render
sv_render:
    tst.l   F_SLICEVIEW
    bne.b   sv_on
    pea     0x400beafa              | displaced instruction: the grid bitmap arg
    jmp     RENDER_RESUME

sv_on:
    lea     %sp@(12),%sp            | drop the three blit args
    clr.b   POSTED                  | consumed: the tick may post again

| clear the whole grid area (sv_fill args: d0,d1,d2,d4,d5 = x0,y0,x1,y1,mode).
| The number's 15x15 trig-key frame is drawn LAST (sv_frame): drawfmt paints a cleared
| background box around the glyph, which would eat any border drawn before it.
    moveq   #60,%d0
    moveq   #8,%d1
    moveq   #117,%d2
    moveq   #24,%d4
    moveq   #0,%d5
    bsr.w   sv_fill                 | clear (x60..117, y8..24: 2 rows lower than stock's zone)

| resolve this track's voice: a2 = VOICES + track*0xA8
    moveq   #0,%d0
    move.b  CURTRACK,%d0
    move.l  %d0,%d1
    lsl.l   #3,%d0                  | 8t
    lsl.l   #5,%d1                  | 32t
    add.l   %d1,%d0                 | 40t
    lsl.l   #2,%d1                  | 128t
    add.l   %d1,%d0                 | 168t = t*0xA8
    lea     VOICES,%a2
    add.l   %d0,%a2

    tst.b   %a2@(0)                 | voice active?
    beq.w   sv_idle
    move.l  %a2@(8),%d0             | SETTINGS ptr
    beq.w   sv_idle
    move.l  %d0,%a3

| a4 = slice entry = SETTINGS + 300 + (slice+1)*12 ; works for slice == -1 (trim triple)
    move.b  %a2@(32),%d3
    extb.l  %d3                     | d3 = slice, signed
    move.l  %d3,%d0
    addq.l  #1,%d0
    move.l  %d0,%d1
    lsl.l   #3,%d0                  | *8
    lsl.l   #2,%d1                  | *4
    add.l   %d1,%d0                 | *12
    lea     %a3@(300),%a4
    add.l   %d0,%a4

    move.l  %a4@(0),%d6             | d6 = start
    move.l  %a4@(4),%d7             | d7 = end
    sub.l   %d6,%d7                 | d7 = span
    ble.w   sv_number               | degenerate bounds: number only

| ---- bar box: 1 px border, empty interior ----
    moveq   #BAR_X0,%d0
    moveq   #BAR_Y0,%d1
    moveq   #BAR_X1,%d2
    moveq   #BAR_Y1,%d4
    moveq   #1,%d5
    bsr.w   sv_fill
    moveq   #BAR_X0+1,%d0
    moveq   #BAR_Y0+1,%d1
    moveq   #BAR_X1-1,%d2
    moveq   #BAR_Y1-1,%d4
    moveq   #0,%d5
    bsr.w   sv_fill

| ---- fill: w = clamp(pos - start, 0..span) * BAR_IW / span ----
    move.l  %a2@(68),%d0            | live play position
    sub.l   %d6,%d0
    bpl.b   1f
    moveq   #0,%d0                  | racing a wrap: clamp low
1:  cmp.l   %d7,%d0
    bls.b   2f
    move.l  %d7,%d0                 | clamp high
2:  moveq   #BAR_IW,%d1
    mulu.l  %d1,%d0
    divul   %d7,%d0                 | d0 = 0..BAR_IW
    beq.b   sv_marker               | zero width: nothing to fill
    move.l  %d0,%d2
    add.l   #BAR_X0,%d2             | x1 = 84 + w  (w>=1 -> fill 85..84+w)
    moveq   #BAR_X0+1,%d0
    moveq   #BAR_Y0+1,%d1
    moveq   #BAR_Y1-1,%d4
    moveq   #1,%d5
    bsr.w   sv_fill

| ---- loop marker: XOR vline at the loop point, if configured ----
sv_marker:
    move.l  %a4@(8),%d0             | loop point; < 0 = none
    bmi.b   sv_number
    sub.l   %d6,%d0
    bmi.b   sv_number               | outside the slice: don't draw
    cmp.l   %d7,%d0
    bhi.b   sv_number
    moveq   #BAR_IW-1,%d1
    mulu.l  %d1,%d0
    divul   %d7,%d0
    add.l   #BAR_X0+1,%d0           | x = 85..115
    pea     -1                      | XOR: visible over box, fill and background
    pea     BAR_Y1+1
    pea     BAR_Y0-1
    move.l  %d0,%sp@-
    pea     SURF
    jsr     VLINE
    lea     %sp@(20),%sp

| ---- the number, centred in the frame ----
sv_number:
    tst.l   %d3
    bmi.b   sv_dashes               | no slice selected: "--" instead
    move.l  %d3,%d0
    addq.l  #1,%d0                  | display 1-based
    lea     sv_fmt,%a0
    lea     sv_meas,%a1
    bsr.w   sv_text
    bra.b   sv_frame

sv_idle:
sv_dashes:
    lea     sv_dash,%a0             | "--", its own measure template, no varargs read
    move.l  %a0,%a1
    bsr.w   sv_text

| ---- the trig-key frame: four 1 px edges over the text's cleared background ----
sv_frame:
    moveq   #61,%d0
    moveq   #8,%d1
    moveq   #75,%d2
    moveq   #8,%d4
    moveq   #1,%d5
    bsr.b   sv_fill                 | bottom edge (y grows upward on this display)
    moveq   #61,%d0
    moveq   #22,%d1
    moveq   #75,%d2
    moveq   #22,%d4
    moveq   #1,%d5
    bsr.b   sv_fill                 | top edge
    moveq   #61,%d0
    moveq   #8,%d1
    moveq   #61,%d2
    moveq   #22,%d4
    moveq   #1,%d5
    bsr.b   sv_fill                 | left
    moveq   #75,%d0
    moveq   #8,%d1
    moveq   #75,%d2
    moveq   #22,%d4
    moveq   #1,%d5
    bsr.b   sv_fill                 | right
    jmp     ARM_EXIT                | dirty flag + epilogue restore d2-d7/a2-fp

| sv_fill: FILLRECT(SURF, d0, d1, d2, d4, d5) = (x0, y0, x1, y1, mode)
sv_fill:
    move.l  %d5,%sp@-
    move.l  %d4,%sp@-
    move.l  %d2,%sp@-
    move.l  %d1,%sp@-
    move.l  %d0,%sp@-
    pea     SURF
    jsr     FILLRECT
    lea     %sp@(24),%sp
    rts

| sv_text: DRAWFMT(FONT12, SURF, 69, 13, centred, mode 0 = lit glyph no background,
|                  measure %a1, fmt %a0, value %d0)
sv_text:
    move.l  %d0,%sp@-
    move.l  %a0,%sp@-
    move.l  %a1,%sp@-
    clr.l   %sp@-
    pea     1
    pea     12
    pea     68                      | centre of the 61..75 frame
    pea     SURF
    pea     FONT12
    jsr     DRAWFMT
    lea     %sp@(36),%sp
    rts

| =============================== tick ===============================
| Entered from 0x40056c92, in the timer task, once per type-1 timer message.
| May clobber d0/d1/a0/a1 only (the surrounding loop reloads them).
    .global sv_tick
sv_tick:
    addq.l  #1,BLINKCTR
    tst.l   F_SLICEVIEW
    beq.b   sv_tick_out
    moveq   #3,%d0
    cmp.l   VIEW,%d0                | SLICES view on screen?
    bne.b   sv_tick_out
    tst.l   MODAL                   | popup open: 0x4004581c would no-op anyway
    bne.b   sv_tick_out
    tst.b   POSTED
    beq.b   sv_post
    move.l  BLINKCTR,%d0            | one outstanding; retry only after 64 ticks
    sub.l   POSTTIME,%d0
    moveq   #64,%d1
    cmp.l   %d1,%d0
    bls.b   sv_tick_out
sv_post:
    moveq   #1,%d0
    move.b  %d0,POSTED
    move.l  BLINKCTR,%d0
    move.l  %d0,POSTTIME
    pea     sv_msg
    pea     UIQ
    jsr     POST
    addq.l  #8,%sp
sv_tick_out:
    tst.l   TICK_TSTL               | displaced instruction: flags feed the beq at resume
    jmp     TICK_RESUME

| =============================== trig LED ===============================
| sv_ledid: d0 = led id (2 * (slice & 15), the red die of the trig's pair) when the
| feature is live: flag on, SLICES view on screen, this track's voice active, playing a
| slice, and that slice on the visible page. Otherwise d0 = -1 (N set). Clobbers d0/d1/a0
| only, so it is callable from both hook contexts below.
sv_ledid:
    tst.l   F_SLICEVIEW
    beq.b   sl_no
    moveq   #3,%d0
    cmp.l   VIEW,%d0
    bne.b   sl_no
    moveq   #0,%d0
    move.b  CURTRACK,%d0
    move.l  %d0,%d1
    lsl.l   #3,%d0                  | 8t
    lsl.l   #5,%d1                  | 32t
    add.l   %d1,%d0                 | 40t
    lsl.l   #2,%d1                  | 128t
    add.l   %d1,%d0                 | 168t
    lea     VOICES,%a0
    add.l   %d0,%a0
    tst.b   %a0@(0)                 | voice active?
    beq.b   sl_no
    move.b  %a0@(32),%d0
    extb.l  %d0
    bmi.b   sl_no                   | no slice
    move.l  %d0,%d1
    asr.l   #4,%d1
    cmp.l   PAGE,%d1                | slice on the visible page?
    bne.b   sl_no
    moveq   #15,%d1
    and.l   %d1,%d0
    add.l   %d0,%d0                 | led id = 2 * trig
    rts
sl_no:
    moveq   #-1,%d0
    rts

| sv_led — detour from 0x400444fc, the common tail of the per-view trig-LED refresher
| 0x40043fdc, after the view arms painted (SLICES: green = slice exists) and before the
| red playhead overlay. Paints the playing slice's trig AMBER (both dies set, both full
| brightness) — a combination the SLICES view never uses. The dispatcher flushes after
| fnA, so no explicit flush. Must preserve d3/d4; driver calls clobber d0/d1/a0/a1 only.
    .global sv_led
sv_led:
    bsr.b   sv_ledid
    bmi.b   sl_done
    move.l  %d0,%sp@-               | keep the id across the calls
    move.l  %d0,%sp@-
    jsr     LEDSETPAIR              | both dies on
    addq.l  #4,%sp
    move.l  %sp@,%d0
    pea     0xF
    move.l  %d0,%sp@-
    jsr     LEDBRIGHT2              | both dies full brightness -> amber
    addq.l  #8,%sp
    addq.l  #4,%sp
sl_done:
    move.b  0x80000000,%d0          | displaced instruction
    jmp     LED_RESUME

| sv_beat — detour from 0x40056f24, the once-per-quarter-note arm of the tempo LED
| (jsr LEDFLASH with (3, 0x26) already stacked). Replaying the jsr from here leaves the
| stock args at 4(sp), exactly as the original call site did. Then the same inversion
| pulse, same 3-tick length, on both dies of the playing slice's trig — so it blinks in
| lockstep with the tempo LED. Only d0/d1/a0/a1 are free here.
    .global sv_beat
sv_beat:
    jsr     LEDFLASH                | displaced: the stock tempo-LED flash
    bsr.w   sv_ledid
    bmi.b   sb_done
    move.l  %d0,%sp@-               | keep the id
    pea     3
    move.l  %d0,%sp@-
    jsr     LEDFLASH
    addq.l  #8,%sp
    move.l  %sp@,%d0
    addq.l  #1,%d0
    pea     3
    move.l  %d0,%sp@-
    jsr     LEDFLASH
    addq.l  #8,%sp
    addq.l  #4,%sp
sb_done:
    jmp     BEAT_RESUME

| =============================== PERSONALIZE entry ===============================
    .global lbl_sliceview, get_sliceview, set_sliceview
lbl_sliceview:
    .asciz "SLICE PLAYHEAD"
    .align 2

get_sliceview:
    move.l  #GLYPH_ON,%d0
    tst.l   F_SLICEVIEW
    bne.b   gs_ret
    move.l  #GLYPH_OFF,%d0
gs_ret:
    rts

set_sliceview:
    move.l  F_SLICEVIEW,%d0
    add.l   4(%sp),%d0
    andi.l  #1,%d0
    move.l  %d0,F_SLICEVIEW
    rts

| =============================== data ===============================
sv_msg:
    .byte   78                      | event 78 -> 0x40062d04 -> jsr 0x4004581c (view redraw)
    .byte   0,0,0,0,0,0,0
sv_fmt:
    .asciz  "%d"
sv_meas:
    .asciz  "00"
sv_dash:
    .asciz  "--"
    .align 2
