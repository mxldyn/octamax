import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.symbol.*;
public class GhidraV18c extends GhidraScript {
  AddressSpace sp; ReferenceManager rm;
  void callers(long t,String tag,int depth,String ind){
    if(depth>3)return;
    var f=getFunctionContaining(sp.getAddress(t)); if(f==null)return;
    long ep=f.getEntryPoint().getOffset();
    println(ind+tag+" 0x"+Long.toHexString(ep)+":");
    int n=0;
    for(Reference r: rm.getReferencesTo(sp.getAddress(ep))){ if(!r.getReferenceType().isCall())continue;
      var cf=getFunctionContaining(r.getFromAddress());
      String cn=cf==null?"?":cf.getName();
      boolean interesting = cn.contains("9094")|| (cf!=null && (cf.getEntryPoint().getOffset()==0x40009094L||cf.getEntryPoint().getOffset()==0x4000c8a4L||cf.getEntryPoint().getOffset()==0x4000c11aL||cf.getEntryPoint().getOffset()==0x4000a8fcL));
      println(ind+"   <- "+cn+" @"+r.getFromAddress()+(interesting?"  <<< FRAME/APPLY":""));
      n++; if(cf!=null && n<=3) callers(cf.getEntryPoint().getOffset(),cn,depth+1,ind+"    ");
    }
    if(n==0) println(ind+"   <- (root/vectored)");
  }
  public void run() throws Exception {
    sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); rm=currentProgram.getReferenceManager();
    callers(0x40004008L,"FUN_40004008",0,"");
  }
}
