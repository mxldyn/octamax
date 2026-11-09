| scene_stub v2 — "sticky global" scene A/B selection, redesigned.
|
| WHY v2: v1 hooked FUN_40009094 and treated every invocation as a pattern change,
| copying the outgoing pattern's selection over the incoming one. That premise is
| false — FUN_40009094 is apply_part(part, pattern), called from 10 sites (3 of which
| pass an arbitrary pattern in a register), and the manual scene-assign path
| (FUN_40052944) reaches it too. Result: assigning a scene by hand got clobbered.
|
| v2 ignores the function's arguments entirely and polls the REAL active pattern
| (DAT_80000003). A pattern change and a manual assignment are then distinguishable:
| in the first the index changes, in the second it does not.
|
|   enforce():
|       p = *(0x80000003)
|       if !VALID:            STICKY = live[p]           ; adopt, first run
|       elif p != LAST_P:     live[p] = STICKY ; HOLD = 4 ; impose, pattern changed
|       elif HOLD != 0:       live[p] = STICKY ; HOLD--   ; keep imposing briefly
|       else:                 STICKY = live[p]            ; adopt, user assigned
|       LAST_P = p ; VALID = 0xA5
|
| The HOLD window exists because the Part loaders (FUN_4004a100 / FUN_400a0734) may
| write the destination Part's saved selection right after the pattern change; without
| it we would adopt their value and lose stickiness. HOLD is a heuristic — it is the
| one parameter that may need tuning on hardware.
|
| enforce() is idempotent, so it is called from two hosts for robustness:
|   - FUN_40009094 (apply_part): runs on pattern change AND on manual scene assign
|   - FUN_4003f1b4 (crossfader): re-asserts while audio runs, in case a loader writes
|     after apply_part
|
| Data model (verified): live copy = *(0x46c82456) + pattern*0x18b2 + 0x8ed90 (A) / +1 (B).
| All three consumers read it — crossfader FUN_4003f1b4, event loop FUN_40061a94
| (publishes UI elements 0x37/0x38) and FUN_4004d640 (LCD numbers) — so fixing the data
| fixes audio and display together. No GUI patch needed.
|
| RAM (patch-owned, clear of audio 0x80006a00.. and GUI 0x80006c30..):
|   0x80006c60 LAST_P   0x80006c61 VALID(0xA5)
|   0x80006c62 STICKY_A 0x80006c63 STICKY_B   0x80006c64 HOLD
| Cave: 0x400d6700 (past the GUI stubs, inside the free region that ends ~0x400d7c1c).

    .include "tools/patch_ram.inc"
    .equ LAST_P,   SC_LAST_P
    .equ VALID,    SC_VALID
    .equ STICKY_A, SC_STICKY_A
    .equ STICKY_B, SC_STICKY_B
    .equ HOLD,     SC_HOLD
    .equ HOLD_N,   4

    .equ PROJ_PTR, 0x46c82456
    .equ ACT_PAT,  0x80000003
    .equ STRIDE,   0x18b2
    .equ SEL_OFF,  0x8ed90

    .equ F_LAZY,    0x800000d8      | PERSONALIZE: LAZY TRANSITIONS
    .equ SAVE_STUB, 0x400d64e0      | audio patch entry (lazy part apply)
    .equ XF_RESUME, 0x4003f1bc      | crossfader, after the displaced prologue

    .text
    .global _start
_start:

| ---- host 1: FUN_40009094 (apply_part). Detour at 0x40009094 jumps here. ----
scene_stub:
    tst.l   F_LAZY                     | gate: apagado -> stock
    beq.b   sc_skip
    bsr.w   enforce
sc_skip:
    jmp     SAVE_STUB                  | chain into the existing audio patch

| ---- host 2: FUN_4003f1b4 (crossfader). Detour at 0x4003f1b4 jumps here. ----
| Displaced prologue: lea -0x3c(sp),sp ; movem.l d2-d7/a2-a6,(sp)
xf_stub:
    tst.l   F_LAZY                     | gate: apagado -> stock
    beq.b   xf_skip
    bsr.w   enforce
xf_skip:
    lea     -0x3c(%sp),%sp
    .short  0x48d7, 0x7cfc             | movem.l %d2-%d7/%a2-%a6,(%sp)
    jmp     XF_RESUME

| ---- shared: enforce() ----
enforce:
    lea     -0x18(%sp),%sp             | ColdFire: no movem with -(An)
    .short  0x48d7, 0x030f             | movem.l %d0-%d3/%a0-%a1,(%sp)

    moveq   #0,%d0
    move.b  ACT_PAT,%d0                | d0 = active pattern
    movea.l PROJ_PTR,%a0               | a0 = project base (pointer, not the constant)
    move.l  #STRIDE,%d1
    move.l  %d0,%d2
    muls.l  %d1,%d2                    | d2 = p * 0x18b2
    adda.l  %d2,%a0
    adda.l  #SEL_OFF,%a0               | a0 = &live[p].sceneA  (sceneB at 1(a0))

    moveq   #0,%d1
    move.b  VALID,%d1
    cmpi.l  #0xa5,%d1
    bne.b   en_adopt                   | first run -> take whatever is selected now

    moveq   #0,%d1
    move.b  LAST_P,%d1
    cmp.l   %d0,%d1
    bne.b   en_changed                 | pattern changed -> impose

    moveq   #0,%d1
    move.b  HOLD,%d1
    beq.b   en_adopt                   | window closed -> user owns the selection
    subq.l  #1,%d1                     | still holding -> impose and count down
    move.b  %d1,HOLD
    bra.b   en_impose

en_changed:
    move.l  #HOLD_N,%d1
    move.b  %d1,HOLD

en_impose:
    move.b  STICKY_A,%d3
    move.b  %d3,(%a0)
    move.b  STICKY_B,%d3
    move.b  %d3,1(%a0)
    bra.b   en_stamp

en_adopt:
    move.b  (%a0),%d3
    move.b  %d3,STICKY_A
    move.b  1(%a0),%d3
    move.b  %d3,STICKY_B

en_stamp:
    move.b  %d0,LAST_P
    move.l  #0xa5,%d1
    move.b  %d1,VALID

    .short  0x4cd7, 0x030f             | movem.l (%sp),%d0-%d3/%a0-%a1
    lea     0x18(%sp),%sp
    rts

| ---- shared LAZY helper ----
    .equ TRK_BANK, 0x8000182a          | per-track bank[8]
    .equ TRK_PART, 0x80001832          | per-track part[8]
    .equ ACT_BANK, 0x80000002          | active bank
    .equ ACT_PART, 0x80000003          | active part
| lz_dirty: d0 = track 0..7 -> Z clear if the track is in transition, Z set if not.
| Keeps d0; clobbers d1 and a0 only (led_stub calls it with the LED painter's registers live).
| Lives here for space; enc_apply (patch_enc.s) and led_stub (patch_led.s) call it through the
| absolute address build_all passes them as LZ_DIRTY. A track is in transition when restore_stub
| protected it (LZ_SNAPOK) and its per-track (bank, part) still differs from the active one;
| stock tests both bytes the same way (0x40052c50).
    .if TRK_PART - TRK_BANK - 8
    .error "lz_dirty reads the per-track part as 8(TRK_BANK)"
    .endif
    .global lz_dirty
lz_dirty:
    lea     LZ_SNAPOK,%a0
    tst.b   (%a0,%d0.l)
    beq.b   ld_out                     | not protected: Z set
    lea     TRK_BANK,%a0
    mvz.b   (%a0,%d0.l),%d1
    cmp.b   ACT_BANK,%d1
    bne.b   ld_out                     | other bank: Z clear
    mvz.b   8(%a0,%d0.l),%d1
    cmp.b   ACT_PART,%d1               | other part: Z clear; same: Z set
ld_out:
    rts
