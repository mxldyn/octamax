import ghidra.program.model.address.Address;
import ghidra.program.model.symbol.*;
import ghidra.program.model.listing.Function;
public class GhidraVCallers extends ghidra.app.script.GhidraScript {
  long[] T = { 0x40006820L, 0x40008f84L, 0x40008fe4L, 0x40096ab0L };
  public void run() throws Exception {
    ReferenceManager rm = currentProgram.getReferenceManager();
    for (long t: T){
      Address a=toAddr(t); int n=0;
      println("=== callers/refs to "+a+" ("+(getFunctionAt(a)!=null?getFunctionAt(a).getName():"?")+") ===");
      for (Reference r: rm.getReferencesTo(a)){
        if(!r.getReferenceType().isCall() && !r.getReferenceType().isJump() && !r.getReferenceType().isFlow()) continue;
        Function f=getFunctionContaining(r.getFromAddress());
        println("  "+r.getReferenceType()+" from "+r.getFromAddress()+" in "+(f==null?"<none>":f.getName()));
        n++;
      }
      println("  total flow refs: "+n);
    }
  }
}
