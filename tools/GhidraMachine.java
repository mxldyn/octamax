import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
public class GhidraMachine extends GhidraScript {
  AddressSpace sp; Listing lst; FunctionManager fm;
  // things that would silence a voice, by address substring
  String[] STOP = {"40006820","40008f84","40008fe4","4000672c","800049d8","7fffb628","46c80354","40096ab0","40096300"};
  void scan(long ep){
    Function f = fm.getFunctionContaining(sp.getAddress(ep));
    if (f==null){ println("no fn @ "+Long.toHexString(ep)); return; }
    long a=f.getEntryPoint().getOffset(), end=f.getBody().getMaxAddress().getOffset();
    StringBuilder hits=new StringBuilder();
    for (; a<=end; ){
      Instruction ins = lst.getInstructionAt(sp.getAddress(a));
      if (ins==null){ a+=2; continue; }
      String s=ins.toString();
      for (String t: STOP){ if (s.contains(t)){ hits.append(String.format("    %08x  %s\n",a,s)); break; } }
      a+=ins.getLength();
    }
    println("== "+f.getName()+" 0x"+Long.toHexString(f.getEntryPoint().getOffset())+(hits.length()==0?"  (no stop/machine refs)":""));
    if (hits.length()>0) print(hits.toString());
  }
  public void run() throws Exception {
    sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    lst = currentProgram.getListing();
    fm = currentProgram.getFunctionManager();
    long[] cluster = {0x40095560L,0x40095774L,0x40095268L,0x40094b6cL,0x40095cd8L,
                      0x40094fa4L,0x40094dc8L,0x40094c94L,0x40095394L,
                      0x40095560L,0x40097554L,0x40095b70L,0x4009b5acL};
    println("### machine/recorder cluster — stop/machine refs ###");
    for (long ep: cluster) scan(ep);
    // who WRITES the machine-type array 0x46c80354 ?
    println("\n### writers/refs to machine-type array 0x46c80354 ###");
    ReferenceManager rm = currentProgram.getReferenceManager();
    for (Reference r: rm.getReferencesTo(sp.getAddress(0x46c80354L))){
      Function f=getFunctionContaining(r.getFromAddress());
      println("  "+r.getReferenceType()+" from "+r.getFromAddress()+" in "+(f==null?"<none>":f.getName()));
    }
    println("\n[GhidraMachine] fin.");
  }
}
