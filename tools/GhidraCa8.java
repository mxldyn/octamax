import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.listing.*;
public class GhidraCa8 extends GhidraScript {
  AddressSpace sp;
  void callers(long t,String tag){ ReferenceManager rm=currentProgram.getReferenceManager();
    println("\n-- callers of 0x"+Long.toHexString(t)+" ("+tag+") --");
    int n=0; for(Reference r: rm.getReferencesTo(sp.getAddress(t))){ if(!r.getReferenceType().isCall()&&!r.getReferenceType().isJump())continue;
      Function f=getFunctionContaining(r.getFromAddress()); println("   @"+r.getFromAddress()+" in "+(f==null?"?":f.getName())); n++; }
    if(n==0) println("   (none direct)"); }
  public void run() throws Exception {
    sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
    callers(0x40056c40L,"clears 0x46104ca8");   // does the load call this?
    callers(0x40005c7cL,"FUN_40005214 caller1");
    callers(0x400972fcL,"FUN_40005214 caller2 (0x8000184c writer)");
    // and: is FUN_40056c40 or caseD reachable from the project load FUN_4008445c?
    // trace one level up from 0x40056c40's callers
  }
}
