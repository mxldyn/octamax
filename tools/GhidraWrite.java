import ghidra.app.script.GhidraScript; import ghidra.program.model.address.*; import ghidra.program.model.listing.*;
public class GhidraWrite extends GhidraScript { public void run() throws Exception {
  var sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); var lst=currentProgram.getListing();
  for(long ep: new long[]{0x400166b8L,0x40081b30L}){
    println("\n== 0x"+Long.toHexString(ep)+" ==");
    for(long a=ep;a<ep+0x50;){var i=lst.getInstructionAt(sp.getAddress(a));
      if(i!=null){println(String.format("%08x  %s",a,i.toString()));a+=i.getLength();}else{a+=2;}}}
}}
