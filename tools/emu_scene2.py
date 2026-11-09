#!/usr/bin/env python3
# Valida patch_scene2.bin (sticky scenes v2) en el emulador ColdFire.
#
# Lo importante: el test 4 es la REGRESION que rompio v1 -- asignar una scene a mano
# despues de una transicion tiene que sobrevivir. v1 la pisaba.
import pathlib, struct
from unicorn import *
from unicorn.m68k_const import *

STUB = pathlib.Path("out/patch_scene2.bin").read_bytes()
SCENE_STUB = 0x400d6700     # host 1: FUN_40009094 (apply_part)
XF_STUB    = 0x400d6712     # host 2: FUN_4003f1b4 (crossfader)
SAVE_STUB  = 0x400d64e0     # chain target de host 1
XF_RESUME  = 0x4003f1bc     # retorno de host 2

PROJ   = 0x46d00000
PTRLOC = 0x46c82456
ACTPAT = 0x80000003
LAST_P, VALID, STICKY_A, STICKY_B, HOLD = (0x40af0260, 0x40af0261,   # tools/patch_ram.inc
                                           0x40af0262, 0x40af0263, 0x40af0264)
STRIDE, SEL = 0x18b2, 0x8ed90
SEED = {UC_M68K_REG_D0: 0x11111111, UC_M68K_REG_D1: 0x22222222,
        UC_M68K_REG_D2: 0x33333333, UC_M68K_REG_D3: 0x44444444,
        UC_M68K_REG_A0: 0x55555555, UC_M68K_REG_A1: 0x66666666}


def sel(pat):
    return PROJ + pat * STRIDE + SEL


def run(entry, act_pat, state, live, extra_writes=None, lazy=1):
    """state = (valid, last_p, sticky_a, sticky_b, hold); live = (a,b) del pattern activo"""
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    uc.mem_map(0x40000000, 0x400000)
    uc.mem_map(0x46000000, 0x1000000)
    uc.mem_map(0x80000000, 0x20000)
    uc.mem_map(0x41000000, 0x20000)
    uc.mem_map(0x40af0000, 0x1000)       # patch RAM block
    uc.mem_write(SCENE_STUB, STUB)
    uc.mem_write(PTRLOC, struct.pack(">I", PROJ))
    uc.mem_write(ACTPAT, bytes([act_pat]))
    uc.mem_write(0x800000d8, struct.pack('>I', lazy))   # PERSONALIZE: LAZY TRANSITIONS
    valid, last_p, sa, sb, hold = state
    for addr, val in ((VALID, valid), (LAST_P, last_p), (STICKY_A, sa),
                      (STICKY_B, sb), (HOLD, hold)):
        uc.mem_write(addr, bytes([val]))
    uc.mem_write(sel(act_pat), bytes(live))

    sp0 = 0x41018000
    uc.mem_write(sp0, struct.pack(">I", 0x401f0000))
    uc.reg_write(UC_M68K_REG_A7, sp0)
    for r, v in SEED.items():
        uc.reg_write(r, v)

    done = {"target": None, "sp": None, "regs": {}}
    stop_at = SAVE_STUB if entry == SCENE_STUB else XF_RESUME

    def hook(uc, addr, size, user):
        if addr == stop_at:
            done["target"] = addr
            done["sp"] = uc.reg_read(UC_M68K_REG_A7)
            for r in SEED:
                done["regs"][r] = uc.reg_read(r)
            uc.emu_stop()

    uc.hook_add(UC_HOOK_CODE, hook)
    wild = []

    def w(uc, acc, ad, sz, val, u):
        if not (0x46000000 <= ad < 0x47000000 or 0x40af0000 <= ad < 0x40af0600
                or 0x41000000 <= ad < 0x41020000):
            wild.append((hex(ad), sz, val))

    uc.hook_add(UC_HOOK_MEM_WRITE, w)
    err = None
    try:
        uc.emu_start(entry, 0, count=4000)
    except UcError as e:
        err = str(e)

    return {
        "err": err, "wild": wild, "sp0": sp0, **done,
        "live": list(uc.mem_read(sel(act_pat), 2)),
        "sticky": list(uc.mem_read(STICKY_A, 2)),
        "last_p": uc.mem_read(LAST_P, 1)[0],
        "valid": uc.mem_read(VALID, 1)[0],
        "hold": uc.mem_read(HOLD, 1)[0],
    }


FAILS = []


def check(name, r, *, want_live=None, want_sticky=None, want_hold=None,
          want_last=None, entry=SCENE_STUB, sp_delta=0):
    msgs = []
    if r["err"]:
        msgs.append("ERROR " + r["err"])
    if r["target"] is None:
        msgs.append("no llego al destino esperado")
    if r["wild"]:
        msgs.append("WILD WRITE " + str(r["wild"][:3]))
    if r["target"] is not None and r["sp"] != r["sp0"] + sp_delta:
        msgs.append("SP=%x esperado=%x" % (r["sp"], r["sp0"] + sp_delta))
    if entry == SCENE_STUB:  # host 1 restaura todo; host 2 solo hasta el prologo
        for rr, v in SEED.items():
            if r["regs"].get(rr) != v:
                msgs.append("reg no restaurado")
                break
    if want_live is not None and r["live"] != list(want_live):
        msgs.append("live=%s esperado=%s" % (r["live"], list(want_live)))
    if want_sticky is not None and r["sticky"] != list(want_sticky):
        msgs.append("sticky=%s esperado=%s" % (r["sticky"], list(want_sticky)))
    if want_hold is not None and r["hold"] != want_hold:
        msgs.append("HOLD=%d esperado=%d" % (r["hold"], want_hold))
    if want_last is not None and r["last_p"] != want_last:
        msgs.append("LAST_P=%d esperado=%d" % (r["last_p"], want_last))
    if r["valid"] != 0xa5:
        msgs.append("VALID=%02x" % r["valid"])
    ok = not msgs
    if not ok:
        FAILS.append(name)
    print(("PASS" if ok else "FAIL"), name)
    print("      live=%s sticky=%s LAST_P=%d HOLD=%d" %
          (r["live"], r["sticky"], r["last_p"], r["hold"]))
    for m in msgs:
        print("       -", m)


OLD = (0x0F, 0x0F)   # A16/B16 -- lo que el usuario traia
NEW = (0x0A, 0x0B)   # A11/B12 -- lo que tiene el Part destino
MAN = (0x03, 0x04)   # A4/B5   -- lo que el usuario asigna a mano

print("== host 1: FUN_40009094 (apply_part) ==\n")

check("1 primer arranque (VALID=0): adopta lo que haya, no impone",
      run(SCENE_STUB, 8, (0x00, 0, 0, 0, 0), NEW),
      want_live=NEW, want_sticky=NEW, want_last=8)

check("2 cambio de pattern (P5->P8): impone sticky y abre HOLD",
      run(SCENE_STUB, 8, (0xa5, 5, *OLD, 0), NEW),
      want_live=OLD, want_sticky=OLD, want_hold=4, want_last=8)

check("3 mismo pattern con HOLD>0: re-impone y descuenta",
      run(SCENE_STUB, 8, (0xa5, 8, *OLD, 4), NEW),
      want_live=OLD, want_sticky=OLD, want_hold=3, want_last=8)

check("4 REGRESION v1 - asignacion manual con HOLD=0: ADOPTA (gana el usuario)",
      run(SCENE_STUB, 8, (0xa5, 8, *OLD, 0), MAN),
      want_live=MAN, want_sticky=MAN, want_hold=0, want_last=8)

check("5 loader pisa durante HOLD: se restaura el sticky",
      run(SCENE_STUB, 8, (0xa5, 8, *OLD, 2), NEW),
      want_live=OLD, want_sticky=OLD, want_hold=1, want_last=8)

check("6 ya adoptado el manual, cambio de pattern: viaja el manual",
      run(SCENE_STUB, 3, (0xa5, 8, *MAN, 0), NEW),
      want_live=MAN, want_sticky=MAN, want_hold=4, want_last=3)

check("7 pattern alto (P255)",
      run(SCENE_STUB, 255, (0xa5, 0, *OLD, 0), NEW),
      want_live=OLD, want_sticky=OLD, want_last=255)

print("\n== host 2: FUN_4003f1b4 (crossfader) ==\n")

# el prologo desplazado reserva 0x3c bytes antes de saltar a XF_RESUME
check("8 crossfader: impone y ejecuta el prologo desplazado",
      run(XF_STUB, 8, (0xa5, 5, *OLD, 0), NEW),
      want_live=OLD, want_sticky=OLD, want_last=8,
      entry=XF_STUB, sp_delta=-0x3c)

check("9 crossfader con HOLD=0: adopta igual que host 1",
      run(XF_STUB, 8, (0xa5, 8, *OLD, 0), MAN),
      want_live=MAN, want_sticky=MAN, want_last=8,
      entry=XF_STUB, sp_delta=-0x3c)

# el movem del prologo desplazado tiene que haber guardado d2-d7/a2-a6 en (sp)
r = run(XF_STUB, 8, (0xa5, 5, *OLD, 0), NEW)
print("\n== prologo desplazado del crossfader ==")
print("   d2 guardado =", hex(r["regs"].get(UC_M68K_REG_D2, 0)),
      "(debe seguir siendo 0x33333333: enforce no lo toca)")

# --- gate: con LAZY TRANSITIONS apagado no debe tocar nada
r = run(SCENE_STUB, 8, (0xa5, 5, *OLD, 0), NEW, lazy=0)
ok = (r["target"] == SAVE_STUB and r["live"] == list(NEW)
      and r["last_p"] == 5 and r["sticky"] == list(OLD))
if not ok:
    FAILS.append("10 gate apagado")
print(("PASS" if ok else "FAIL"), "10 GATE apagado: encadena a save_stub sin tocar la seleccion")
print("      live=%s (debe seguir siendo %s), LAST_P=%d (sin cambiar)"
      % (r["live"], list(NEW), r["last_p"]))

print("\n" + ("TODOS OK" if not FAILS else "FALLAN: " + ", ".join(FAILS)))
