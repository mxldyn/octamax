import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
public class GhidraRecMeta extends GhidraScript {
  public void run() throws Exception {
    var sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); var lst=currentProgram.getListing();
    // recorder metadata base 0x46c922c4 (state structs, stride 0x2c). Find functions that
    // reference this base (compute meta struct addresses) — the zeroer of +0x10 (length) lives there.
    var it=lst.getInstructions(true);
    java.util.LinkedHashMap<String,Integer> fns=new java.util.LinkedHashMap<>();
    while(it.hasNext()){
      var i=it.next(); String s=i.toString();
      if(s.contains("46c922c4")||s.contains("46c938c4")||s.contains("46c939cc")){
        var f=getFunctionContaining(i.getAddress()); String fn=f==null?"?":f.getName();
        fns.merge(fn,1,Integer::sum);
        println(String.format("%08x  %-40s [%s]", i.getAddress().getOffset(), s, fn));
      }
    }
    println("\n== fns referencing recorder-metadata base ==");
    for(var e: fns.entrySet()) println("  "+e.getKey()+" x"+e.getValue());
  }
}
