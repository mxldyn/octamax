import ghidra.app.script.GhidraScript; import ghidra.program.model.address.*; import ghidra.program.model.listing.*;
public class GhidraF4008 extends GhidraScript { public void run() throws Exception {
  var sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); var lst=currentProgram.getListing();
  // FUN_40007960 args: pushed by caller before jsr @0x400041c4. Dump FUN_40004008 around the call.
  println("== FUN_40004008 around the call to FUN_40007960 @0x400041c4 ==");
  for(long a=0x40004190L;a<0x400041d0L;){var i=lst.getInstructionAt(sp.getAddress(a));
    if(i!=null){println(String.format("%08x  %s",a,i.toString()));a+=i.getLength();}else a+=2;}
  println("\n== FUN_40004008 head (to see arg sources) ==");
  var f=getFunctionContaining(sp.getAddress(0x40004008L));
  long ep=f.getEntryPoint().getOffset();
  for(long a=ep;a<ep+0x40;){var i=lst.getInstructionAt(sp.getAddress(a));
    if(i!=null){println(String.format("%08x  %s",a,i.toString()));a+=i.getLength();}else a+=2;}
}}
