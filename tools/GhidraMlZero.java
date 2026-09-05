import ghidra.app.script.GhidraScript; import ghidra.program.model.address.*; import ghidra.program.model.listing.*;
public class GhidraMlZero extends GhidraScript {
  public void run() throws Exception {
    var sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); var lst=currentProgram.getListing();
    // Find writes to metadata +0x10 (length). Look for clr.l (0x10,An) or move ...,(0x10,An)
    // in functions that set An from the recorder-metadata base region.
    var it=lst.getInstructions(true);
    while(it.hasNext()){
      var i=it.next(); String s=i.toString(); String m=i.getMnemonicString();
      boolean w = (m.startsWith("clr")||m.startsWith("move")) && (s.endsWith(",(0x10,A2)")||s.endsWith(",(0x10,A3)")||s.endsWith(",(0x10,A0)")||s.endsWith(",(0x10,A1)")||s.equals("clr.l (0x10,A2)")||s.contains("(0x10,A")&&(s.startsWith("clr")||s.contains(",(0x10,A")));
      if(!w) continue;
      // only clr or zero-ish moves
      if(!(m.startsWith("clr")||s.contains("#0x0,")||s.contains("D")&&s.contains(",(0x10,A"))) continue;
      var f=getFunctionContaining(i.getAddress());
      String fn=f==null?"?":f.getName();
      // restrict to recorder-relevant functions (0x4009xxxx cluster or those touching metadata)
      println(String.format("%08x  %-30s [%s]", i.getAddress().getOffset(), s, fn));
    }
  }
}
