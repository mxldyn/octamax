// Struct de voz (0x800049d8, stride 0xA8) y funciones que lo leen/escriben.
// Objetivo: hallar el campo "slot fuente" para detectar tracks leyendo recorders 0x80-0x87.
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

public class GhidraVoiceSlot extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] anchors = {
            0x40000e50L,  // voice state getter (need_stop_predicate)
            0x40000ee0L,  // active voice query (0x800049d8[t*0xA8] byte0)
            0x4000672cL,  // voice stop (dentro de kill_voice) — revela campos del struct
            0x400a1030L,  // per-track algo (usado en prestep/reload)
            0x40095f90L,  // FUN_40095f90(slot,mode) — final del flex load (asigna a voz?)
        };
        String[] labels = { "voice_state_getter", "active_voice_query", "voice_stop", "per_track_a1030", "flex_finalize" };
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
        println("\n[GhidraVoiceSlot] fin.");
    }
}
