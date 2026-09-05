import ghidra.app.script.GhidraScript; import ghidra.program.model.address.*; import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
public class GhidraMute2Br extends GhidraScript { public void run() throws Exception {
  var sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); var lst=currentProgram.getListing();
  var rm=currentProgram.getReferenceManager();
  println("== all branches to MUTE2 0x4000812c ==");
  for(Reference r: rm.getReferencesTo(sp.getAddress(0x4000812cL))){
    var i=lst.getInstructionAt(r.getFromAddress());
    println("  from 0x"+Long.toHexString(r.getFromAddress().getOffset())+"  "+(i!=null?i.toString():"?"));
  }
  // dump the region just after the play-continue (0x40007f02) to find where PLAY commits/returns
  println("\n== play path tail 0x40007f02.. ==");
  for(long a=0x40007f02L;a<0x40007f80L;){var i=lst.getInstructionAt(sp.getAddress(a));
    if(i!=null){String s=i.toString(); println(String.format("%08x  %-36s%s",a,s,(s.contains("812c")||s.contains("unlk")||s.contains("rts"))?"  <<":"")); a+=i.getLength();}else a+=2;}
}}
