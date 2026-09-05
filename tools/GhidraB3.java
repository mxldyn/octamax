import ghidra.app.script.GhidraScript; import ghidra.program.model.address.*; import ghidra.program.model.listing.*;
public class GhidraB3 extends GhidraScript { public void run() throws Exception {
  var sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); var lst=currentProgram.getListing();
  for(long a: new long[]{0x40007f02L,0x40007a26L,0x40007efeL}){
    var i=lst.getInstructionAt(sp.getAddress(a));
    var i2=lst.getInstructionAt(sp.getAddress(a+(i!=null?i.getLength():2)));
    println(String.format("0x%08x  %s (len %d)  next: %s",a,i,i!=null?i.getLength():0,i2));
  }
}}
