import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
public class GhidraLoadCalls extends GhidraScript {
  AddressSpace sp; Listing lst; FunctionManager fm;
  void dumpCalls(long ep){
    Function f = fm.getFunctionContaining(sp.getAddress(ep));
    if (f==null){ println("no fn @ "+Long.toHexString(ep)); return; }
    long a=f.getEntryPoint().getOffset(), end=f.getBody().getMaxAddress().getOffset();
    println("\n===== "+f.getName()+" 0x"+Long.toHexString(a)+" .. 0x"+Long.toHexString(end)+" — CALLS =====");
    for (; a<=end; ){
      Instruction ins = lst.getInstructionAt(sp.getAddress(a));
      if (ins==null){ a+=2; continue; }
      String m = ins.getMnemonicString();
      if (m.startsWith("jsr")||m.startsWith("bsr")||m.startsWith("jmp")){
        // resolve target function name if any
        String tgt="";
        Reference[] rs = ins.getReferencesFrom();
        for (Reference r: rs){ if (r.getReferenceType().isCall()||r.getReferenceType().isJump()){
          Function tf = fm.getFunctionAt(r.getToAddress());
          tgt = r.getToAddress()+(tf!=null?" "+tf.getName():"");
        }}
        println(String.format("%08x  %-26s -> %s", a, ins.toString(), tgt));
      }
      a+=ins.getLength();
    }
  }
  public void run() throws Exception {
    sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    lst = currentProgram.getListing();
    fm = currentProgram.getFunctionManager();
    dumpCalls(0x4008445cL);   // load orchestrator (calls FUN_400905d4)
    dumpCalls(0x400905d4L);   // flex/bank load (calls apply_part)
    println("\n[GhidraLoadCalls] fin.");
  }
}
