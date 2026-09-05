import ghidra.program.model.address.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.scalar.Scalar;
// Find every function that references the voice-active base 0x800049d8 (== -0x7fffb628
// as a signed displacement) or the voice command region, to locate the "reset to static"
// bulk voice-clear that is NOT FUN_40006820.
public class GhidraVoiceWriters extends ghidra.app.script.GhidraScript {
  public void run() throws Exception {
    // scan all instructions for immediate/const 0x800049d8 or 0x7fffb628 (the lea form)
    Listing lst = currentProgram.getListing();
    InstructionIterator it = lst.getInstructions(true);
    java.util.LinkedHashMap<String,Integer> hitFns = new java.util.LinkedHashMap<>();
    long[] wanted = {0x800049d8L, 0x7fffb628L, 0x8000184aL, 0x8000184cL, 0x46c7dfbaL};
    while (it.hasNext()){
      Instruction ins = it.next();
      String s = ins.toString();
      boolean hit=false; long which=0;
      for (long w: wanted){ String h=Long.toHexString(w); if (s.contains(h)){ hit=true; which=w; break; } }
      if (!hit) continue;
      Function f = getFunctionContaining(ins.getAddress());
      String fn = f==null? "<none>" : f.getName();
      String key = fn;
      hitFns.merge(key, 1, Integer::sum);
      // print the actual line with the enclosing fn
      println(String.format("%08x  %-40s  [%s]  const=%x", ins.getAddress().getOffset(), s, fn, which));
    }
    println("\n=== functions referencing voice-active/cmd regions ===");
    for (var e: hitFns.entrySet()) println("  "+e.getKey()+"  x"+e.getValue());
    println("\n[GhidraVoiceWriters] fin.");
  }
}
