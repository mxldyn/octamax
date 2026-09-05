    .cpu 5407
    .text
| =====================================================================
|  BOOT-ZERO (on 2afix base). Zero the relocated static settings' DDR home at BOOT,
|  before any project load or audio read.
|
|  The stock boot conditionally clears battery-backed SRAM [0x10000000, 0x100fff00) at
|  0x4001fa64.. (when the checksum at 0x100fff00 is invalid / on EMPTY RESET). The old
|  settings table (0x100d5b30) lives inside that span, so stock code can rely on it being
|  zero after a cold init. Moved to DDR (0x40a955e0) the table is in NObody's boot clear,
|  so it starts as garbage -> the load reads it right after the LOADING popup (before the
|  reload orchestrator) -> corrupt noises + hang. (This is why the earlier reload-orch
|  zero-init never helped: that hook runs AFTER this crash point.)
|
|  Fix: detour 0x4001fa64 (lea 0x10000000,a0) to first zero the whole reserved DDR window
|  [0x40a955e0, 0x40af55e0) (384 KB), then run the displaced lea and resume at 0x4001fa6a.
|  Runs unconditionally every boot; d0 (the checksum) is preserved by full save/restore.
| =====================================================================

bootzero_stub:
    lea     -0x3c(%sp), %sp
    movem.l %d0-%d7/%a0-%a6, (%sp)
    movea.l #0x40a955e0, %a0
    move.l  #0x18000, %d0            | 0x60000/4 longwords = whole reserved 384 KB
    moveq   #0, %d1
bz_lp:
    move.l  %d1, (%a0)+
    subq.l  #1, %d0
    bne.b   bz_lp
    movem.l (%sp), %d0-%d7/%a0-%a6
    lea     0x3c(%sp), %sp
    lea     0x10000000, %a0          | displaced (41f9 10000000)
    jmp     0x4001fa6a               | stock: cmp.l 0x100fff00,d0
