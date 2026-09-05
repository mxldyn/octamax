    .cpu 5407
    .text
| =====================================================================
|  HOT CHANGE v8 (on R11) — recorder-preserving flex-pool reinit.
|
|  Root cause (found): FUN_40096f24 (flex pool reinit, called @0x40085ba0 in the
|  load task) resets boundary to 0x390a, rebuilds the free list over ALL pages,
|  ZEROES the whole ~89MB pool, and re-reserves recorders -> wipes recorder content.
|
|  Fix (emulator-validated, tools/emu_pool.py): when g_hot, replace FUN_40096f24
|  with a FLEX-ONLY reinit that KEEPS the recorder region (high pages) intact:
|    - keep the current boundary _DAT_80006920 (recorders stay reserved)
|    - cursor = 0 ; rebuild the free list ONLY over [0..boundary)
|    - clear flex slot metadata (0..0x7f) exactly as stock does
|    - do NOT zero the pool, do NOT run the recorder loop
|  Recorders (top pages) keep their pages + content; flex reloads into the low pages.
|
|  Hooks (all gated on g_hot): hot_change, hot_panic, hot_reinit, hot_unload,
|  hot_reclaim, hot_resync (which one-shot disarms at the end-of-load re-sync).
| =====================================================================

| ---- FUN_40063e28 hook: arm g_hot + SNAPSHOT R7 metadata + open picker ----
hot_change:
    tst.l   4(%sp)
    bne.b   hc_ret
    | snapshot R7 (rec6) metadata while intact: 0x2c struct + 0x448 settings struct
    move.l  #0x2c, -(%sp)          | memcpy(snap_2c, 0x46c939cc, 0x2c)
    pea     0x46c939cc
    pea     snap_2c
    jsr     0x40020898
    lea     12(%sp), %sp
    move.l  #0x448, -(%sp)         | memcpy(snap_448, 0x100d52a0, 0x448)
    pea     0x100d52a0
    pea     snap_448
    jsr     0x40020898
    lea     12(%sp), %sp
    moveq   #1, %d0
    move.l  %d0, g_hot
    jmp     0x400647a0
hc_ret:
    rts

| ---- FUN_400a10c8 hook: skip the panic while armed ----
hot_panic:
    tst.l   g_hot
    beq.b   hp_stock
    rts
hp_stock:
    lea     -0x24(%sp), %sp
    movem.l %d2-%d5/%a2-%a6, (%sp)
    jmp     0x400a10d0

| ---- FUN_400238a4 hook: RESTORE R7 metadata + skip re-sync + ONE-SHOT disarm ----
hot_resync:
    tst.l   g_hot
    beq.b   hr_stock
    jsr     hc_diaglog           | DIAG: log ml_min / o0 / t2 to CF
    | restore R7 metadata (content already preserved by v8; only the metadata was reset)
    move.l  #0x2c, -(%sp)         | memcpy(0x46c939cc, snap_2c, 0x2c)
    pea     snap_2c
    pea     0x46c939cc
    jsr     0x40020898
    lea     12(%sp), %sp
    move.l  #0x448, -(%sp)        | memcpy(0x100d52a0, snap_448, 0x448)
    pea     snap_448
    pea     0x100d52a0
    jsr     0x40020898
    lea     12(%sp), %sp
    | re-finalize R7 to rebuild playback handle + trim + display from restored metadata
    move.l  #1, -(%sp)            | FUN_40099374(type=1, slot=0x86, force=1)
    move.l  #0x86, -(%sp)
    move.l  #1, -(%sp)
    jsr     0x40099374
    lea     12(%sp), %sp
    | v16 DIAGNOSTIC: do NOT disarm here. The post-load part-apply (which stops
    | track 6's voice via FUN_40006820) runs AFTER this re-sync; if we disarm now,
    | hot_vstop is inert by then. Leaving g_hot armed lets hot_vstop protect the
    | track 6 voice through the apply. (Proper disarm-on-first-track6-trig comes
    | next if this confirms the timing hypothesis.)
    | clr.l   g_hot
    rts
hr_stock:
    move.l  %a2, -(%sp)
    jsr     0x4009b220
    jmp     0x400238ac
    .balign 4
snap_2c:    .space 0x2c
    .balign 4
snap_448:   .space 0x448
    .balign 4

| ---- FUN_40096300 hook: while armed, skip UNLOAD of recorder slots 0x80-0x87 ----
hot_unload:
    tst.l   g_hot
    beq.b   hu_stock
    move.l  4(%sp), %d0
    subi.l  #0x80, %d0
    cmpi.l  #8, %d0
    bcc.b   hu_stock
    moveq   #1, %d0
    rts
hu_stock:
    lea     -0x28(%sp), %sp
    movem.l %d2-%d7/%a2-%a5, (%sp)
    jmp     0x40096308

| ---- FUN_40095a90 hook: while armed, skip the recorder page RECLAIM ----
hot_reclaim:
    tst.l   g_hot
    beq.b   hrc_stock
    moveq   #0, %d0
    rts
hrc_stock:
    lea     -0x2c(%sp), %sp
    movem.l %d2-%d7/%a2-%a5, (%sp)
    jmp     0x40095a98

| ---- FUN_40096f24 hook: recorder-preserving FLEX-ONLY reinit while armed ----
hot_reinit:
    tst.l   g_hot
    bne.b   hri_go
    lea     -0x2c(%sp), %sp       | not armed -> stock FUN_40096f24
    movem.l %d2-%d7/%a2-%a6, (%sp)
    jmp     0x40096f2c
hri_go:
    lea     -0x2c(%sp), %sp
    movem.l %d2-%d7/%a2-%a6, (%sp)
    | 1. unload flex slots 0..0x7f (recorders 0x80-0x87 skipped -> preserved)
    moveq   #0, %d2
    lea     0x46c922cc, %a2       | &flex_state[0].+8
hri_unl:
    move.l  (%a2), %d0            | state+8
    cmpi.l  #1, %d0               | ==1 (already empty) -> skip
    beq.b   hri_unl_n
    move.l  %d2, -(%sp)
    jsr     0x40096300            | unload flex slot (hot_unload passes: slot < 0x80)
    addq.l  #4, %sp
hri_unl_n:
    lea     0x2c(%a2), %a2
    addq.l  #1, %d2
    cmpi.l  #0x80, %d2
    bne.b   hri_unl
    | 2. cursor = 0 ; KEEP boundary ; set table pointers (as stock)
    clr.l   0x8000691c
    move.l  #0x46c2e9c0, %d0
    move.l  %d0, 0x80006914
    move.l  #0x46c2e580, %d0
    move.l  %d0, 0x80006918
    | 3. rebuild free list ONLY over [0..boundary): 0x46c2e9c0[i] = i+1
    move.l  0x80006920, %d3       | B = boundary
    lea     0x46c2e9c0, %a2
    moveq   #1, %d4               | value = i+1
    moveq   #0, %d5               | i
hri_fl:
    cmp.l   %d3, %d5
    bcc.b   hri_fl_done           | i >= B -> done
    move.w  %d4, (%a2)+
    addq.l  #1, %d4
    addq.l  #1, %d5
    bra.b   hri_fl
hri_fl_done:
    | 4. clear flex slot metadata 0..0x7f (exactly as stock)
    lea     0x46c2e580, %a2       | page-list starts (long)
    lea     0x46c75e88, %a3       | sizes (short)
    lea     0x46c922c4, %a4       | state struct (0x2c)
    lea     0x46c93c28, %a5       | dirty bytes
    moveq   #0, %d2
hri_md:
    clr.l   (%a2)+
    clr.w   (%a3)+
    move.l  0x14(%a4), %d0        | gen counter ++ (skip 0)
    addq.l  #1, %d0
    bne.b   hri_md1
    moveq   #1, %d0
hri_md1:
    move.l  %d0, 0x14(%a4)
    moveq   #1, %d0
    move.l  %d0, 8(%a4)           | state = 1
    clr.l   0xc(%a4)
    clr.l   0x10(%a4)
    clr.b   (%a5)+
    lea     0x2c(%a4), %a4
    addq.l  #1, %d2
    cmpi.l  #0x80, %d2
    bne.b   hri_md
    | 5. mark flex format valid (recorders untouched; no pool zero)
    moveq   #1, %d0
    move.l  %d0, 0x46105408
    | re-validate R7's recorder metadata at the END of this teardown phase, so ml is
    | not left at 0 in the window before hot_recmeta (FUN_40007960 entry) next runs
    | -> shrinks the frame-builder race that keeps muting the voice.
    move.l  #0x2c, -(%sp)
    pea     snap_2c
    pea     0x46c939cc
    jsr     0x40020898
    lea     12(%sp), %sp
    movem.l (%sp), %d2-%d7/%a2-%a6
    lea     0x2c(%sp), %sp
    rts

| ---- FUN_40006820 hook: while armed, do NOT stop track 6's voice ----
|  FUN_40006820(track) is the per-track voice-stop primitive: it clears the
|  active byte (0x800049d8+track*0xA8), clears the voice command slot, bumps a
|  gen counter, and sends the DSP note-off (FUN_4000672c). It is the ONLY entry
|  that stops a single voice during a project load (the machine-reassign
|  FUN_40096ab0 calls it after writing the flex machine-type). FUN_40006890
|  (stop-all) lives only in reformat_confirm, never in the load path, so gating
|  this entry for track 6 is sufficient: track 6's live buffer keeps sounding
|  continuously across the swap (source<->dest track 7 match by construction).
|  INDEX-AGNOSTIC: instead of a hardcoded track number, protect any voice that is
|  CURRENTLY a recorder-buffer-playback machine (voice type == 4, at voice+0x14 =
|  0x800049ec + track*0xA8). That is exactly "the live recorder-buffer voice" the
|  transition needs kept alive, regardless of which track index it sits on -> no
|  off-by-one risk. At the moment FUN_40006820 is called to stop the voice, the
|  voice-type byte still reflects the OLD (type-4) state (the new machine's type-4
|  setup, FUN_40005214, runs AFTER the stop), so this reliably catches it.
|  HARDWARE-CORRECTED: the type-4 detection was WRONG (the recorder voice's type
|  byte at voice+0x14 is 0x01, not 4 -- MAXODBG2 v14=0x01860001; the emulator only
|  "validated" type-4 because the harness SEEDED the fake value). The hardcoded
|  track index 6 is confirmed correct (v18==v16). Use it.
hot_vstop:
    tst.l   g_hot
    beq.b   hvs_stock
    move.l  4(%sp), %d0          | track index (return addr at 0(sp))
    moveq   #6, %d1
    cmp.l   %d0, %d1             | 6 - track
    bne.b   hvs_stock            | track != 6 -> stock stop
    rts                          | g_hot && track 6 -> keep it sounding
hvs_stock:
    move.l  %a2, -(%sp)          | displaced 0x40006820
    move.l  %d2, -(%sp)          | displaced 0x40006822
    move.l  0xc(%sp), %d1        | displaced 0x40006824
    jmp     0x40006828

| ---- FUN_40008f84 hook: the OTHER caller of the DSP voice-release FUN_4000672c ----
|  FUN_4000672c (DSP voice release/realloc) has exactly TWO callers: FUN_40006820
|  (covered by hot_vstop) and FUN_40008f84 (also reached via FUN_40008fe4). Gating
|  BOTH callers for a recorder-playback voice (type 4) means FUN_4000672c is NEVER
|  invoked for that voice -> its DSP slot is never released -> the buffer keeps
|  sounding across the load, WITHOUT gating FUN_4000672c itself (v17's mistake, which
|  corrupted the voice allocator and cut everything). Same type-4 detection as hot_vstop.
hot_vstop2:
    tst.l   g_hot
    beq.b   hv2_stock
    move.l  4(%sp), %d0          | track index (return addr at 0(sp))
    moveq   #6, %d1
    cmp.l   %d0, %d1             | 6 - track
    bne.b   hv2_stock            | track != 6 -> stock release
    rts                          | g_hot && track 6 -> keep it sounding
hv2_stock:
    lea     -0xc(%sp), %sp       | displaced 0x40008f84
    movem.l %d2-%d3/%a2, (%sp)   | displaced 0x40008f88
    jmp     0x40008f8c

| ---- FUN_4000672c hook: while armed, do NOT send the DSP note-off for track 6 ----
|  FUN_4000672c is the SINGLE funnel to the DSP note-off (only FUN_40006820 and
|  FUN_40008f84 reach it). hot_vstop covers the FUN_40006820 path (and its
|  active-byte clear); but FUN_40008f84 -> FUN_4000672c reaches the DSP note-off
|  WITHOUT touching FUN_40006820, so it silences track 6 on the real DSP even
|  though the CPU-side voice-active byte stays set (emulator-confirmed: scenarios
|  E/F call FUN_4000672c(6) unimpeded). Gating FUN_4000672c for track 6 blocks the
|  note-off from BOTH paths -> the DSP voice is never released across the swap.
hot_noteoff:
    tst.l   g_hot
    beq.b   hno_stock
    move.l  4(%sp), %d0          | track index (return addr at 0(sp))
    moveq   #6, %d1
    cmp.l   %d0, %d1
    bne.b   hno_stock
    rts                          | g_hot && track 6 -> skip the DSP note-off
hno_stock:
    lea     -0x10(%sp), %sp      | displaced 0x4000672c
    movem.l %d2-%d5, (%sp)       | displaced 0x40006730
    jmp     0x40006734

| ---- FUN_40007960 hook: keep R7's recorder metadata VALID every frame ----
|  FUN_40007960 is the per-frame recorder-voice processor. It takes the PLAY path
|  (produces R7's DSP frame) only if the recorder metadata at voice+0x4 (= 0x46c939cc)
|  has state(+0x8)==0 AND length(+0x10)>0. The load invalidates that metadata mid-load
|  -> FUN_40007960 skips PLAY and calls FUN_40006820 (stop). hot_vstop blocks the stop
|  (o0 stays FF, HW-confirmed) but the voice is then ACTIVE-BUT-UNFED -> silent.
|  Fix: while g_hot, restore R7's metadata from the snapshot at this function's entry,
|  every frame, so it is ALWAYS playable -> R7's frame keeps being produced -> the buffer
|  sounds continuously across the load. (Recorder pages are preserved by hot_reinit, so
|  the restored handle stays valid. Released at disarm, when the new project takes over.)
hot_recmeta:
    tst.l   g_hot
    beq.b   hrm_stock
    move.l  (gcnt).l, %d0        | PROGRESS CLOCK: count FUN_40007960 calls while armed
    addq.l  #1, %d0
    move.l  %d0, (gcnt).l
    move.l  #0x2c, -(%sp)        | memcpy(0x46c939cc, snap_2c, 0x2c)  -- metadata only
    pea     snap_2c              | (settings 0x448 must NOT be restored per-frame: the DSP
    pea     0x46c939cc           |  reads them live -> per-frame overwrite = audio corruption,
    jsr     0x40020898           |  confirmed by MAXOHT23's screech. Restored once at hot_resync.)
    lea     12(%sp), %sp
hrm_stock:
    link.w  %a6, #-0x8c          | displaced 0x40007960
    movem.l %d2-%d7/%a2-%a5, (%sp) | displaced 0x40007964
    | NOTE: forcing D5 (arg 0x1c) here to skip the D4/D5 MUTE2 gate was tried (MAXOHT27)
    | and made it WORSE (~15% vs ~50%): it drives the play path into the DEEPER MUTE2 branch
    | (0x40007efe, voice+0x18==0) which CLEARS voice fields -> harder cut. Forcing individual
    | play-gates backfires; the recorder play path needs a coherent full state. Left un-forced.
    jmp     0x40007968

| ---- PROGRESS METER: how far did track-6's voice stay fed, and what cut it? ----
|  fmute = the gcnt value at the FIRST mute of track 6 (frames the voice was fed
|          before the cut) -> monotonic progress metric (higher each fix = better).
|  which = 1 (stop path 0x40008110) or 2 (MUTE2 0x4000812c) -> the current blocker.
|  g/m1/m2 = total FUN_40007960 calls / stop-mutes / mute2s for track 6.
hc_diaglog:
    move.l  (m2_cnt).l, -(%sp)
    move.l  (m1_cnt).l, -(%sp)
    move.l  (gcnt).l, -(%sp)
    move.l  (first_which).l, -(%sp)
    move.l  (first_mute).l, -(%sp)
    pea     dfmt
    pea     dlogbuf
    jsr     0x40013a08
    lea     0x1c(%sp), %sp
    move.l  %d0, (dlen).l
    move.l  #0x200, -(%sp)
    move.l  #0x460261e0, -(%sp)
    pea     0x400b328b
    pea     dpath
    pea     dfh
    jsr     0x40016864
    lea     0x14(%sp), %sp
    tst.l   %d0
    blt.b   dl_done
    move.l  (dlen).l, -(%sp)
    pea     dlogbuf
    pea     dfh
    jsr     0x400166b8
    lea     0xc(%sp), %sp
    pea     dfh
    jsr     0x4001677c
    addq.l  #4, %sp
dl_done:
    rts

| ---- PROGRESS METER detours on the two non-PLAY exits of FUN_40007960 (track 6 only) ----
|  At both exits A2 = the voice base, so cmpa.l #voice[6] filters track 6.
hot_m1:                          | detour 0x40008110 (STOP path)
    cmpa.l  #0x80004dc8, %a2     | is this track 6's voice?
    bne.b   hm1_stock
    tst.l   (first_mute).l
    bne.b   hm1_inc
    move.l  (gcnt).l, %d0
    move.l  %d0, (first_mute).l
    moveq   #1, %d0
    move.l  %d0, (first_which).l
hm1_inc:
    move.l  (m1_cnt).l, %d0
    addq.l  #1, %d0
    move.l  %d0, (m1_cnt).l
hm1_stock:
    jsr     0x40006820.l         | displaced (was PC-rel jsr 0x40006820)
    movea.l 8(%a6), %a0          | displaced movea.l (8,A6),A0
    jmp     0x40008118

hot_m2:                          | detour 0x4000812c (MUTE2 path)
    cmpa.l  #0x80004dc8, %a2
    bne.b   hm2_stock
    move.l  %d0, -(%sp)
    tst.l   (first_mute).l
    bne.b   hm2_inc
    move.l  (gcnt).l, %d0
    move.l  %d0, (first_mute).l
    moveq   #2, %d0
    move.l  %d0, (first_which).l
hm2_inc:
    move.l  (m2_cnt).l, %d0
    addq.l  #1, %d0
    move.l  %d0, (m2_cnt).l
    move.l  (%sp)+, %d0
hm2_stock:
    lea     0x40095bdc, %a0      | displaced lea (0x40095bdc).l,A0
    jmp     0x40008132

    .balign 4
gcnt:        .long 0
first_mute:  .long 0
first_which: .long 0
m1_cnt:      .long 0
m2_cnt:      .long 0
dlen:        .long 0
dfmt:        .asciz "fmute=%x which=%x g=%x m1=%x m2=%x\n"
    .balign 2
dpath:       .asciz "/HOTDBG.TXT"
    .balign 4
dfh:         .space 0x40
    .balign 4
dlogbuf:     .space 0x60

    .balign 4
g_hot:      .long 0
