//@category Octatrack
// Listing dump (ColdFire hot-path safe) for several ranges: audio-stop (mask),
// kill-1-voice, and the load-path voice-stop call sites.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
public class GhidraDisN extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    Listing lst = currentProgram.getListing();
    long[][] ranges = {
      {0x40006820L, 0x90L,  0x1},   // audio_stop(mask)
      {0x40008f84L, 0xa0L,  0x2},   // kill 1 voice
      {0x40096a80L, 0xb0L,  0x3},   // flex reload wrapper region (caller of stop)
      {0x40097820L, 0x60L,  0x4},   // flex_unload voicekill site 0x40097856
      {0x40006890L, 0x60L,  0x5},   // f6890
    };
    for (long[] r : ranges) {
      long start=r[0], end=r[0]+r[1];
      println(String.format("\n==== range #%d  0x%08x .. 0x%08x ====", r[2], start, end));
      for (long a=start; a<end; ) {
        Address ad = sp.getAddress(a);
        Instruction ins = lst.getInstructionAt(ad);
        if (ins != null) {
          println(String.format("%08x  %s", a, ins.toString()));
          a += ins.getLength();
        } else {
          Data dat = lst.getDataAt(ad);
          println(String.format("%08x  [no-instr]", a));
          a += (dat!=null && dat.getLength()>0 ? dat.getLength() : 2);
        }
      }
    }
    println("\n[GhidraDisN] fin.");
  }
}
