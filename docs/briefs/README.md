# Decomp Briefs

Short, scoped task descriptions for individual decomp efforts.
Each brief lives in its own file (`NNN-<slug>.md`).

A brief is a short spec the brain writes for another agent. It pins
down scope, success criteria, and the branch convention so the agent
can pick it up cold without re-discovering context.

## Format

```
### <agent-slug>/<scope>

**Goal:** one sentence describing what's being built.
**Scope:** files / directories this task may touch.
**Non-scope:** explicit "don't touch these".
**Success:** how we'll know it's done (tests pass / PR merges cleanly / etc).
**Branch:** suggested branch name following the AGENTS.md convention.
```

## Briefs

Briefs 001–037 lived locally per the prior workflow (their numbers are
referenced in git history via `git log --grep='brief 0'`). Tracked-in-repo
brief numbering starts at 038.

| #   | Brief | Goal | Status |
|-----|-------|------|--------|
| 038 | [`scaffolder-functions-hpp-sjis`](038-scaffolder-functions-hpp-sjis.md) | Investigate sjiswrap Shift-JIS warning on `include/functions.hpp`; fix if real. | Closed (PR #40) |
| 039 | [`decomper-close-one-partial-match`](039-decomper-close-one-partial-match.md) | Push one ≥ 87% partial-match TU (start with `CPadManager` at 99.5%) to 100% matched. | Abandoned (superseded by 041) |
| 040 | [`scaffolder-vtable-shape-detection`](040-scaffolder-vtable-shape-detection.md) | Add vtable-shape detector to `tools/suggest_symbol_name.py`; emit `__vt__<class>` at Tier-1 confidence. | Closed (PR #42) |
| 041 | [`decomper-g3d-anmclr-flip-retry`](041-decomper-g3d-anmclr-flip-retry.md) | Retry `libs/nw4r/src/g3d/g3d_anmclr.cpp` flip (US) now that PR #39's carve cleared the multi-define. | Closed (PR #41 — flip fails, new blocker found → split into 042 + 043) |
| 042 | [`scaffolder-anmclr-sdata-uncarve`](042-scaffolder-anmclr-sdata-uncarve.md) | Drop `g3d_anmclr.cpp`'s `.sdata` carve (over-claimed `lbl_eu_80663458`); absorb back into `nw4r_dataa.s`. | Closed (PR #43) |
| 043 | [`decomper-vtable-rename-wave-2`](043-decomper-vtable-rename-wave-2.md) | Use PR #42's new vtable detector to find + rename 10–25 more vtable placeholders in `config/us/symbols.txt`. | Closed (PR #44 — 25 renames landed) |
