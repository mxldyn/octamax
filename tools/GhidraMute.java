import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
public class GhidraMute extends GhidraScript {
  AddressSpace sp; Listing lst;
  void dump(long a0,long n){ println(String.format("\n== 0x%08x ==",a0));
    for(long a=a0;a<a0+n;){Instruction i=lst.getInstructionAt(sp.getAddress(a));
      if(i!=null){println(String.format("%08x  %s",a,i.toString()));a+=i.getLength();}else{println(a+" [d]");a+=2;}}}
  void callers(long t){ ReferenceManager rm=currentProgram.getReferenceManager();
    Function tf=getFunctionContaining(sp.getAddress(t));
    println(String.format("\n-- callers of 0x%08x (%s) --",t,tf==null?"?":tf.getName()));
    for(Reference r: rm.getReferencesTo(sp.getAddress(t))){ if(!r.getReferenceType().isCall()&&!r.getReferenceType().isJump())continue;
      Function f=getFunctionContaining(r.getFromAddress()); println("   "+r.getReferenceType()+" @"+r.getFromAddress()+" in "+(f==null?"?":f.getName())); } }
  public void run() throws Exception {
    sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); lst=currentProgram.getListing();
    Function f=getFunctionContaining(sp.getAddress(0x40005214L));
    long ep=f==null?0x40005214L:f.getEntryPoint().getOffset();
    dump(ep, 0x400052f0L-ep>0? Math.min(0xd0,0x400052f0L-ep):0xd0);
    callers(ep);
  }
}
