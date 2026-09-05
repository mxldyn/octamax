import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
public class GhidraTrig extends GhidraScript {
  AddressSpace sp; Listing lst;
  void dump(long a0,long n,String tag){ println(String.format("\n== %s 0x%08x ==",tag,a0));
    for(long a=a0;a<a0+n;){Instruction i=lst.getInstructionAt(sp.getAddress(a));
      if(i!=null){println(String.format("%08x  %s",a,i.toString()));a+=i.getLength();}else{println(String.format("%08x [d]",a));a+=2;}}}
  public void run() throws Exception {
    sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); lst=currentProgram.getListing();
    Function f=getFunctionContaining(sp.getAddress(0x40005030L));
    long ep=f.getEntryPoint().getOffset(), end=f.getBody().getMaxAddress().getOffset();
    println("FUN_40005030 (trig) 0x"+Long.toHexString(ep)+" .. 0x"+Long.toHexString(end)+" len="+(end-ep));
    dump(ep, Math.min(end-ep+2, 0x180), "trig full");
  }
}
