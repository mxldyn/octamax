    .cpu 5407
    .text
| =====================================================================
|  STATIC state-table accessors — Layer 1, PURE PASSTHROUGH.
|
|  Stock computes a state-slot pointer inline as `base + slot*44` with
|  base = 0x46c90a78 (table A). 35 random-access sites do
|  `muls.l dS,REG` (REG = slot*44) then `addi.l/adda.l #0x46c90a78,REG`.
|
|  Layer 1 replaces ONLY that 6-byte base-add with `jsr sh_<REG>` (also
|  6 bytes, byte-exact). Each helper simply re-does the SAME add the inline
|  instruction did and returns:
|      sh_dN:  addi.l #0x46c90a78,%dN ; rts
|      sh_aN:  adda.l #0x46c90a78,%aN ; rts
|
|  Behaviour is byte-identical to stock for EVERY input value:
|    * result = base + REG, exactly the replaced instruction's result;
|    * CCR: the addi helper sets CCR from the add (identical to the inline
|      addi); the adda helper leaves CCR untouched (identical to the inline
|      adda) — rts touches neither. So CCR after the call == CCR after the
|      original inline op, for all callers.
|
|  This deliberately does NOT range-check or redirect. The earlier
|  dual-table redirect (bhi #0x1600 -> table B) crashed at BOOT: `bhi` is an
|  UNSIGNED compare, so it fired not only for real slots 129..255 but for
|  SENTINEL / out-of-range indices that reach the 5 UNGUARDED accessors
|  (e.g. a "no slot" -1 -> 0xffffffd4, or a default current-slot 255 ->
|  0x2bf4). Stock lets those land in adjacent initialised memory (flex /
|  settings) harmlessly; the redirect sent them into the boot-zeroed table B
|  at 0x40b00000 -> read 0 -> deref 0 -> VEC:04 ADDR:00000000 at startup.
|
|  Redirect + table-B init + two-sided bounds + sentinel handling all belong
|  to Layer 2 (after table B is a real, initialised table). Layer 1's only
|  job is to prove the jsr-to-cave plumbing (cave validity, jsr/rts in the
|  IPL7 voice path, CCR neutrality) is sound while staying provably stock.
|
|  The allocator loop-start (lea 0x46c90a78 @ 0x4002409c) is NOT converted.
| =====================================================================
    .equ TA,  0x46c90a78

sh_d0:  addi.l #TA,%d0
        rts
sh_d1:  addi.l #TA,%d1
        rts
sh_d2:  addi.l #TA,%d2
        rts
sh_d4:  addi.l #TA,%d4
        rts
sh_d5:  addi.l #TA,%d5
        rts
sh_a0:  adda.l #TA,%a0
        rts
sh_a2:  adda.l #TA,%a2
        rts
sh_a3:  adda.l #TA,%a3
        rts
sh_a5:  adda.l #TA,%a5
        rts
