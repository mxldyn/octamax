import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
public class GhidraReset extends GhidraScript {
  AddressSpace sp; Listing lst; ReferenceManager rm;
  void dump(long a0,long n,String tag){ println(String.format("\n== %s 0x%08x ==",tag,a0));
    for(long a=a0;a<a0+n;){Instruction i=lst.getInstructionAt(sp.getAddress(a));
      if(i!=null){println(String.format("%08x  %s",a,i.toString()));a+=i.getLength();}else{println(String.format("%08x [d]",a));a+=2;}}}
  void callersRec(long t,int depth,String ind,java.util.Set<Long> seen){
    if(depth>5) return;
    Function tf=getFunctionContaining(sp.getAddress(t)); if(tf==null){println(ind+"0x"+Long.toHexString(t)+" (no fn)");return;}
    long ep=tf.getEntryPoint().getOffset();
    if(seen.contains(ep)){println(ind+tf.getName()+" (seen)");return;} seen.add(ep);
    int n=0;
    for(Reference r: rm.getReferencesTo(sp.getAddress(ep))){ if(!r.getReferenceType().isCall())continue;
      Function f=getFunctionContaining(r.getFromAddress()); String fn=f==null?"?":f.getName();
      boolean load = fn.contains("4008445c")|| (f!=null && f.getEntryPoint().getOffset()==0x4008445cL);
      println(ind+tf.getName()+" <- "+fn+" @"+r.getFromAddress()+(load?"   *** LOAD ORCHESTRATOR ***":""));
      n++; if(f!=null && n<=4) callersRec(f.getEntryPoint().getOffset(),depth+1,ind+"  ",seen);
    }
    if(n==0) println(ind+tf.getName()+" <- (root/vectored)");
  }
  public void run() throws Exception {
    sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); lst=currentProgram.getListing(); rm=currentProgram.getReferenceManager();
    dump(0x400068e4,0x120,"FUN_400068e4 (reset-voices?)");
    println("\n### is FUN_400068e4 reachable from the load? ###");
    callersRec(0x400068e4L,0,"  ",new java.util.HashSet<>());
  }
}
