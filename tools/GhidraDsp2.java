import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
public class GhidraDsp2 extends GhidraScript {
  public void run() throws Exception {
    Listing lst = currentProgram.getListing();
    InstructionIterator it = lst.getInstructions(true);
    java.util.LinkedHashMap<String,Integer> fns = new java.util.LinkedHashMap<>();
    // find immediates/operands touching the DSP MMIO window 0x2000_00xx
    String[] tags = {"20000000","20000004","20000008","2000000c","20000010","2000001c"};
    while (it.hasNext()){
      Instruction ins = it.next();
      String s = ins.toString();
      boolean hit=false;
      for (String t: tags){ if (s.contains(t)){ hit=true; break; } }
      if (!hit) continue;
      Function f = getFunctionContaining(ins.getAddress());
      String fn = f==null?"<none>":f.getName();
      fns.merge(fn,1,Integer::sum);
      println(String.format("%08x  %-38s [%s]", ins.getAddress().getOffset(), s, fn));
    }
    println("\n== functions touching DSP MMIO ==");
    for (var e: fns.entrySet()) println("  "+e.getKey()+"  x"+e.getValue());
  }
}
