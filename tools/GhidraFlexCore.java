// Nucleo del pool FLEX: prep (borra/reparticiona?), loader por-slot, y el mapeo
// voz->slot. Decide si el lazy swap es posible (prep aditivo vs wipe total).
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

public class GhidraFlexCore extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] anchors = {
            0x40096a5cL,  // prep del pool FLEX (clave: wipe o aditivo?)
            0x40096548L,  // FUN_40096548(slotIdx,1) — carga 1 slot flex a RAM
            0x4009395cL,  // prep del pool STATIC (comparacion)
            0x40093980L,  // load 1 slot static
            0x40000e50L,  // voice state getter (usado por need_stop_predicate)
        };
        String[] labels = { "flex_pool_prep", "flex_slot_load", "static_pool_prep", "static_slot_load", "voice_state_getter" };
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        FunctionManager fm = currentProgram.getFunctionManager();
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        ConsoleTaskMonitor mon = new ConsoleTaskMonitor();
        HashSet<Long> seen = new HashSet<>();
        for (int i = 0; i < anchors.length; i++) {
            Address a = sp.getAddress(anchors[i]);
            Function f = fm.getFunctionContaining(a);
            if (f == null) { try { disassemble(a); f = createFunction(a, labels[i]); } catch (Exception e) {} }
            if (f == null) { println("==== " + labels[i] + ": SIN FUNCION @ " + a); continue; }
            long ep = f.getEntryPoint().getOffset();
            if (seen.contains(ep)) { println("\n==== " + labels[i] + " -> misma func 0x" + Long.toHexString(ep)); continue; }
            seen.add(ep);
            DecompileResults res = dec.decompileFunction(f, 120, mon);
            println("\n============ " + labels[i] + "   func 0x" + Long.toHexString(ep) + " ============");
            if (res != null && res.decompileCompleted()) println(res.getDecompiledFunction().getC());
            else println("  (fallo)");
        }
        println("\n[GhidraFlexCore] fin.");
    }
}
