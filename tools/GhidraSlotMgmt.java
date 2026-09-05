// Decompila el setter de slots y funciones de gestion para hallar el allocator
// (malloc/heap-top) y el struct de slot. Objetivo: encontrar RAM fija libre.
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

public class GhidraSlotMgmt extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] anchors = {
            0x40023f1cL,  // setter FUN_40023f1c(type,idx,..) — struct + posible malloc
            0x40024580L,  // static ref — gestion
            0x40024932L,  // static ref
            0x40024f24L,  // static ref
            0x40025548L,  // static ref (path/proj?)
            0x40029016L,  // static ref
        };
        String[] labels = {
            "slot_setter", "slotmgmt_4580", "slotmgmt_4932",
            "slotmgmt_4f24", "slotmgmt_5548", "slotmgmt_9016"
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
        println("\n[GhidraSlotMgmt] fin.");
    }
}
