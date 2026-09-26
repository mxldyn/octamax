| led_stub — dim the track LED while that track is IN TRANSITION.
|
| A track is "dirty" when it is still sounding with the SOURCE Part's parameters,
| i.e. it has not been re-trigged since the pattern change. That is exactly
| per_track_part[track] != active_Part — the same condition the GUI-in-transition
| patch already uses and that is validated on hardware.
|
| Why brightness and not colour: FUN_40083eb0 already uses all four 2-bit colour
| states (0 off / 1 current track / 2 other sounding / 3 combination), but it passes
| a hardcoded 0xF brightness for every track, every frame. Brightness is therefore a
| free dimension — no existing meaning is displaced.
|
| REVERTED to this minimal form after three additions made it worse. The "always dirty"
| bug belonged to the amber scene-trig indicator (since removed), which OR-ed all 8
| tracks into one light; THIS stub never had it, because the painter already iterates
| tracks and each pass checks its own. What got added on top and then removed again:
|   - a "&& sounding" test reading 0x800049d8, a byte that PULSES -> the LED flickered
|   - a patch-owned dirty mask, never initialised at boot -> idle tracks read as dirty
|   - a colour override, which only existed to fight the flicker the first item caused
| Eight instructions is the whole indicator.
|
| Host: FUN_40083eb0, the 8-track LED painter. At the loop tail:
|   D5 = track index (0..7)   D2 = LED id   D3 = id+1   A3 = FUN_400135b0(id, level)
| The original emits `pea (0xf).w ; move.l D2,-(SP) ; jsr (A3)` twice — one call per
| die of the bi-colour LED. We replace both with the same calls at a computed level.
|
| Stack note: FUN_40083eb0 does NOT pop per call; it cleans 0x20 bytes once at
| 0x40083fc6. The stub must therefore push exactly the same 16 bytes the two
| displaced calls would have pushed, and must NOT clean up itself.
|
| Detour: 0x40083fb4 <- jmp led_stub (6 B, covers the first `pea` + `move.l D2,-(SP)`).
| Bytes 0x40083fba..0x40083fc3 become dead; the stub replicates them and resumes at
| 0x40083fc4.
|
| RAM: 0x80006c65 (one byte, adjacent to the scene v2 block at 0x80006c60..64).

    .equ TRK_PART,  0x8000182a      | per_track_part[8], byte per track
    .equ ACT_PART,  0x80000002      | active Part
    .equ MIDI_MODE, 0x80000012      | non-zero while the [MIDI] key mode is on (toggled 0x4005555c;
                                    | the painter itself reads it through 0x40033970). NOT 0x460d1736.
    .equ BRIGHT_TMP,0x80006c65      | survives the call: FUN_400135b0 may clobber d0
    .equ RESUME,    0x40083fc4      | back into the loop, at addq.l #1,D5

    .equ LVL_NORM,  0xf             | stock brightness
    .equ LVL_DIRTY, 0x5             | in transition — clearly dimmer, still readable

    .text
    .global _start
_start:
led_stub:
    tst.l   0x800000d8                 | gate: LAZY TRANSITIONS apagado -> brillo de fabrica
    beq.b   lb_norm
    tst.l   MIDI_MODE                  | modo MIDI: los T1..T8 son pistas MIDI, que no
    bne.b   lb_norm                    | participan en la transicion -> brillo de fabrica
    | --- decide the level for this track ---
    lea     TRK_PART,%a0
    moveq   #0,%d1
    move.b  (%a0,%d5.l),%d1            | d1 = per_track_part[track]
    moveq   #0,%d0
    move.b  ACT_PART,%d0               | d0 = active Part
    cmp.l   %d0,%d1
    beq.b   lb_norm                    | same Part -> not in transition
    moveq   #LVL_DIRTY,%d0
    bra.b   lb_emit
lb_norm:
    moveq   #LVL_NORM,%d0
lb_emit:
    move.b  %d0,BRIGHT_TMP

    | --- displaced: FUN_400135b0(D2, level) ---
    move.l  %d0,-(%sp)
    move.l  %d2,-(%sp)
    jsr     (%a3)

    | --- displaced: FUN_400135b0(D3, level) --- reload, d0 is caller-saved
    moveq   #0,%d0
    move.b  BRIGHT_TMP,%d0
    move.l  %d0,-(%sp)
    move.l  %d3,-(%sp)
    jsr     (%a3)

    jmp     RESUME                     | the caller cleans all 0x20 bytes
