import ghidra.app.script.GhidraScript; import ghidra.program.model.address.*; import ghidra.program.model.listing.*;
public class GhidraReloadCfm extends GhidraScript { public void run() throws Exception {
  var sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); var lst=currentProgram.getListing();
  var fm=currentProgram.getFunctionManager();
  var f=fm.getFunctionContaining(sp.getAddress(0x40063bf8L));
  long ep=f.getEntryPoint().getOffset(), end=f.getBody().getMaxAddress().getOffset();
  println("FUN_40063bf8 0x"+Long.toHexString(ep)+" .. 0x"+Long.toHexString(end)+" (len "+(end-ep)+")");
  for(long a=ep;a<ep+0x30;){var i=lst.getInstructionAt(sp.getAddress(a));
    if(i!=null){println(String.format("%08x  %s",a,i.toString()));a+=i.getLength();}else a+=2;}
}}
