import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
public class GhidraV18 extends GhidraScript {
  public void run() throws Exception {
    var sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); var lst=currentProgram.getListing();
    // scan whole image for writes to (0x18,An) or (0x1a,An) or (0x1b,An) — candidate voice+0x18 field writers.
    // Heuristic: any instruction whose operand text has ",(0x18," / ",(0x1a," / ",(0x1b," (dest = displaced An).
    var it=lst.getInstructions(true);
    int n=0;
    while(it.hasNext() && n<80){
      var i=it.next(); String s=i.toString(); String m=i.getMnemonicString();
      if(!(m.startsWith("move")||m.startsWith("clr")||m.startsWith("st")||m.startsWith("bset")||m.startsWith("bclr"))) continue;
      // destination displaced 0x18/0x1a/0x1b (voice-struct field) — only when it's the DEST (ends with the ea)
      if(s.matches(".*,\\((0x18|0x1a|0x1b),A[0-9]\\)$") || s.matches(".*,\\((0x18|0x1a|0x1b),A[0-9],D[0-9].*\\)$")){
        var f=getFunctionContaining(i.getAddress());
        println(String.format("%08x  %-38s [%s]", i.getAddress().getOffset(), s, f==null?"?":f.getName()));
        n++;
      }
    }
    println("total "+n);
  }
}
