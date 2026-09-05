import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
public class GhidraPlayPath extends GhidraScript {
  public void run() throws Exception {
    var sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); var lst=currentProgram.getListing();
    // FUN_40007960 body: find every branch to the mute/stop target 0x40008110 and the checks before it.
    // Dump 0x400079a2..0x40007b00 (the PLAY-decision region).
    for(long a=0x400079a2L;a<0x40007b00L;){var i=lst.getInstructionAt(sp.getAddress(a));
      if(i!=null){
        String s=i.toString();
        String mark = s.contains("40008110")?"   <<< MUTE/STOP":"";
        println(String.format("%08x  %-38s%s",a,s,mark)); a+=i.getLength();
      } else {a+=2;}}
    println("\n== mute target 0x40008110 ==");
    for(long a=0x40008110L;a<0x40008140L;){var i=lst.getInstructionAt(sp.getAddress(a));
      if(i!=null){println(String.format("%08x  %s",a,i.toString()));a+=i.getLength();}else{a+=2;}}
  }
}
