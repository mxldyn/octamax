// Project-change / audiopool-reload orchestrator. Objetivo: hallar DONDE y POR QUE
// se detiene el audio al recargar el pool, y si el stop es separable de la recarga.
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

public class GhidraProjChange extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] anchors = {
            0x4002342aL,  // 'LOADING PROJECT' — orquestador de carga
            0x4006682cL,  // 'REFORMAT FLEX RAM' — reformat del pool
            0x40068b8aL,  // 'AUD POOL'
            0x40063eb8L,  // 'CHANGE PROJECT' handler
            0x400646bcL,  // project.work loader
            0x400905d4L,  // FUN_400905d4 (RAM load, de notas de bank)
            0x4008ded0L,  // FUN_4008ded0 (de notas)
        };
        String[] labels = {
            "project_load_orchestrator", "reformat_flex_ram", "aud_pool_handler",
            "change_project_handler", "project_work_loader", "ram_load_905d4", "ded0"
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
        println("\n[GhidraProjChange] fin.");
    }
}
