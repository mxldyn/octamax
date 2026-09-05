// Recorder buffers: unload por-slot, alloc reservado, y region PCM. Confirmar que
// saltar el teardown de 0x80..0x87 preserva los buffers a traves de un pool swap.
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

public class GhidraRec extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] anchors = {
            0x40096300L,  // FUN_40096300(slot) — unload por-slot (que hace con recorders?)
            0x40095a90L,  // recorder alloc A
            0x400948ccL,  // recorder alloc B
            0x40008f84L,  // FUN_40008f84(track) — kill de una voz (dentro de stop_all_voices)
            0x40099668L,  // FUN_40099668(1,slot) — post-load (marca sounding?)
        };
        String[] labels = { "unload_slot", "rec_alloc_a", "rec_alloc_b", "kill_voice", "post_load_99668" };
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
        println("\n[GhidraRec] fin.");
    }
}
