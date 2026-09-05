import ghidra.app.script.GhidraScript; import ghidra.program.model.address.*; import ghidra.program.model.listing.*;
public class GhidraMuteTgt extends GhidraScript { public void run() throws Exception {
  var sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); var lst=currentProgram.getListing();
  for(long[] r: new long[][]{{0x40008104L,0x40008130L},{0x40008120L,0x40008150L}}){
    println("== 0x"+Long.toHexString(r[0])+" ==");
    for(long a=r[0];a<r[1];){var i=lst.getInstructionAt(sp.getAddress(a));
      if(i!=null){println(String.format("%08x  %s",a,i.toString()));a+=i.getLength();}else{a+=2;}}}
}}
