// Los handlers sincronos del menu PROJECT (cluster 0x40063xxx que llama panic).
// Buscar el de "cargar proyecto elegido": estructura [panic; kill; set proj; post load].
// Ese es el template para HOT CHANGE (replicar el post-load, saltar el teardown).
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

public class GhidraProjHandlers extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] anchors = {
            0x40063590L,  // reload handler (menu vtable 0x400cc460)
            0x400637c4L,  // panic caller
            0x400638eeL,  // panic caller
            0x40063a12L,  // panic caller
            0x40063b98L,  // panic caller (near bank poster jmp 0x40063c14)
            0x40063c22L,  // panic caller (near poster)
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
            if (f == null) { try { disassemble(a); f = createFunction(a, "h_" + Long.toHexString(anchors[i])); } catch (Exception e) {} }
            if (f == null) { println("==== 0x" + Long.toHexString(anchors[i]) + ": SIN FUNCION"); continue; }
            long ep = f.getEntryPoint().getOffset();
            if (seen.contains(ep)) { println("\n==== anchor 0x" + Long.toHexString(anchors[i]) + " -> misma func 0x" + Long.toHexString(ep)); continue; }
            seen.add(ep);
            DecompileResults res = dec.decompileFunction(f, 110, mon);
            println("\n============ anchor 0x" + Long.toHexString(anchors[i]) + "  func 0x" + Long.toHexString(ep) + " ============");
            if (res != null && res.decompileCompleted()) println(res.getDecompiledFunction().getC());
            else println("  (fallo)");
        }
        println("\n[GhidraProjHandlers] fin.");
    }
}
