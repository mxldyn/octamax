//@category Octatrack
// AUTO PTN 1: decompile the BANK-select state machine and everything the synthetic
// "press+release trig 1" path touches, list callers and global refs.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;
public class GhidraAutoPtn extends GhidraScript {
  DecompInterface d; ConsoleTaskMonitor mon; FunctionManager fm; AddressSpace sp;
  void dump(long a,String tag) throws Exception {
    var f=fm.getFunctionAt(sp.getAddress(a));
    if(f==null) f=fm.getFunctionContaining(sp.getAddress(a));
    if(f==null){ try{ disassemble(sp.getAddress(a)); f=createFunction(sp.getAddress(a),null);}catch(Exception e){} }
    if(f==null){println("\n#### NO FUNCTION 0x"+Long.toHexString(a)+" ("+tag+") ####");return;}
    var r=d.decompileFunction(f,300,mon);
    println("\n#### "+f.getName()+" @"+f.getEntryPoint()+" size="+f.getBody().getNumAddresses()+" ("+tag+") ####");
    println(r!=null&&r.decompileCompleted()?r.getDecompiledFunction().getC():"(no-C)");
  }
  void callers(long a) {
    println("\n=== refs to 0x"+Long.toHexString(a)+" ===");
    var ri=currentProgram.getReferenceManager().getReferencesTo(sp.getAddress(a));
    var lst=currentProgram.getListing();
    while(ri.hasNext()){
      var r=ri.next();
      var f=fm.getFunctionContaining(r.getFromAddress());
      var ins=lst.getInstructionAt(r.getFromAddress());
      println("  "+r.getReferenceType()+"  from "+r.getFromAddress()+" in "+(f!=null?f.getName():"?")+"  ["+(ins!=null?ins.toString():"data")+"]");
    }
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
    sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
    fm=currentProgram.getFunctionManager();
    d=new DecompInterface(); d.openProgram(currentProgram);
    mon=new ConsoleTaskMonitor();
    long[][] fns={{0x4007af30L},{0x4007af80L},{0x4007b25cL},{0x4007b26cL},{0x4007b2fcL},{0x4007b3e0L},{0x4007b408L},{0x4007b434L},
                  {0x40056b00L},{0x40056a70L},{0x40031200L},{0x40031494L},{0x4003146cL},{0x4007e760L},{0x4007e81cL},{0x4007e998L},
                  {0x400a1030L},{0x4009c634L},{0x4009a404L},{0x40068fa8L},{0x40068fd0L},{0x40068e00L},{0x4005a2b8L}};
    for(long[] a:fns) dump(a[0],"");
    for(long a:new long[]{0x4007af30L,0x4007af80L,0x4007b25cL,0x4007b26cL,0x4007b2fcL,0x4007b3e0L,0x4007b408L,0x4007b434L,0x40056b00L}) callers(a);
    for(long a:new long[]{0x460e73b8L,0x460e73bcL,0x460e73c0L,0x460e73c2L,0x460e73c6L}) callers(a);
    refsRange(0x800000a8L,0x800000abL);
    refsRange(0x100fff38L,0x100fff3bL);
    // the two tables registered by the bank-select mode
    println("\n=== data @0x400cff14 / 0x400cff28 ===");
    var mem=currentProgram.getMemory();
    for(long a=0x400cff14L;a<0x400cff40L;a+=4) println("  0x"+Long.toHexString(a)+": 0x"+Long.toHexString(mem.getInt(sp.getAddress(a))&0xffffffffL));
    println("\n=== strings ===");
    for(long a:new long[]{0x400b7302L,0x400b730eL,0x400b7322L}){ StringBuilder s=new StringBuilder(); for(int i=0;i<40;i++){ int c=mem.getByte(sp.getAddress(a+i))&0xff; if(c==0)break; s.append((char)c);} println("  0x"+Long.toHexString(a)+": \""+s+"\""); }
    println("\n[END]");
  }
}
