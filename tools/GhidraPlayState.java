import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
public class GhidraPlayState extends GhidraScript {
  public void run() throws Exception {
    Listing lst = currentProgram.getListing();
    InstructionIterator it = lst.getInstructions(true);
    // the "voice is playing" states set by the trig, in both abs and signed-disp forms
    String[] tags = {"8000188e","7fffe772",  // voice cmd flags (bit8=play)
                     "8000186e","7fffe792",  // timing from table
                     "80000110","7ffffef0",  // DSP voice sample assign
                     "400d8120"};            // the timing table
    while (it.hasNext()){
      Instruction ins = it.next();
      String s = ins.toString();
      for (String t: tags){ if (s.contains(t)){
        Function f=getFunctionContaining(ins.getAddress());
        String m=ins.getMnemonicString();
        boolean w = (m.startsWith("move")||m.startsWith("clr")) && (s.matches(".*,\\(0x"+t+"\\).*")||s.contains(",(0x"+t)||s.matches(".*,\\(-0x"+t.replace("7fff","7fff")+"\\).*")||s.contains("("+t)||s.endsWith(t+").l"));
        println(String.format("%08x  %-42s [%s]", ins.getAddress().getOffset(), s, f==null?"?":f.getName()));
        break; }}
    }
  }
}
