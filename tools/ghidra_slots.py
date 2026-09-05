# Ghidra post-script — decompila las funciones del sample-slot table (Static/Flex).
# Ancladas a strings de UI. Se ejecuta via analyzeHeadless -process.
# @category Octatrack
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

# direccion ANCLA (mid-function) -> etiqueta. Decompilamos la funcion contenedora.
ANCHORS = [
    (0x400240d8, "alloc_free_static_slot"),   # 'NO FREE STATIC SLOTS!'
    (0x40024138, "alloc_free_flex_slot"),     # 'NO FREE FLEX SLOTS!'  (comparacion)
    (0x40084cc0, "load_static_A"),            # "Couldn't load STATIC[%d]"
    (0x400908c0, "load_static_B"),            # "Couldn't load STATIC[%d]"
    (0x4008924a, "serialize_sample_slots"),   # 'SLOT=%03d' / 'TYPE=STATIC'
    (0x4006df80, "ui_static_slot_label"),     # 'STATIC %03d'
    (0x4006b0a0, "load_file_to_static"),      # 'LOAD FILE TO STATIC %d'
]

af = currentProgram.getAddressFactory().getDefaultAddressSpace()  # noqa: F821
fm = currentProgram.getFunctionManager()                          # noqa: F821
dec = DecompInterface()
dec.openProgram(currentProgram)  # noqa: F821
mon = ConsoleTaskMonitor()

seen = set()
for vaddr, label in ANCHORS:
    a = af.getAddress(vaddr)
    f = fm.getFunctionContaining(a)
    if f is None:
        try:
            disassemble(a)                    # noqa: F821
            f = createFunction(a, label)      # noqa: F821
        except Exception as e:
            print("[!] no function at 0x%x: %s" % (vaddr, e))
            continue
    ep = f.getEntryPoint().getOffset()
    if ep in seen:
        print("\n==== %s @ anchor 0x%08x -> same func as above (0x%08x) ====" % (label, vaddr, ep))
        continue
    seen.add(ep)
    res = dec.decompileFunction(f, 120, mon)
    print("\n==================== %s   anchor 0x%08x   func 0x%08x ====================" %
          (label, vaddr, ep))
    if res and res.decompileCompleted():
        print(res.getDecompiledFunction().getC())
    else:
        print("  (decompile failed: %s)" % (res.getErrorMessage() if res else "no result"))

print("\n[ghidra_slots] done.")
