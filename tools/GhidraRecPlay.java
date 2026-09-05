import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
public class GhidraRecPlay extends GhidraScript {
  AddressSpace sp; Listing lst;
  public void run() throws Exception {
    sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); lst=currentProgram.getListing();
    var f=getFunctionContaining(sp.getAddress(0x4000a8fcL));
    long ep=f.getEntryPoint().getOffset(), end=f.getBody().getMaxAddress().getOffset();
    println(String.format("===== FUN_4000a8fc (frame handler) 0x%08x .. 0x%08x len %d =====", ep,end,end-ep));
    for(long a=ep;a<=end;){Instruction i=lst.getInstructionAt(sp.getAddress(a));
      if(i==null){a+=2;continue;} println(String.format("%08x  %s",a,i.toString())); a+=i.getLength();}
  }
}
