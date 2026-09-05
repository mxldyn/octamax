import ghidra.app.script.GhidraScript; import ghidra.app.decompiler.*;
import ghidra.program.model.address.*; import ghidra.program.model.listing.*;
import ghidra.util.task.ConsoleTaskMonitor;
public class GhidraF96a5c extends GhidraScript { public void run() throws Exception {
  var sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); var fm=currentProgram.getFunctionManager();
  var f=fm.getFunctionContaining(sp.getAddress(0x40096a5cL));
  long ep=f.getEntryPoint().getOffset(), end=f.getBody().getMaxAddress().getOffset();
  println("FUN_40096a5c 0x"+Long.toHexString(ep)+" .. 0x"+Long.toHexString(end)+" (len "+(end-ep)+")");
  var dec=new DecompInterface(); dec.openProgram(currentProgram);
  var res=dec.decompileFunction(f,90,new ConsoleTaskMonitor());
  if(res!=null && res.decompileCompleted()) println(res.getDecompiledFunction().getC());
  else {
    var lst=currentProgram.getListing();
    for(long a=ep;a<=end && a<ep+0x120;){var i=lst.getInstructionAt(sp.getAddress(a));
      if(i!=null){println(String.format("%08x  %s",a,i.toString()));a+=i.getLength();}else a+=2;}
  }
}}
