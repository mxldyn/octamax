import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
public class GhidraGate extends GhidraScript {
  public void run() throws Exception {
    Listing lst = currentProgram.getListing();
    InstructionIterator it = lst.getInstructions(true);
    String[] tags = {"80001860","46104ca8","80000028"};
    for (String t: tags) println("watching "+t);
    while (it.hasNext()){
      Instruction ins = it.next();
      String s = ins.toString();
      String m = ins.getMnemonicString();
      boolean isW = m.startsWith("move")||m.startsWith("clr")||m.startsWith("st")||m.startsWith("bset")||m.startsWith("bclr")||m.startsWith("or")||m.startsWith("and");
      for (String t: tags){
        if (s.contains(t)){
          Function f=getFunctionContaining(ins.getAddress());
          // is it a WRITE to that addr? (dest operand contains the tag)
          boolean writes = s.matches(".*,\\(?0x"+t+"\\)?.*") || s.contains(","+"(0x"+t+")") || s.endsWith("(0x"+t+").l");
          println(String.format("%08x  %-40s [%s]%s", ins.getAddress().getOffset(), s, f==null?"?":f.getName(), writes?"  <WRITE>":""));
        }
      }
    }
  }
}
