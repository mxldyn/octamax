| patch_ram.inc -- RAM owned by the patches (LAZY TRANSITIONS, sticky scenes, dimmed LED,
| SLICE PLAYHEAD). One block, shared by every source that keeps state between calls.
|
| Home: DDR 0x40af0000..0x40af0600, inside the 384 KB reserve [0x40a955e0, 0x40af55e0) that
| dual-256 carves below the flex pool (SET-B uses it up to 0x40ab93e0). Nothing in the stock OS
| references that window (hardware canary, see DUAL256.md), and the boot-zero stub clears it
| every boot, so the state starts at zero like before.
|
| Until OCTAMAX_2h this block sat at 0x80006a00..0x80007000 in the internal SRAM. That is NOT
| free: it lies inside the work buffer 0x80006964..0x80007574 of the stock audio analysis task
| (FUN_40098a5c; FUN_40098388 writes up to 1536 B from 0x80006974). When that task ran it
| overwrote the saved track parameters, the per-track part bytes and the sticky scene state.
| Offsets inside the block are the old ones minus 0x80006a00.

    .equ RAM_BLOCK,   0x40af0000

    .equ LZ_SAVE,     RAM_BLOCK + 0x000   | 0x200: voice params 0x80000a50 saved before apply_part
    .equ LZ_PART,     RAM_BLOCK + 0x200   | 0x10:  0x8000182a..39: per-track bank[8], then part[8]
    .equ LZ_PART_B,   RAM_BLOCK + 0x208   |        its second half: the per-track part (0x80001832..39)
    .equ LZ_PLAYING,  RAM_BLOCK + 0x220   | 8:     per-track "voice active" flags
    .equ LZ_SNAPOK,   RAM_BLOCK + 0x228   | 8:     per-track: restore_stub protected it and parked
                                          |        its destination params in LZ_DEST (= in transition)
    .equ SC_LAST_P,   RAM_BLOCK + 0x260   | sticky scenes: last active part
    .equ SC_VALID,    RAM_BLOCK + 0x261   |        0xA5 once initialised
    .equ SC_STICKY_A, RAM_BLOCK + 0x262
    .equ SC_STICKY_B, RAM_BLOCK + 0x263
    .equ SC_HOLD,     RAM_BLOCK + 0x264
    .equ LED_TMP,     RAM_BLOCK + 0x265   | dimmed LED: brightness across a call
    .equ SV_BLINKCTR, RAM_BLOCK + 0x268   | slice playhead: timer ticks (long)
    .equ SV_POSTED,   RAM_BLOCK + 0x26c   |                 redraw outstanding (byte)
    .equ SV_POSTTIME, RAM_BLOCK + 0x270   |                 BLINKCTR at last post (long)
    .equ LZ_DEST,     RAM_BLOCK + 0x400   | 0x200: destination params parked by restore_stub
    .equ RAM_END,     RAM_BLOCK + 0x600
