// Loader de sample FLEX -> RAM pool. Objetivo del lazy swap: hallar el pool base,
// el descriptor por-slot (puntero PCM + len), y el loop que sobrescribe el pool.
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

public class GhidraFlexLoad extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] anchors = {
            0x400878c2L,  // LOAD_24BIT_FLEX area — loader de sample flex a RAM
            0x40090974L,  // "Couldn't load FLEX[%d]" / "Successfully loaded FLEX" section
            0x40084be6L,  // "Couldn't load FLEX[%d]" en loader task FUN_4008445c
            0x400cc834L,  // 'FLEX FORMAT' ref (config de formato)
        };
        String[] labels = { "flex_sample_loader", "flex_load_section", "loader_task_flex", "flex_format_cfg" };
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
        println("\n[GhidraFlexLoad] fin.");
    }
}
