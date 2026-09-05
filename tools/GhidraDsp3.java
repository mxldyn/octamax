import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
public class GhidraDsp3 extends GhidraScript {
  AddressSpace sp; Listing lst;
  void dump(long a0,long n){
    println(String.format("\n== 0x%08x ==",a0));
    for (long a=a0;a<a0+n;){ Instruction ins=lst.getInstructionAt(sp.getAddress(a));
      if(ins!=null){println(String.format("%08x  %s",a,ins.toString()));a+=ins.getLength();}else{println(String.format("%08x [d]",a));a+=2;} }
  }
  void callers(long t){
    ReferenceManager rm=currentProgram.getReferenceManager();
    println(String.format("\n-- callers of 0x%08x (%s) --",t, getFunctionAt(sp.getAddress(t))!=null?getFunctionAt(sp.getAddress(t)).getName():"?"));
    for(Reference r: rm.getReferencesTo(sp.getAddress(t))){ if(!r.getReferenceType().isCall())continue;
      Function f=getFunctionContaining(r.getFromAddress()); println("   @"+r.getFromAddress()+" in "+(f==null?"?":f.getName())); }
  }
  public void run() throws Exception {
    sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); lst=currentProgram.getListing();
    dump(0x4000a8fc,0x40);          // command sender
    callers(0x4000a8fcL);
    callers(0x400df066L);
    callers(0x400df0f4L);
    callers(0x400e0d7eL);
    callers(0x40001d4cL);           // P-mem DSP loader
    callers(0x40001b18L);           // X/Y DSP loader
  }
}
