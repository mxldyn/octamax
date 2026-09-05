import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
public class GhidraFeed extends GhidraScript {
  AddressSpace sp; Listing lst;
  public void run() throws Exception {
    sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); lst=currentProgram.getListing();
    // frame builder FUN_4000c8a4 + per-frame compute FUN_4000c11a: find where they READ the
    // voice-play state (7fffe772=0x8000188e, 7ffffef0=0x80000110) and per-track feed decisions.
    long[] fns = {0x4000c8a4L, 0x4000c11aL};
    for (long ep: fns){
      var f=getFunctionContaining(sp.getAddress(ep));
      long end=f.getBody().getMaxAddress().getOffset();
      println(String.format("\n===== %s 0x%08x .. 0x%08x (len %d) =====", f.getName(), ep, end, end-ep));
      for(long a=ep;a<=end;){Instruction i=lst.getInstructionAt(sp.getAddress(a));
        if(i==null){a+=2;continue;}
        String s=i.toString();
        // print lines touching the play-state, voice-active, DSP frame buffer, or trig-pending
        if(s.contains("7fffe772")||s.contains("8000188e")||s.contains("7ffffef0")||s.contains("80000110")
           ||s.contains("7fffb628")||s.contains("800049d8")||s.contains("800000e0")||s.contains("80000a50")
           ||s.contains("8000184c")||s.contains("80001828")||s.contains("8000182a")||s.contains("400d8120")
           ||s.contains("7fffe792")||s.contains("8000186e"))
          println(String.format("%08x  %s", a, s));
        a+=i.getLength();}
    }
  }
}
