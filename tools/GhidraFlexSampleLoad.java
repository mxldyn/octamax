import ghidra.app.script.GhidraScript; import ghidra.program.model.address.*; import ghidra.program.model.symbol.*;
import ghidra.program.model.listing.*;
public class GhidraFlexSampleLoad extends GhidraScript {
  AddressSpace sp; ReferenceManager rm;
  void refs(long t,String tag){ println("\n-- refs to "+tag+" (0x"+Long.toHexString(t)+") --");
    for(Reference r: rm.getReferencesTo(sp.getAddress(t))){
      var f=getFunctionContaining(r.getFromAddress());
      println("   "+r.getReferenceType()+" @"+r.getFromAddress()+" in "+(f==null?"?":f.getName())); } }
  public void run() throws Exception {
    sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); rm=currentProgram.getReferenceManager();
    refs(0x400b8b1aL,"'Successfully loaded FLEX[%d]'");
    refs(0x400b790dL,"'Couldnt load FLEX[%d]'");
    refs(0x400b3a85L,"'%s/AUDIO/%s.wav'");
    refs(0x400b85e9L,"'TYPE=FLEX'");
  }
}
