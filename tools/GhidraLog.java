import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
public class GhidraLog extends GhidraScript {
  AddressSpace sp; Listing lst; ReferenceManager rm;
  void refs(long t,String tag){ println("\n-- refs to 0x"+Long.toHexString(t)+" ("+tag+") --");
    for(Reference r: rm.getReferencesTo(sp.getAddress(t))){ Function f=getFunctionContaining(r.getFromAddress());
      println("   "+r.getReferenceType()+" @"+r.getFromAddress()+" in "+(f==null?"?":f.getName())); } }
  void dump(long a0,long n,String tag){ println("\n== "+tag+" 0x"+Long.toHexString(a0)+" ==");
    for(long a=a0;a<a0+n;){Instruction i=lst.getInstructionAt(sp.getAddress(a));
      if(i!=null){println(String.format("%08x  %s",a,i.toString()));a+=i.getLength();}else{a+=2;}}}
  public void run() throws Exception {
    sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); lst=currentProgram.getListing(); rm=currentProgram.getReferenceManager();
    refs(0x400b367aL,"/LOG %s.txt");
    refs(0x400b369eL,"DEBUG");
    // find the write primitive: look near the open helper FUN_40016864 for a sibling 'write'
    refs(0x40016864L,"FUN_40016864 open");
  }
}
