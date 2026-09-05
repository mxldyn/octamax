import ghidra.app.script.GhidraScript; import ghidra.program.model.address.*; import ghidra.program.model.listing.*;
public class GhidraF96a5cL extends GhidraScript { public void run() throws Exception {
  var sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); var lst=currentProgram.getListing();
  for(long a=0x40096a5cL;a<0x40096a7cL;){var i=lst.getInstructionAt(sp.getAddress(a));
    if(i!=null){println(String.format("%08x  %s",a,i.toString()));a+=i.getLength();}else a+=2;}
  println("--- FUN_40096a5c calls FUN_40096300 in a loop? check what FUN_40096300 does to recorders ---");
  // also: does the flex-init loop unload slots 0..0x88 (incl recorders 0x80-0x87)?
}}
