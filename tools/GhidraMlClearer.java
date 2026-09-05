import ghidra.app.script.GhidraScript; import ghidra.program.model.address.*; import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
public class GhidraMlClearer extends GhidraScript {
  AddressSpace sp; Listing lst; ReferenceManager rm;
  void ctx(long site,long fnEp,String tag){
    println("\n== "+tag+" clr site 0x"+Long.toHexString(site)+" (fn 0x"+Long.toHexString(fnEp)+") ==");
    for(long a=fnEp;a<site+6 && a<fnEp+0x100;){var i=lst.getInstructionAt(sp.getAddress(a));
      if(i!=null){String s=i.toString(); if(s.contains("46c9")||s.contains("46c8")||s.contains("(0x10,A")||a==fnEp||s.contains("adda")||s.contains("lea")) println(String.format("%08x  %s",a,s)); a+=i.getLength();}else a+=2;}
    // callers
    println("  callers:");
    var f=getFunctionContaining(sp.getAddress(fnEp));
    for(Reference r: rm.getReferencesTo(sp.getAddress(fnEp))){ if(!r.getReferenceType().isCall())continue;
      var cf=getFunctionContaining(r.getFromAddress()); println("    <- "+(cf==null?"?":cf.getName())+" @"+r.getFromAddress()); }
  }
  public void run() throws Exception {
    sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); lst=currentProgram.getListing(); rm=currentProgram.getReferenceManager();
    ctx(0x4009385e, 0x40093814, "FUN_40093814");
    ctx(0x40098c18, 0x40098a5c, "FUN_40098a5c");
    ctx(0x400986e6, 0x400986c8, "FUN_400986c8");
  }
}
