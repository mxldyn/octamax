import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.util.task.ConsoleTaskMonitor;
public class GhidraAssignLoop extends GhidraScript {
  DecompInterface dec; ConsoleTaskMonitor mon; FunctionManager fm; AddressSpace sp;
  void dc(long ep){
    Function f = fm.getFunctionContaining(sp.getAddress(ep));
    if (f==null){ println("no fn @ "+Long.toHexString(ep)); return; }
    DecompileResults res = dec.decompileFunction(f, 120, mon);
    println("\n===== "+f.getName()+" 0x"+Long.toHexString(f.getEntryPoint().getOffset())+" =====");
    if (res!=null && res.decompileCompleted()) println(res.getDecompiledFunction().getC());
    else println("(decompile failed)");
  }
  public void run() throws Exception {
    sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    fm = currentProgram.getFunctionManager();
    dec = new DecompInterface(); dec.openProgram(currentProgram);
    mon = new ConsoleTaskMonitor();
    ReferenceManager rm = currentProgram.getReferenceManager();
    // who calls the flex/bank load FUN_400905d4?
    println("=== callers of FUN_400905d4 (flex/bank load) ===");
    for (Reference r: rm.getReferencesTo(sp.getAddress(0x400905d4L))){
      if(!r.getReferenceType().isCall()) continue;
      Function f=getFunctionContaining(r.getFromAddress());
      println("  from "+r.getFromAddress()+" in "+(f==null?"<none>":f.getName()));
    }
    dc(0x400226f4L);   // flex-assign caller in the load cluster
    dc(0x4006437cL);   // calls FUN_40008fe4 twice (static path?)
    println("\n[GhidraAssignLoop] fin.");
  }
}
