import ghidra.app.script.GhidraScript; import ghidra.program.model.address.*; import ghidra.program.model.symbol.*;
import ghidra.program.model.listing.*;
public class GhidraFlexLoad2 extends GhidraScript {
  AddressSpace sp; ReferenceManager rm;
  void callers(long t,String tag){ println("\n-- callers of 0x"+Long.toHexString(t)+" ("+tag+") --");
    int n=0; for(Reference r: rm.getReferencesTo(sp.getAddress(t))){ if(!r.getReferenceType().isCall())continue;
      var f=getFunctionContaining(r.getFromAddress()); println("   <- "+(f==null?"?":f.getName())+" @"+r.getFromAddress()); n++; }
    if(n==0)println("   (none/root)"); }
  public void run() throws Exception {
    sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); rm=currentProgram.getReferenceManager();
    callers(0x40096548L,"flex pool alloc");
    // sample-related strings: find .wav / sample file handling
    println("\n-- sample/wav strings --");
    var lst=currentProgram.getListing();
    // search for likely sample-load functions: those calling both file-open (FUN_40016864) and flex-alloc
    // print functions that reference the flex-alloc AND look load-ish
  }
}
