import ghidra.app.script.GhidraScript; import ghidra.app.decompiler.*;
import ghidra.program.model.address.*; import ghidra.program.model.listing.*;
import ghidra.util.task.ConsoleTaskMonitor;
public class GhidraFlexOrch extends GhidraScript { public void run() throws Exception {
  var sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); var fm=currentProgram.getFunctionManager();
  var lst=currentProgram.getListing();
  var f=fm.getFunctionContaining(sp.getAddress(0x4009083cL));
  long ep=f.getEntryPoint().getOffset(), end=f.getBody().getMaxAddress().getOffset();
  println("FUN_4009083c 0x"+Long.toHexString(ep)+" .. 0x"+Long.toHexString(end)+" (len "+(end-ep)+")");
  var dec=new DecompInterface(); dec.openProgram(currentProgram);
  var res=dec.decompileFunction(f,90,new ConsoleTaskMonitor());
  if(res!=null && res.decompileCompleted()){ String c=res.getDecompiledFunction().getC();
    // print first ~60 lines
    String[] L=c.split("\n"); for(int i=0;i<Math.min(L.length,70);i++) println(L[i]);
  } else {
    println("(decompile failed; calls of interest:)");
    long[] interest={0x40096f24L,0x40096548L,0x40016864L,0x40006820L,0x40096300L,0x4008ded0L,0x40025230L,0x40088288L};
    for(long a=ep;a<=end;){var i=lst.getInstructionAt(sp.getAddress(a)); if(i==null){a+=2;continue;}
      String s=i.toString(); for(long it:interest) if(s.contains(Long.toHexString(it))){println(String.format("%08x  %s",a,s));break;} a+=i.getLength();}
  }
}}
