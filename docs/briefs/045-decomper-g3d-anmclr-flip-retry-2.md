# 045 — decomper/g3d-anmclr-flip-retry-2

**Goal:** Retry the `nw4r/src/g3d/g3d_anmclr.cpp` flip from `NonMatching` to `Matching` (US), now that brief 042 (PR #43) cleared the `.sdata 0x80663458` over-claim that caused brief 041 to bail.

## Context

The story so far:
- **Brief 039 (PR #39)**: carved 4 per-TU data ranges for `g3d_anmclr.cpp` to enable a flip. NW4R Data went 88.24% → 97.18%.
- **Brief 041 (PR #41 — closed, not merged)**: tried to flip the TU to Matching. Failed with 4 link errors: `undefined: 'lbl_eu_80663458'`. Root cause: the `.sdata 0x80663458–0x80663460` carve gave `g3d_anmclr.cpp` a range containing an 8-byte symbol that no class in the TU actually owns. Decomper bailed cleanly per the brief's rules.
- **Brief 042 (PR #43)**: scaffolder dropped the bad `.sdata` carve and re-absorbed `lbl_eu_80663458` back into `nw4r_dataa.s`. The orphan turned out to be two namespace-level function pointers (`PlayPolicy_Onetime` + `PlayPolicy_Loop` in `nw4r::g3d`), not a class static — confirming the carve was wrong, not the dead-code trim.

Now we retry the flip with the unblocker in place.

## Scope

- `configure.py` — change `NonMatching` to `Matching` for `g3d_anmclr.cpp` (1 line, same as brief 041's attempted edit).
- If the flip lights up but produces small diff against the per-TU report, iterate on the source in `libs/nw4r/src/g3d/g3d_anmclr.cpp` to close the gap.

## Non-scope

- Don't re-touch `config/us/splits.txt` — that's the scaffolder's lane. If you find a new splits issue, bail and report (like brief 041 did).
- Don't touch other TUs, even if they show as adjacent in the build report.
- Don't widen to JP / EU (no baseroms).

## Success

- `python configure.py --version us && ninja` builds clean.
- `build/us/main.dol` SHA-1 stays `214b15173fa3bad23a067476d58d3933ad7037b7`.
- `g3d_anmclr.cpp` shows as Matching in `build/us/report.json`.
- NW4R Data progress climbs into the high 90s / 100% (brief 039's carve sized the per-TU claim to deliver this; brief 042's fix removed only the wrong .sdata 8 bytes, so the rest still counts).

## Test plan

- [ ] Apply the configure.py edit
- [ ] Run `ninja` — full DOL link should now succeed (no more `undefined: 'lbl_eu_80663458'`)
- [ ] Verify SHA-1
- [ ] Quote the relevant lines from `build/us/report.json` showing g3d_anmclr.cpp at 100% (code + data)
- [ ] If the flip fails for a *new* reason (not the same multi-define, not the same .sdata blocker), follow brief 041's pattern: bail, report what blocks, don't widen scope.

## Branch

`decomper/g3d-anmclr-flip-retry-2`

## If it works

Note that in the PR description with the relevant report.json numbers — that's the cycle's headline win. Brain will summarise for cntrl_alt_lenny.

## If it fails

Same pattern as brief 041's PR — close it with a clean bail report. The blocker analysis is the deliverable; the configure.py change itself shouldn't merge if the build breaks. Brain will close + scope the next fix.
