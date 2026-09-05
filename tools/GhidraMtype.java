import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.util.task.ConsoleTaskMonitor;
public class GhidraMtype extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    Listing lst = currentProgram.getListing();
    // Dump the two machine-type WRITE sites in context (listing).
    long[][] r = {{0x4000dfc0L,0x40L},{0x4000e730L,0x40L}};
    for (long[] rg: r){
      println(String.format("\n== ctx 0x%08x ==", rg[0]));
      for (long a=rg[0]; a<rg[0]+rg[1]; ){
        Instruction ins = lst.getInstructionAt(sp.getAddress(a));
        if (ins!=null){ println(String.format("%08x  %s",a,ins.toString())); a+=ins.getLength(); }
        else { println(String.format("%08x  [d]",a)); a+=2; }
      }
    }
    // Who writes 0x46c80354 with a STATIC-ish constant, in a loop over 8 tracks? show funcs
    ReferenceManager rm = currentProgram.getReferenceManager();
    println("\n== all refs to 0x46c80354 (machine-type[0]) with enclosing fn ==");
    for (Reference ref: rm.getReferencesTo(sp.getAddress(0x46c80354L))){
      Function f=getFunctionContaining(ref.getFromAddress());
      println("  "+ref.getReferenceType()+" @"+ref.getFromAddress()+" in "+(f==null?"?":f.getName()));
    }
  }
}
