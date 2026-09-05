import ghidra.app.script.GhidraScript; import ghidra.app.decompiler.*;
import ghidra.program.model.address.*; import ghidra.program.model.listing.*;
import ghidra.util.task.ConsoleTaskMonitor;
public class GhidraLog2 extends GhidraScript { public void run() throws Exception {
  var sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); var lst=currentProgram.getListing();
  var fm=currentProgram.getFunctionManager();
  var dec=new DecompInterface(); dec.openProgram(currentProgram); var mon=new ConsoleTaskMonitor();
  var f=fm.getFunctionContaining(sp.getAddress(0x4001ff2cL));
  long ep=f.getEntryPoint().getOffset(), end=f.getBody().getMaxAddress().getOffset();
  println("=== FUN_4001ff2c (log writer) 0x"+Long.toHexString(ep)+" .. 0x"+Long.toHexString(end)+" ===");
  var res=dec.decompileFunction(f,60,mon);
  if(res!=null && res.decompileCompleted()) println(res.getDecompiledFunction().getC());
  else println("(decompile failed, listing:)");
  for(long a=ep;a<=end;){var i=lst.getInstructionAt(sp.getAddress(a));
    if(i!=null){println(String.format("%08x  %s",a,i.toString()));a+=i.getLength();}else{a+=2;}}
}}
