import ghidra.app.script.GhidraScript; import ghidra.program.model.address.*; import ghidra.program.model.listing.*;
public class GhidraFbEntry extends GhidraScript { public void run() throws Exception {
  var sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); var lst=currentProgram.getListing();
  for(long a=0x4000c8a4L;a<0x4000c8c2L;){var i=lst.getInstructionAt(sp.getAddress(a)); if(i==null){a+=2;continue;}
    println(String.format("%08x  %s",a,i.toString())); a+=i.getLength();} }}
