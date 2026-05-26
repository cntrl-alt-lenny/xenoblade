# 042 — scaffolder/anmclr-sdata-uncarve

**Goal:** Drop `g3d_anmclr.cpp`'s `.sdata` range from `config/us/splits.txt` and absorb the orphan `lbl_eu_80663458` back into `nw4r_dataa.s`, so a future `g3d_anmclr.cpp` flip stops failing at the link stage with `undefined: 'lbl_eu_80663458'`.

## Context

Brief 039 carved 4 per-TU data ranges out of `nw4r_data.s` for `g3d_anmclr.cpp`:

  - `.rodata 0x8051D530 - 0x8051D560` (48 bytes) ← keep
  - `.data 0x80569180 - 0x80569210` (144 bytes) ← keep
  - `.sdata 0x80663458 - 0x80663460` (8 bytes) ← **drop this**
  - `.sdata2 0x80669B48 - 0x80669B58` (16 bytes) ← keep

Brief 041's flip attempt revealed the `.sdata` range is wrong: the only symbol in it (`lbl_eu_80663458`, size 0x8) isn't owned by any class that survived `g3d_anmclr.cpp`'s dead-code trim. The neighbour at `0x80663460` (`smBaseUpdateRate__Q34nw4r3g3d9FrameCtrl`) is a `FrameCtrl` static, suggesting the orphan also belongs to `FrameCtrl` or a sibling — not to `g3d_anmclr.cpp`.

Brain confirmed the decomper-side dead-code trim (brief 036) is correct; the splits.txt-side over-claim is the bug.

Four downstream TUs (`g3d_anmscn.o`, `g3d_anmtexpat.o`, `g3d_anmtexsrt.o`, `g3d_anmchr.o`) reference `lbl_eu_80663458` as an extern; removing it from `nw4r_datab.s` broke their link. Putting it back in `nw4r_dataa.s` restores the extern symbol.

## Scope

- `config/us/splits.txt` only.
- Two edits:
  1. Remove the `.sdata 0x80663458 - 0x80663460` line from `nw4r/src/g3d/g3d_anmclr.cpp`'s block.
  2. Extend `nw4r_dataa.s`'s `.sdata` line to `start:0x80663450 end:0x80663460` (was `0x80663450 - 0x80663458`).
- The other 3 carves (`.rodata`, `.data`, `.sdata2`) stay — only `.sdata` was wrong.

## Non-scope

- Don't touch `config/jp/` or `config/eu/` (no baseroms for those regions yet).
- Don't touch `src/`, `libs/`, `include/`.
- Don't try to rename `lbl_eu_80663458` to its true owner — that's a decomper concern for later, when whichever TU actually owns it gets matched.
- Don't touch the `nw4r_datab.s` `.sdata` range start (`0x80663460`) — that's correct; it's where `FrameCtrl`'s statics begin.

## Success

- Build (`python configure.py --version us && ninja`) is clean.
- `build/us/main.dol` SHA-1 stays `214b15173fa3bad23a067476d58d3933ad7037b7`.
- The 4 external references to `lbl_eu_80663458` (from `g3d_anmscn.o` etc.) resolve again — verifiable by re-running brief 041's flip attempt and confirming compile-stage links work cleanly when `g3d_anmclr.cpp` is set to Matching. (Don't actually do the flip in this brief — that's brief 043's job.)
- No new warnings.

## Test plan

- [ ] Apply the splits.txt edit
- [ ] `python configure.py --version us && ninja`
- [ ] Verify SHA-1: `shasum -a 1 build/us/main.dol` matches the baseline
- [ ] Sanity-check the diff is exactly 2 lines changed (one removed from g3d_anmclr block, one end-address updated in nw4r_dataa.s block)

## Branch

`scaffolder/anmclr-sdata-uncarve`
