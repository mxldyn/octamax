// Callees del orquestador de carga FUN_4002325c — buscar quien RESETEA/vacía los
// recording buffers durante la carga de proyecto (a pesar de preservar las paginas).
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

public class GhidraRecClear extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] anchors = {
            0x4009b5acL,  // FUN_4009b5ac(0) — recorder region, called in load orch + reformat
            0x4004d894L,  // FUN_4004d894 — load orch tail
            0x40064bc0L,  // FUN_40064bc0 — load orch
            0x4009b270L,  // FUN_4009b270 — recorder query (from os_apply_flash)
        };
        String[] labels = {"rec_5ac","load_d894","load_64bc0","rec_query_b270"};
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
        println("\n[GhidraRecClear] fin.");
    }
}
