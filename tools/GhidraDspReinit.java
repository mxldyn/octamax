import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.listing.*;
public class GhidraDspReinit extends GhidraScript {
  AddressSpace sp; ReferenceManager rm;
  void up(long t,int depth,String ind){
    if(depth>4) return;
    Function tf=getFunctionContaining(sp.getAddress(t));
    String nm = tf==null?("0x"+Long.toHexString(t)):tf.getName();
    long ep = tf==null?t:tf.getEntryPoint().getOffset();
    int n=0;
    for(Reference r: rm.getReferencesTo(sp.getAddress(ep))){ if(!r.getReferenceType().isCall())continue;
      Function f=getFunctionContaining(r.getFromAddress());
      String fn=f==null?"?":f.getName();
      println(ind+nm+" <- "+fn+" @"+r.getFromAddress());
      n++;
      if(f!=null && n<=3) up(f.getEntryPoint().getOffset(),depth+1,ind+"  ");
    }
    if(n==0) println(ind+nm+" <- (no callers / root)");
  }
  public void run() throws Exception {
    sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); rm=currentProgram.getReferenceManager();
    println("=== call-up from DSP program uploader FUN_400e1292 ===");
    up(0x400e1292L,0,"  ");
    println("\n=== call-up from FUN_400e136c ===");
    up(0x400e136cL,0,"  ");
  }
}
