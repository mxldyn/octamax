import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.util.task.ConsoleTaskMonitor;
public class GhidraApplyPart extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    FunctionManager fm = currentProgram.getFunctionManager();
    DecompInterface dec = new DecompInterface();
    dec.openProgram(currentProgram);
    ConsoleTaskMonitor mon = new ConsoleTaskMonitor();
    long[] fns = {0x40009094L};
    for (long ep: fns){
      Function f = fm.getFunctionContaining(sp.getAddress(ep));
      if (f==null){ println("no fn @ "+Long.toHexString(ep)); continue; }
      DecompileResults res = dec.decompileFunction(f, 120, mon);
      println("\n===== "+f.getName()+" 0x"+Long.toHexString(f.getEntryPoint().getOffset())+" =====");
      if (res!=null && res.decompileCompleted()) println(res.getDecompiledFunction().getC());
      else println("(decompile failed)");
    }
    // scan apply_part for calls of interest
    Listing lst = currentProgram.getListing();
    long[] interest = {0x40006820L,0x40008f84L,0x40008fe4L,0x40096ab0L,0x40006890L,0x4000672cL};
    println("\n### apply_part calls of interest ###");
    Function f = fm.getFunctionContaining(sp.getAddress(0x40009094L));
    long a=f.getEntryPoint().getOffset(), end=f.getBody().getMaxAddress().getOffset();
    for (; a<=end; ){
      Instruction ins = lst.getInstructionAt(sp.getAddress(a));
      if (ins==null){ a+=2; continue; }
      String s=ins.toString();
      for (long it: interest){ if (s.contains(Long.toHexString(it))){ println(String.format("%08x  %s",a,s)); break; } }
      a+=ins.getLength();
    }
    println("\n[GhidraApplyPart] fin.");
  }
}
