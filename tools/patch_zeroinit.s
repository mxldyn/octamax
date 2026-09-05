    .cpu 5407
    .text
| =====================================================================
|  ZERO-INIT probe (on R11 + step-1 pool move + step-2a settings relocation).
|
|  Hypothesis: step-2a crashes because the static settings table, moved from SRAM
|  (0x100d5b30, zeroed by the boot data-segment clear) to DDR (0x40a955e0, in the pool
|  region that NOTHING clears at boot), starts as GARBAGE. If the load reads any settings
|  field before writing it, SRAM read 0 but DDR reads junk -> "corrupt noises + hang".
|
|  Fix/test: zero [0x40a955e0, +0x22400) (128 slots x 0x448) ONCE, at the FIRST project
|  reload (FUN_4009083c entry), before its STATIC 0..0x7f slot loop touches any setting.
|  FUN_4009083c is the reload orchestrator for EVERY load (boot auto-load AND CHANGE), so
|  the boot path can't bypass it. First load = boot = no live audio -> no glitch confound.
|
|  Detour displaces 8 bytes at 0x4009083c:
|     4fefffd4  lea     -0x2c(%sp),%sp
|     48d77cfc  movem.l %d2-%d7/%a2-%a6,(%sp)
|  -> replaced by  4ef9 <zi_stub>  +  4e71 (nop) pad. The stub zeroes (once), then
|  replicates those two instructions and jumps to 0x40090844 (movea.l 0x34(%sp),%a4).
|  d0/d1/a0 are scratch at entry (args are on the stack), so no save/restore needed.
| =====================================================================

zi_stub:
    tst.l   g_done
    bne.b   zi_prologue
    moveq   #1, %d0
    move.l  %d0, g_done
    movea.l #0x40a955e0, %a0
    move.l  #0x8900, %d0        | 0x22400/4 longwords
    clr.l   %d1
zi_lp:
    move.l  %d1, (%a0)+
    subq.l  #1, %d0
    bne.b   zi_lp
zi_prologue:
    lea     -0x2c(%sp), %sp     | 4fefffd4  (displaced)
    movem.l %d2-%d7/%a2-%a6, (%sp)   | 48d77cfc  (displaced)
    jmp     0x40090844          | stock body, after the displaced 8 bytes

    .balign 4
g_done: .long 0
