// Decompila las funciones del sample-slot table (Static/Flex), ancladas a
// strings de UI. Usa getFunctionContaining porque las anclas son mid-function.
//@category Octatrack
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.HashSet;

public class GhidraSlots extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] anchors = {
            0x400240d8L,  // 'NO FREE STATIC SLOTS!'  -> alloc_free_static_slot
            0x40024138L,  // 'NO FREE FLEX SLOTS!'    -> alloc_free_flex_slot
            0x40084cc0L,  // "Couldn't load STATIC[%d]" A
            0x400908c0L,  // "Couldn't load STATIC[%d]" B
            0x4008924aL,  // 'SLOT=%03d' serializer
            0x4006df80L,  // 'STATIC %03d' UI label
            0x4006b0a0L,  // 'LOAD FILE TO STATIC %d'
        };
        String[] labels = {
            "alloc_free_static_slot", "alloc_free_flex_slot",
            "load_static_A", "load_static_B",
            "serialize_sample_slots", "ui_static_slot_label", "load_file_to_static"
        };

        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        FunctionManager fm = currentProgram.getFunctionManager();
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        ConsoleTaskMonitor mon = new ConsoleTaskMonitor();
        HashSet<Long> seen = new HashSet<>();

        for (int i = 0; i < anchors.length; i++) {
            Address a = sp.getAddress(anchors[i]);
            Function f = fm.getFunctionContaining(a);
            if (f == null) {
                try { disassemble(a); f = createFunction(a, labels[i]); }
                catch (Exception e) { println("[!] no func @ " + a + ": " + e); }
            }
            if (f == null) { println("==== " + labels[i] + ": SIN FUNCION @ " + a + " ===="); continue; }
            long ep = f.getEntryPoint().getOffset();
            if (seen.contains(ep)) {
                println("\n==== " + labels[i] + " (ancla " + a + ") -> misma func 0x" + Long.toHexString(ep) + " ====");
                continue;
            }
            seen.add(ep);
            DecompileResults res = dec.decompileFunction(f, 120, mon);
            println("\n============ " + labels[i] + "   ancla " + a + "   func 0x" + Long.toHexString(ep) + " ============");
            if (res != null && res.decompileCompleted()) {
                println(res.getDecompiledFunction().getC());
            } else {
                println("  (fallo: " + (res != null ? res.getErrorMessage() : "null") + ")");
            }
        }
        println("\n[GhidraSlots] fin.");
    }
}
