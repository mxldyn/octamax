// Los handlers de paso del task de carga async FUN_4008445c. Clasificar cada paso:
// cargar datos (los queremos en HOT CHANGE) vs teardown de audio (los salteamos).
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

public class GhidraLoadSteps extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] anchors = {
            0x40084438L, 0x400843dcL, 0x400843c0L, 0x400843a4L, 0x40084388L,
            0x4008436cL, 0x40084350L, 0x400842e0L, 0x400842c4L, 0x400842a8L, 0x4008423cL
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
            if (f == null) { try { disassemble(a); f = createFunction(a, "step_" + Long.toHexString(anchors[i])); } catch (Exception e) {} }
            if (f == null) { println("==== step 0x" + Long.toHexString(anchors[i]) + ": SIN FUNCION"); continue; }
            long ep = f.getEntryPoint().getOffset();
            if (seen.contains(ep)) { println("\n==== 0x" + Long.toHexString(anchors[i]) + " -> misma func 0x" + Long.toHexString(ep)); continue; }
            seen.add(ep);
            DecompileResults res = dec.decompileFunction(f, 90, mon);
            println("\n============ step  anchor 0x" + Long.toHexString(anchors[i]) + "  func 0x" + Long.toHexString(ep) + " ============");
            if (res != null && res.decompileCompleted()) println(res.getDecompiledFunction().getC());
            else println("  (fallo)");
        }
        println("\n[GhidraLoadSteps] fin.");
    }
}
