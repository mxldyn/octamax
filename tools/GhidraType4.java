import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
public class GhidraType4 extends GhidraScript {
  AddressSpace sp; Listing lst;
  void dump(long a0,long n,String tag){ println(String.format("\n== %s 0x%08x ==",tag,a0));
    for(long a=a0;a<a0+n;){Instruction i=lst.getInstructionAt(sp.getAddress(a));
      if(i!=null){println(String.format("%08x  %s",a,i.toString()));a+=i.getLength();}else{println(String.format("%08x [d]",a));a+=2;}}}
  public void run() throws Exception {
    sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); lst=currentProgram.getListing();
    // FUN_400972fc: bridges flex-assign to FUN_40005214; shows how type-4 is detected per track
    dump(0x400972fc,0x100,"FUN_400972fc (type4 setup bridge)");
    // where is the per-voice machine-type byte read as ==4? we saw voice+0x14 in FUN_4000672c,
    // and pattern machine-type in FUN_40005214. Dump FUN_4000672c head to see voice+0x14 use.
    dump(0x40006734,0x30,"FUN_4000672c head (voice+0x14 type check)");
  }
}
