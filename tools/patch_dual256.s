    .cpu 5407
    .text
| =====================================================================
|  DUAL-256 redirect helpers — one family for the FOUR per-slot tables that travel together.
|
|  Contract (same proven shape as patch_state_helpers_b.s): each helper receives PRODUCT = idx*stride
|  in its register and returns the correct table pointer, redirecting the new slots into table B while
|  leaving every stock index byte-identical to the original `add #base,reg`:
|
|    SETTINGS (stride 0x448, base 0x100d5b30): idx<128 -> A ; idx 128..255 -> B ; idx>=256 -> A
|      (settings has NO template; A[128]=0x100f7f30 is OOB, so redirect starts at 128.)
|    STATE    (stride 44,    base 0x46c90a78): idx<128 -> A ; 128..255 -> B ; >=256 -> A  (ALIGNED w/ SETTINGS)
|    STRIDE4#1(stride 4,     base 0x46c920a4): idx<128 -> A ; 128..255 -> B ; >=256 -> A
|    STRIDE4#2(stride 4,     base 0x46c93a24): idx<128 -> A ; 128..255 -> B ; >=256 -> A
|
|  Two-sided product bounds send OOR/sentinel indices back to A = stock-safe; the redirect fires only
|  for real new slots. B-table layout INSIDE the 384 KB pool-reclaimed reserve [0x40a955e0,0x40af55e0)
|  (0x47700000 was in the pool tail -> overwritten at runtime -> wiped slot 129; the reserve is carved
|  below the pool by moving its base up, hardware-confirmed safe -- see build_dual256 POOL_RECLAIM).
|    SETTINGS-B 0x40a955e0 (+0x22400 -> ends 0x40ab79e0)   STATE-B 0x40ab79e0 (+0x1600)
|    STRIDE4-B1 0x40ab8fe0 (+0x200)   STRIDE4-B2 0x40ab91e0 (+0x200 -> ends 0x40ab93e0)
|  ADJ = B_base - idx0*stride, so B addr = product + ADJ = B_base + (idx-idx0)*stride.
| =====================================================================

|  ---- SETTINGS: A=0x100d5b30, redirect idx 128..255 ----
    .equ SET_A,    0x100d5b30
    .equ SET_LO,   0x22400            | 128*0x448  (product < LO -> A)
    .equ SET_HI,   0x44800            | 256*0x448  (product >= HI -> A, OOR)
    .equ SET_ADJ,  0x40a731e0         | SETTINGS_B(0x40a955e0) - 128*0x448
|  folded +0x10e field accessors:
    .equ SETF_A,   0x100d5c3e         | SET_A + 0x10e
    .equ SETF_ADJ, 0x40a732ee         | SET_ADJ + 0x10e

|  ---- STATE: A=0x46c90a78, redirect idx 129..255 (template A[128]) ----
    .equ ST_A,     0x46c90a78
    .equ ST_LO,    0x1600             | 128*44   (product <= LO -> A, incl template)
    .equ ST_HI,    0x2bf4             | 255*44   (product > HI -> A, OOR)
    .equ ST_ADJ,   0x40ab63e0         | STATE_B(0x40ab79e0) - 128*44

|  ---- STRIDE4#1: A=0x46c920a4, redirect idx 129..255 ----
    .equ S41_A,    0x46c920a4
    .equ S4_LO,    0x200              | 128*4
    .equ S4_HI,    0x3fc              | 255*4
    .equ S41_ADJ,  0x40ab8de0         | STRIDE4B1(0x40ab8fe0) - 128*4

|  ---- STRIDE4#2: A=0x46c93a24, redirect idx 129..255 ----
    .equ S42_A,    0x46c93a24
    .equ S42_ADJ,  0x40ab8fe0         | STRIDE4B2(0x40ab91e0) - 128*4

| SETTINGS data helpers (blo=below LO ->A, bhs HI ->A):
    .macro SETD reg
h_set_\reg:  cmpi.l #SET_LO,%\reg
        blo.b  9f
        cmpi.l #SET_HI,%\reg
        bhs.b  9f
        addi.l #SET_ADJ,%\reg
        rts
9:      addi.l #SET_A,%\reg
        rts
    .endm
    .macro SETA reg
h_set_\reg:  cmpa.l #SET_LO,%\reg
        blo.b  9f
        cmpa.l #SET_HI,%\reg
        bhs.b  9f
        adda.l #SET_ADJ,%\reg
        rts
9:      adda.l #SET_A,%\reg
        rts
    .endm
| folded +0x10e (data only, d0):
h_setf_d0:  cmpi.l #SET_LO,%d0
        blo.b  9f
        cmpi.l #SET_HI,%d0
        bhs.b  9f
        addi.l #SETF_ADJ,%d0
        rts
9:      addi.l #SETF_A,%d0
        rts

| STATE helpers (product<LO ->A ; LO<=p<=HI ->B ; p>HI ->A) -- idx=128->B[0], aligned w/ SETTINGS:
    .macro STD reg
h_st_\reg:  cmpi.l #ST_LO,%\reg
        blo.b  9f
        cmpi.l #ST_HI,%\reg
        bhi.b  9f
        addi.l #ST_ADJ,%\reg
        rts
9:      addi.l #ST_A,%\reg
        rts
    .endm
    .macro STA reg
h_st_\reg:  cmpa.l #ST_LO,%\reg
        blo.b  9f
        cmpa.l #ST_HI,%\reg
        bhi.b  9f
        adda.l #ST_ADJ,%\reg
        rts
9:      adda.l #ST_A,%\reg
        rts
    .endm

| STRIDE4#1 helpers:
    .macro S41D reg
h_s41_\reg: cmpi.l #S4_LO,%\reg
        blo.b  9f
        cmpi.l #S4_HI,%\reg
        bhi.b  9f
        addi.l #S41_ADJ,%\reg
        rts
9:      addi.l #S41_A,%\reg
        rts
    .endm
    .macro S41A reg
h_s41_\reg: cmpa.l #S4_LO,%\reg
        blo.b  9f
        cmpa.l #S4_HI,%\reg
        bhi.b  9f
        adda.l #S41_ADJ,%\reg
        rts
9:      adda.l #S41_A,%\reg
        rts
    .endm
| STRIDE4#2 helpers:
    .macro S42D reg
h_s42_\reg: cmpi.l #S4_LO,%\reg
        blo.b  9f
        cmpi.l #S4_HI,%\reg
        bhi.b  9f
        addi.l #S42_ADJ,%\reg
        rts
9:      addi.l #S42_A,%\reg
        rts
    .endm
    .macro S42A reg
h_s42_\reg: cmpa.l #S4_LO,%\reg
        blo.b  9f
        cmpa.l #S4_HI,%\reg
        bhi.b  9f
        adda.l #S42_ADJ,%\reg
        rts
9:      adda.l #S42_A,%\reg
        rts
    .endm

| ---- instantiate exactly the (table,reg) helpers the census requires ----
    SETD d0
    SETD d1
    SETD d2
    SETD d3
    SETA a1
    SETA a2
    SETA a3
    SETA a4
    STD  d0
    STD  d1
    STD  d2
    STD  d4
    STD  d5
    STA  a0
    STA  a2
    STA  a3
    STA  a5
    S41A a0
    S41D d0
    S42A a0
    S42D d0

| SLICE-DATA display buffer (stride 0x3000, A-base 0x46aaa980, 128-sized): idx>=128 -> ONE shared
| scratch in the reserve (only one slot is viewed at a time). Avoids writing 12 KB to the possibly-used
| 0x46c2a980 (= A + 128*0x3000). Receives PRODUCT=idx*0x3000 in d0. Placed LAST so the standard helper
| family layout (probed by emu_check at HELP_AT) is unchanged.
    .equ SLICE_A,       0x46aaa980
    .equ SLICE_LO,      0x180000          | 128*0x3000
    .equ SLICE_HI,      0x300000          | 256*0x3000
    .equ SLICE_SCRATCH, 0x40aba000        | shared 0x3000 buffer (reserve, AFTER T24-B now)
h_slice_d0:  cmpi.l #SLICE_LO,%d0
        blo.b  8f
        cmpi.l #SLICE_HI,%d0
        bhs.b  8f
        move.l #SLICE_SCRATCH,%d0
        rts
8:      addi.l #SLICE_A,%d0
        rts

| ---- Wave 8: STATIC streaming state table (stride 24, A=0x46947c56, 128 entries). Touched by 0x40016fe8
| (write), 0x40017fa0 (FN-CLEAR tail, read/unlink), 0x40017e0c / 0x40017ec0 (read, via 0x400180c8). All
| via FN-VIEW/FN-CLEAR (STATIC-only; idx>=128 is OOB in stock -> the next table is at 0x4694887c). Two
| access shapes: `adda #A,aN` (aN=idx*24) and `lea A,a0` then `a0@(0,d0)` (d0=idx*24+field). B-table in
| the reserve, contiguous right after stride4-B2 (inside the boot-zeroed HOLE).
    .equ T24_A,    0x46947c56
    .equ T24_LO,   0xC00              | 128*24 (product < LO -> A)
    .equ T24_HI,   0x1800             | 256*24 (product >= HI -> A, OOR)
    .equ T24_ADJ,  0x40ab87e0         | T24_B(0x40ab93e0) - 128*24
    .macro T24A reg
h_t24_\reg: cmpa.l #T24_LO,%\reg
        blo.b  9f
        cmpa.l #T24_HI,%\reg
        bhs.b  9f
        adda.l #T24_ADJ,%\reg
        rts
9:      adda.l #T24_A,%\reg
        rts
    .endm
    T24A a0
    T24A a1
| offset form: d0 = idx*24 (+ small field) ; set a0 so a0 + d0 hits the right table:
h_t24off_a0: cmpi.l #T24_LO,%d0
        blo.b  9f
        cmpi.l #T24_HI,%d0
        bhs.b  9f
        movea.l #T24_ADJ,%a0
        rts
9:      movea.l #T24_A,%a0
        rts

| ---- Wave 10: voice-bind resolver 0x4000f450 STRIDE4 base-select (lea-base form). The site does
| `lea #S4N_A,a0` then later `lea a0@(0,idx:l:4),a0`. We replace the base-load with a jsr that sets a0
| to the A base (idx<128 or >=256) OR the ADJ base (=B - 128*4), so a0 + idx*4 lands in STRIDE4-B[idx-128].
| Input: d1 = slot idx (live in the resolver's STATIC branch). Output: a0 = base. One helper per table.
| CRITICAL: at 0x4000f4f4 the stock `lea #S42,a0` does NOT touch flags, and the very next insn
| `beqs 0x4000f502` (0x4000f4fa) selects STATIC-S42 vs FLEX-S41 on Z=(type==0) set by `movel sp@56,d2`
| just before. Replacing the lea with a jsr whose body runs `cmpi` CLOBBERS that Z -> wrong table ->
| gen-mismatch -> spurious voice reset. So h_s42base_a0 MUST restore Z=(d2==0) before returning
| (d2 still holds the type here). h_s41base_a0 (site 0x4000f4fc) is followed by a non-branch, but we
| keep it symmetric/harmless.
h_s41base_a0: cmpi.l #128,%d1
        blo.b  1f
        cmpi.l #256,%d1
        bhs.b  1f
        movea.l #S41_ADJ,%a0
        tst.l  %d2
        rts
1:      movea.l #S41_A,%a0
        tst.l  %d2
        rts
h_s42base_a0: cmpi.l #128,%d1
        blo.b  2f
        cmpi.l #256,%d1
        bhs.b  2f
        movea.l #S42_ADJ,%a0
        tst.l  %d2
        rts
2:      movea.l #S42_A,%a0
        tst.l  %d2
        rts
