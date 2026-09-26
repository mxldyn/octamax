#!/usr/bin/env python3
# Valida patch_led.bin: un track EN TRANSICION se pinta con brillo reducido.
# Lo critico aca es el stack: FUN_40083eb0 no popea por llamada, limpia 0x20 al
# final, asi que el stub tiene que empujar exactamente 16 bytes y no limpiar nada.
import pathlib, struct
from unicorn import *
from unicorn.m68k_const import *

STUB_ADDR = 0x400d6800
STUB = pathlib.Path("out/patch_led.bin").read_bytes()
RESUME = 0x40083fc4
TRK_PART = 0x8000182a
ACT_PART = 0x80000002
SETLEVEL = 0x400135b0          # A3 apunta aca
LVL_NORM, LVL_DIRTY = 0xF, 0x5


MIDI_MODE = 0x80000012


def run(track, part_of_track, active_part, lazy=1, midi=0):
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    uc.mem_map(0x40000000, 0x400000)
    uc.mem_map(0x80000000, 0x20000)
    uc.mem_map(0x41000000, 0x20000)
    uc.mem_map(0x46000000, 0x200000)
    uc.mem_write(MIDI_MODE, struct.pack('>I', midi))
    uc.mem_write(STUB_ADDR, STUB)
    # FUN_400135b0 simulado: un rts, para capturar los argumentos ya empujados
    uc.mem_write(SETLEVEL, b"\x4e\x75")
    uc.mem_write(TRK_PART + track, bytes([part_of_track]))
    uc.mem_write(ACT_PART, bytes([active_part]))
    uc.mem_write(0x800000d8, struct.pack('>I', lazy))   # PERSONALIZE: LAZY TRANSITIONS
    uc.mem_write(0x800000d8, struct.pack('>I', lazy))

    sp0 = 0x41018000
    uc.reg_write(UC_M68K_REG_A7, sp0)
    uc.reg_write(UC_M68K_REG_D5, track)
    uc.reg_write(UC_M68K_REG_D2, 0x40)       # led id
    uc.reg_write(UC_M68K_REG_D3, 0x41)       # led id + 1
    uc.reg_write(UC_M68K_REG_A3, SETLEVEL)
    uc.reg_write(UC_M68K_REG_D4, 0x2)        # color, no debe tocarse

    calls = []
    res = {"resumed": False, "sp": None}

    def hook(uc, addr, size, user):
        if addr == SETLEVEL:
            sp = uc.reg_read(UC_M68K_REG_A7)
            # (sp)=retaddr, 4(sp)=id, 8(sp)=level
            idv = struct.unpack(">I", uc.mem_read(sp + 4, 4))[0]
            lvl = struct.unpack(">I", uc.mem_read(sp + 8, 4))[0]
            calls.append((idv, lvl))
        elif addr == RESUME:
            res["resumed"] = True
            res["sp"] = uc.reg_read(UC_M68K_REG_A7)
            res["regs"] = {r: uc.reg_read(r) for r in
                           (UC_M68K_REG_D2, UC_M68K_REG_D3, UC_M68K_REG_D4,
                            UC_M68K_REG_D5, UC_M68K_REG_A3)}
            uc.emu_stop()

    uc.hook_add(UC_HOOK_CODE, hook)
    err = None
    try:
        uc.emu_start(STUB_ADDR, 0, count=3000)
    except UcError as e:
        err = str(e)
    return {"calls": calls, "err": err, "sp0": sp0, **res}


FAILS = []


def check(name, r, want_lvl):
    m = []
    if r["err"]:
        m.append("ERROR " + r["err"])
    if not r["resumed"]:
        m.append("no llego a RESUME 0x%x" % RESUME)
    if len(r["calls"]) != 2:
        m.append("llamadas a setlevel=%d, esperadas 2" % len(r["calls"]))
    else:
        for i, (idv, lvl) in enumerate(r["calls"]):
            if lvl != want_lvl:
                m.append("call%d level=0x%x esperado 0x%x" % (i, lvl, want_lvl))
        if [c[0] for c in r["calls"]] != [0x40, 0x41]:
            m.append("ids=%s esperados [0x40,0x41]" % [hex(c[0]) for c in r["calls"]])
    # el stub debe dejar 16 bytes empujados y NO limpiarlos
    if r["resumed"] and r["sp"] != r["sp0"] - 16:
        m.append("SP=%x esperado %x (16 bytes empujados, sin limpiar)"
                 % (r["sp"], r["sp0"] - 16))
    if r["resumed"]:
        for reg, want in ((UC_M68K_REG_D2, 0x40), (UC_M68K_REG_D3, 0x41),
                          (UC_M68K_REG_D4, 0x2), (UC_M68K_REG_A3, SETLEVEL)):
            if r["regs"][reg] != want:
                m.append("registro del loop alterado")
                break
    ok = not m
    if not ok:
        FAILS.append(name)
    print(("PASS" if ok else "FAIL"), name)
    print("      levels=%s" % [hex(c[1]) for c in r["calls"]])
    for x in m:
        print("       -", x)


check("1 track NO en transicion (part 1 == activo 1): brillo normal",
      run(track=3, part_of_track=1, active_part=1), LVL_NORM)
check("2 track EN transicion (part 1 != activo 2): brillo reducido",
      run(track=3, part_of_track=1, active_part=2), LVL_DIRTY)
check("3 track 0, en transicion",
      run(track=0, part_of_track=5, active_part=0), LVL_DIRTY)
check("4 track 7 (ultimo), no en transicion",
      run(track=7, part_of_track=4, active_part=4), LVL_NORM)

check("5 GATE apagado: brillo de fabrica aunque este en transicion",
      run(track=3, part_of_track=1, active_part=2, lazy=0), LVL_NORM)

check("6 MODO MIDI: brillo de fabrica aunque la pista de audio este en transicion",
      run(track=3, part_of_track=1, active_part=2, midi=1), LVL_NORM)
check("7 MODO MIDI apagado explicitamente: sigue atenuando",
      run(track=3, part_of_track=1, active_part=2, midi=0), LVL_DIRTY)

print("\n" + ("TODOS OK" if not FAILS else "FALLAN: " + ", ".join(FAILS)))
