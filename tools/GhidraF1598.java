import ghidra.app.script.GhidraScript; import ghidra.program.model.address.*; import ghidra.program.model.listing.*;
public class GhidraF1598 extends GhidraScript { public void run() throws Exception {
  var sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); var lst=currentProgram.getListing();
  var f=getFunctionContaining(sp.getAddress(0x40001598L));
  long ep=f.getEntryPoint().getOffset(), end=f.getBody().getMaxAddress().getOffset();
  println("FUN_40001598 0x"+Long.toHexString(ep)+" .. 0x"+Long.toHexString(end));
  for(long a=ep;a<=end && a<ep+0x80;){var i=lst.getInstructionAt(sp.getAddress(a));
    if(i!=null){println(String.format("%08x  %s",a,i.toString()));a+=i.getLength();}else{a+=2;}}
}}
