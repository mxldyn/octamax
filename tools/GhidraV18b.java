import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
public class GhidraV18b extends GhidraScript {
  AddressSpace sp; Listing lst;
  public void run() throws Exception {
    sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); lst=currentProgram.getListing();
    var f=getFunctionContaining(sp.getAddress(0x40007960L));
    long ep=f.getEntryPoint().getOffset();
    println("== FUN_40007960 head 0x"+Long.toHexString(ep)+" ==");
    for(long a=ep;a<ep+0x60;){var i=lst.getInstructionAt(sp.getAddress(a));
      if(i!=null){println(String.format("%08x  %s",a,i.toString()));a+=i.getLength();}else{a+=2;}}
    println("\n== callers of FUN_40007960 ==");
    var rm=currentProgram.getReferenceManager();
    for(Reference r: rm.getReferencesTo(sp.getAddress(0x40007960L))){ if(!r.getReferenceType().isCall())continue;
      var cf=getFunctionContaining(r.getFromAddress());
      println("   @"+r.getFromAddress()+" in "+(cf==null?"?":cf.getName())); }
  }
}
