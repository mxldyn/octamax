import ghidra.program.model.address.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.listing.*;
public class GhidraVMap extends ghidra.app.script.GhidraScript {
  public void run() throws Exception {
    ReferenceManager rm = currentProgram.getReferenceManager();
    long[] T = { 0x40006890L, 0x4000672cL };
    for (long t: T){
      Address a=toAddr(t);
      println("=== callers to "+a+" ("+(getFunctionAt(a)!=null?getFunctionAt(a).getName():"?")+") ===");
      for (Reference r: rm.getReferencesTo(a)){
        if(!r.getReferenceType().isCall() && !r.getReferenceType().isJump()) continue;
        Function f=getFunctionContaining(r.getFromAddress());
        println("  "+r.getReferenceType()+" from "+r.getFromAddress()+" in "+(f==null?"<none>":f.getName()));
      }
    }
    // dump FUN_4000672c body (DSP note-off primitive)
    Listing lst = currentProgram.getListing();
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    println("\n### FUN_4000672c body ###");
    for (long a=0x4000672cL; a<0x400067d0L; ) {
      Instruction ins = lst.getInstructionAt(sp.getAddress(a));
      if (ins!=null){ println(String.format("%08x  %s", a, ins.toString())); a+=ins.getLength(); }
      else { println(String.format("%08x  [no-instr]", a)); a+=2; }
    }
    // scan the load function 0x400905d4..0x40090800 for calls to stop primitives
    println("\n### load fn 0x400905d4 — calls of interest ###");
    long[] interest = {0x40006820L,0x40008f84L,0x40008fe4L,0x40096ab0L,0x40009094L,0x40006890L,0x4000672cL,0x40096300L};
    for (long a=0x400905d4L; a<0x40090800L; ) {
      Instruction ins = lst.getInstructionAt(sp.getAddress(a));
      if (ins==null){ a+=2; continue; }
      String s = ins.toString();
      for (long it: interest){ if (s.contains(Long.toHexString(it))) { println(String.format("%08x  %s", a, s)); break; } }
      a+=ins.getLength();
    }
    println("\n[GhidraVMap] fin.");
  }
}
