import ghidra.app.script.GhidraScript; import ghidra.program.model.address.*; import ghidra.program.model.listing.*;
public class GhidraDeepMute extends GhidraScript { public void run() throws Exception {
  var sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); var lst=currentProgram.getListing();
  for(long a=0x40007ec0L;a<0x40007f10L;){var i=lst.getInstructionAt(sp.getAddress(a));
    if(i!=null){String s=i.toString(); println(String.format("%08x  %-38s%s",a,s,s.contains("812c")?"  <<MUTE2":"")); a+=i.getLength();}else{a+=2;}}
}}
