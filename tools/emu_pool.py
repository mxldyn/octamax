#!/usr/bin/env python3
"""
Flex paged-allocator emulator — faithful model of the Octatrack flex RAM pool,
to design and VALIDATE a recorder-preserving reinit before touching hardware.

Modeled from the decompiled primitives:
  FUN_40096f24  full pool reinit (cursor=0, boundary=0x390a, zero all, re-reserve recs)
  FUN_400948cc  recorder reserve  (take pages from the top: boundary--)
  FUN_40095a90  recorder reclaim  (return pages to the top: boundary++), zeroes them
  FUN_40096548  flex slot alloc   (bump from the bottom: cursor += need)

Pool geometry:
  NPAGES = 0x390a pages, page = 0x1800 bytes, base 0x40a955e0 (total 0x5590800 ~89MB).

Page table 0x46c2e9c0 is a set of bands of NPAGES shorts each:
  band 0            = the FREE LIST: freelist[i] = physical page number (or 0 = taken)
  band (rec+2)      = recorder rec's page list: [k] = physical page assigned to slot k
Flex slots keep an OFFSET into band 0: slot pages = freelist[off .. off+size).
Recorders MOVE pages out of band 0 into their band.

Invariant we must preserve: every physical page (1..NPAGES) is owned by AT MOST one
of {a flex slot, a recorder, the free pool}. A recorder-preserving reinit must not let
flex or another recorder take a preserved recorder's physical page, and must not zero it.
"""

NPAGES = 0x390a
PAGE = 0x1800
POOLBASE = 0x40a955e0
SR = 0xac44  # 44100


class Pool:
    def __init__(self):
        # band 0 free list; recorder bands 2..9 (index (rec+2))
        self.freelist = [0] * NPAGES          # freelist[i] = physical page, 0=empty
        self.recband = {r: [0] * NPAGES for r in range(8)}
        self.cursor = 0                        # _DAT_8000691c (flex, from bottom)
        self.boundary = NPAGES                 # _DAT_80006920 (recorders, from top)
        self.rec_size = {r: 0 for r in range(8)}   # DAT_46c75e88[rec+0x80]
        self.rec_reserved = {r: 0 for r in range(8)}  # 0x461053a8[rec]
        self.flex_off = {}                     # slot -> offset into freelist
        self.flex_size = {}                    # slot -> size (pages)
        # physical page contents: page -> a tag (what wrote it). None = zeroed.
        self.content = {p: None for p in range(1, NPAGES + 1)}

    # --- FUN_40020984: zero a physical page ---
    def zero_page(self, page):
        if page:
            self.content[page] = None

    # --- FUN_400948cc(rec): reserve rec_reserved[rec] pages from the TOP ---
    def rec_reserve(self, rec):
        band = self.recband[rec]
        k = 0
        while True:
            if k < self.rec_reserved[rec]:
                if band[k] != 0:
                    return  # already has a page here -> stop (idempotent)
                if self.boundary != self.cursor and self.boundary - self.cursor >= 0 and self.boundary > 0:
                    self.boundary -= 1
                    page = self.freelist[self.boundary]
                    self.freelist[self.boundary] = 0
                    band[k] = page
                    self.rec_size[rec] += 1
                else:
                    raise MemoryError(f"rec {rec} OOM at k={k}")
                k += 1
            else:
                return

    # --- FUN_40095a90(rec): reclaim rec's pages back to the free list (zeroes them) ---
    def rec_reclaim(self, rec):
        band = self.recband[rec]
        # loops k from rec_reserved down/over; faithfully: over 0..0x3909 but only its band entries matter
        k = 0
        while k <= self.rec_reserved[rec] and k < NPAGES:
            page = band[k]
            band[k] = 0
            if page != 0:
                self.rec_size[rec] -= 1
                self.zero_page(page)
                self.freelist[self.boundary] = page
                self.boundary += 1
            k += 1

    # --- flex slot alloc (bump from bottom); returns False on OOM ---
    def flex_alloc(self, slot, need, tag):
        if self.flex_size.get(slot):
            return True  # already allocated
        if self.boundary - self.cursor < need:
            return False  # OOM
        self.flex_off[slot] = self.cursor
        for i in range(need):
            page = self.freelist[self.cursor + i]
            self.content[page] = tag  # flex writes its sample into these pages
        self.cursor += need
        self.flex_size[slot] = need
        return True

    def flex_unload_all(self):
        self.flex_off.clear()
        self.flex_size.clear()

    # --- FUN_40096f24: STOCK full reinit ---
    def reinit_stock(self, reserved_per_rec):
        self.flex_unload_all()
        for r in range(8):
            self.recband[r] = [0] * NPAGES
            self.rec_size[r] = 0
        self.cursor = 0
        self.boundary = NPAGES
        for i in range(NPAGES):
            self.freelist[i] = i + 1        # pages 1..NPAGES all free
        for p in range(1, NPAGES + 1):
            self.content[p] = None          # zero whole pool
        for r in range(8):
            self.rec_reserved[r] = reserved_per_rec[r]
            self.rec_reserve(r)

    # --- recorder-preserving reinit (proposed, when g_hot) ---
    # Keep the recorder region (top pages) intact; reset ONLY the flex region.
    def reinit_preserve(self, reserved_per_rec):
        # recorders already reserved from a prior load; their pages are the top ones.
        B = self.boundary                    # keep the current recorder boundary
        self.flex_unload_all()
        self.cursor = 0
        # rebuild the free list for the flex region [0..B): physical pages 1..B
        for i in range(B):
            self.freelist[i] = i + 1
        # zero ONLY the flex region pages (1..B); leave recorder pages (B+1..NPAGES) intact
        for p in range(1, B + 1):
            self.content[p] = None
        # DO NOT touch recorder bands, rec_size, or boundary.
        # (format assumed identical -> reserved_per_rec matches the held layout)

    # --- verification ---
    def owner_map(self):
        """physical page -> owner label; raise on double-ownership."""
        owner = {}
        def claim(page, who):
            if page == 0:
                return
            if page in owner:
                raise AssertionError(f"page {page} double-owned: {owner[page]} AND {who}")
            owner[page] = who
        for r in range(8):
            for k in range(self.rec_reserved[r]):
                claim(self.recband[r][k], f"rec{r}")
        for slot, off in self.flex_off.items():
            for i in range(self.flex_size[slot]):
                claim(self.freelist[off + i], f"flex{slot}")
        return owner

    def rec_pages(self, rec):
        return [self.recband[rec][k] for k in range(self.rec_reserved[rec]) if self.recband[rec][k]]


def fmt_reserved(count, length_s, is24):
    """FUN_40096f24 reserved-size formula, per recorder index."""
    res = []
    for r in range(8):
        if r < count:
            samples = (6 if is24 else 4) * length_s * SR
            pages = (samples + 0x17ff) // 0x1800
        else:
            pages = 0
        res.append(pages)
    return res


def scenario(count, length_s, is24, flex_loads, preserve_rec, label):
    print(f"\n===== {label}  (count={count} len={length_s}s 24bit={is24}) =====")
    reserved = fmt_reserved(count, length_s, is24)
    print(f"  reserved pages/rec: {reserved[:count]}  (total {sum(reserved)})")

    # --- project A: initial load ---
    p = Pool()
    p.reinit_stock(reserved)
    # record content into the preserved recorder (tag its pages)
    for k in range(p.rec_size[preserve_rec]):
        pg = p.recband[preserve_rec][k]
        p.content[pg] = f"REC{preserve_rec}_AUDIO"
    saved_pages = p.rec_pages(preserve_rec)
    saved_content = {pg: p.content[pg] for pg in saved_pages}
    # load project A's flex
    for slot, need in flex_loads:
        if not p.flex_alloc(slot, need, f"A_flex{slot}"):
            print(f"  [A] flex{slot} OOM"); return
    try:
        p.owner_map()
    except AssertionError as e:
        print(f"  [A] INVARIANT BROKEN: {e}"); return
    print(f"  [A] recorder {preserve_rec} holds pages {saved_pages[:6]}{'...' if len(saved_pages)>6 else ''} "
          f"(boundary={p.boundary}, cursor={p.cursor})")

    # --- project change with the PRESERVING reinit, then load project B's flex ---
    p.reinit_preserve(reserved)
    for slot, need in flex_loads:   # B may load different sizes; use same for the stress
        if not p.flex_alloc(slot, need, f"B_flex{slot}"):
            print(f"  [B] flex{slot} OOM"); return
    # re-reserve any NON-preserved recorders that a real load would (they were kept too here)

    # --- verify ---
    try:
        owner = p.owner_map()
    except AssertionError as e:
        print(f"  [B] INVARIANT BROKEN: {e}"); return
    now_pages = p.rec_pages(preserve_rec)
    pages_ok = (now_pages == saved_pages)
    content_ok = all(p.content.get(pg) == saved_content[pg] for pg in saved_pages)
    # ensure no flex slot got a preserved page
    flexpages = set()
    for slot, off in p.flex_off.items():
        for i in range(p.flex_size[slot]):
            flexpages.add(p.freelist[off + i])
    overlap = set(saved_pages) & flexpages
    print(f"  [B] recorder pages same:   {pages_ok}")
    print(f"  [B] recorder content kept: {content_ok}")
    print(f"  [B] flex/recorder overlap: {sorted(overlap) if overlap else 'NONE'}")
    ok = pages_ok and content_ok and not overlap
    print(f"  ==> {'PASS' if ok else 'FAIL'}")
    return ok


def stock_vs_preserve(count, length_s, is24, flex_loads, preserve_rec, label):
    """Show STOCK reinit LOSES the recorder content (reproduces the hw bug), and the
    PRESERVE reinit keeps it — same starting state."""
    print(f"\n----- STOCK vs PRESERVE: {label} -----")
    reserved = fmt_reserved(count, length_s, is24)
    for mode in ("stock", "preserve"):
        p = Pool()
        p.reinit_stock(reserved)
        for k in range(p.rec_size[preserve_rec]):
            p.content[p.recband[preserve_rec][k]] = f"REC{preserve_rec}_AUDIO"
        saved = {pg: p.content[pg] for pg in p.rec_pages(preserve_rec)}
        for slot, need in flex_loads:
            p.flex_alloc(slot, need, f"A{slot}")
        # project change
        if mode == "stock":
            p.reinit_stock(reserved)      # re-reserves recorders -> pages ZEROED
        else:
            p.reinit_preserve(reserved)
        for slot, need in flex_loads:
            p.flex_alloc(slot, need, f"B{slot}")
        kept = saved and all(p.content.get(pg) == v for pg, v in saved.items())
        print(f"    {mode:9s}: recorder {preserve_rec} content kept = {kept}"
              + ("" if saved else "  (recorder not reserved in this config)"))


if __name__ == "__main__":
    stock_vs_preserve(8, 8, False, [(0, 500), (5, 300)], 6,
                      "8 recs 8s, preserve R7")
    results = []
    # a few realistic + stress configs. flex_loads = list of (slot, pages).
    results.append(scenario(2, 16, False, [(0, 100), (1, 200), (2, 50)], 6,
                            "typical: 2 recs 16s, 3 flex, preserve R7"))
    results.append(scenario(8, 8, False, [(0, 500), (5, 300)], 6,
                            "8 recorders reserved, preserve R7"))
    results.append(scenario(1, 64, True, [(0, 1000), (1, 1000)], 0,
                            "1 rec 64s 24bit, big flex, preserve R1"))
    results.append(scenario(4, 30, False, [(i, 40) for i in range(16)], 3,
                            "4 recs, 16 flex slots, preserve R4"))
    print(f"\n===== {'ALL PASS' if all(results) else 'SOME FAILED'} ({sum(1 for r in results if r)}/{len(results)}) =====")
