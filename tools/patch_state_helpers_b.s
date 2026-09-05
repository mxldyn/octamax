    .cpu 5407
    .text
| =====================================================================
|  STATIC state-table accessors — REAL dual table (table B in verified free DDR).
|
|  Each helper receives PRODUCT = slot*44 in REG and returns the slot pointer:
|      product <= 0x1600  (idx 0..128) -> + 0x46c90a78   table A (incl. the index-128
|                                                          TEMPLATE at table-A end 0x46c92078)
|      0x1600 < product <= 0x2bf4 (idx 129..255) -> + 0x46c94a00   table B  (0x46c96000-0x1600)
|      product >  0x2bf4  (idx >= 256, sentinels/OOR) -> + 0x46c90a78   table A (stock-safe)
|
|  TWO-SIDED bound: the low side (bls #0x1600) keeps 0..128 in table A so the template and the
|  voice empty-slot sentinel are byte-identical to stock; the high side (bhi #0x2bf4) sends any
|  index >= 256 (a "no slot" -1 -> 0xffffffd4, etc.) back to table A = stock behaviour, so the
|  redirect fires ONLY for real slots 129..255. Table B [0x46c96000, 0x46c97600) is the window
|  verified free (0 static refs; tools/emu_ddr_free.py). Slot 128's table-B cell (0x46c96000) is
|  unused (128 -> table A), so usable slots are 0..127 + 129..255 = 255.
|
|  ADJ_B = 0x46c96000 - 0x1600 = 0x46c94a00, so table-B addr = product + ADJ_B
|        = 0x46c96000 + (idx-128)*44.
| =====================================================================
    .equ TA,    0x46c90a78          | table A base
    .equ ADJ_B, 0x46c94a00          | table B: 0x46c96000 - 0x1600
    .equ LO,    0x1600              | 128*44
    .equ HI,    0x2bf4              | 255*44

    .macro DHELP name reg
\name:  cmpi.l #LO,%\reg
        bls.b  1f
        cmpi.l #HI,%\reg
        bhi.b  1f
        addi.l #ADJ_B,%\reg
        rts
1:      addi.l #TA,%\reg
        rts
    .endm

    .macro AHELP name reg
\name:  cmpa.l #LO,%\reg
        bls.b  1f
        cmpa.l #HI,%\reg
        bhi.b  1f
        adda.l #ADJ_B,%\reg
        rts
1:      adda.l #TA,%\reg
        rts
    .endm

    DHELP sh_d0 d0
    DHELP sh_d1 d1
    DHELP sh_d2 d2
    DHELP sh_d4 d4
    DHELP sh_d5 d5
    AHELP sh_a0 a0
    AHELP sh_a2 a2
    AHELP sh_a3 a3
    AHELP sh_a5 a5
