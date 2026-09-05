// FUN_40006820 (audio-stop, arg mask) + su caller en 0x40096ad4 (justo tras el prep
// flex). Ver si es un stop MASKEABLE que podamos llamar salvando las voces de recorder.
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

public class GhidraAudioStop extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] anchors = {
            0x40006820L,  // audio-stop (mask arg)
            0x40096ad4L,  // caller just after flex prep
            0x400907e4L,  // apply_part call inside the flex/bank load (0x40009094 caller)
            0x40006890L,  // FUN_40006890 (called in reformat_confirm) — related?
        };
        String[] labels = { "audio_stop", "flex_reload_wrapper", "load_apply_part_site", "f6890" };
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
        println("\n[GhidraAudioStop] fin.");
    }
}
