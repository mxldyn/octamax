//@category Octatrack
// AUTO PTN 1 (2): which words of the ANDY block / PERSONALIZE runtime block are referenced,
// and the key dispatcher that walks the 0x460d165c handler list.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;
public class GhidraAutoPtn2 extends GhidraScript {
  DecompInterface d; ConsoleTaskMonitor mon; FunctionManager fm; AddressSpace sp;
  void dump(long a,String tag) throws Exception {
    var f=fm.getFunctionAt(sp.getAddress(a)); if(f==null) f=fm.getFunctionContaining(sp.getAddress(a));
    if(f==null){println("\n#### NO FUNCTION 0x"+Long.toHexString(a)+" ("+tag+") ####");return;}
    var r=d.decompileFunction(f,300,mon);
    println("\n#### "+f.getName()+" @"+f.getEntryPoint()+" size="+f.getBody().getNumAddresses()+" ("+tag+") ####");
    println(r!=null&&r.decompileCompleted()?r.getDecompiledFunction().getC():"(no-C)");
  }
  void refsRange(long lo,long hi){
    println("\n=== refs into [0x"+Long.toHexString(lo)+",0x"+Long.toHexString(hi)+"] ===");
    var lst=currentProgram.getListing();
    for(long a=lo;a<=hi;a++){
      var ri=currentProgram.getReferenceManager().getReferencesTo(sp.getAddress(a));
      while(ri.hasNext()){ var r=ri.next(); var f=fm.getFunctionContaining(r.getFromAddress());
        var ins=lst.getInstructionAt(r.getFromAddress());
        println("  0x"+Long.toHexString(a)+" <- "+r.getReferenceType()+" "+r.getFromAddress()+" in "+(f!=null?f.getName():"?")+" ["+(ins!=null?ins.toString():"data")+"]"); }
    }
    println("  (end)");
  }
  public void run() throws Exception {
    sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); fm=currentProgram.getFunctionManager();
    d=new DecompInterface(); d.openProgram(currentProgram); mon=new ConsoleTaskMonitor();
    refsRange(0x100fff00L,0x100fffffL);
    refsRange(0x80000070L,0x800000dfL);
    println("\n=== refs to 0x460d165c (handler list head) ===");
    var ri=currentProgram.getReferenceManager().getReferencesTo(sp.getAddress(0x460d165cL));
    Set<Long> fns=new LinkedHashSet<>();
    while(ri.hasNext()){ var r=ri.next(); var f=fm.getFunctionContaining(r.getFromAddress());
      println("  "+r.getReferenceType()+" "+r.getFromAddress()+" in "+(f!=null?f.getName():"?")); if(f!=null) fns.add(f.getEntryPoint().getOffset()); }
    for(long a:fns) dump(a,"list user");
    dump(0x4003125cL,"rebuild");
    dump(0x400a0570L,"pattern change request");
    println("\n[END]");
  }
}
