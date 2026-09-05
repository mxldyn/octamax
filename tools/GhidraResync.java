// Los 4 call sites del re-sync FUN_400238a4 + los callbacks del job de carga de
// proyecto (FUN_40023cf8, FUN_40022dc4). Ubicar cual re-sync usa la carga de proyecto
// y donde termina (para limpiar g_hot).
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

public class GhidraResync extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] anchors = {
            0x40023936L, 0x40023a4aL, 0x40023afaL,  // re-sync sites (not the bank one 0x400239a2)
            0x40023cf8L,  // job cb1
            0x40022dc4L,  // job cb2
            0x4002325cL,  // project-load orchestrator entry
        };
        String[] labels = {"resync_site_23936","resync_site_23a4a","resync_site_23afa",
                           "job_cb1_23cf8","job_cb2_22dc4","proj_load_orch_2325c"};
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
            DecompileResults res = dec.decompileFunction(f, 110, mon);
            println("\n============ " + labels[i] + "  func 0x" + Long.toHexString(ep) + " ============");
            if (res != null && res.decompileCompleted()) println(res.getDecompiledFunction().getC());
            else println("  (fallo)");
        }
        println("\n[GhidraResync] fin.");
    }
}
