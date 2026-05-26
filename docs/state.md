# State of play

Churn-heavy brain log. Split out of `AGENTS.md` so the manifest stays
stable while this file turns over every working chunk.

The brain updates this file at the end of every session so the next
brain (possibly on a different machine or LLM) can catch up in under
a minute. Keep it short. If you're the brain reading this cold:
`git log --oneline -20` and the open-PR list fill in whatever this
misses.

**Last updated:** 2026-05-26 (late morning). Brain on Mac (native
arm64 build works fine — ninja + wibo run through unchanged). US
build green @ SHA1 `214b15173fa3bad23a067476d58d3933ad7037b7`.

### Upstream PR aftermath

All three upstream PRs (xbret#31/#32/#33) **closed by collaborator
CelestialAmber** at ~08:06 UTC with the comment on #31:

> "I'm sorry, but I don't want to accept AI assisted commits."

#32 and #33 were closed seconds later without comment (batch close).
Hard "no" from upstream on AI-attributed work. **Standing rule for
next brain: don't open more upstream PRs until cntrl_alt_lenny has
discussed an attribution change with the maintainer.** Fork work
continues unaffected — these were the first attempt at upstreaming
and the policy was unknown beforehand.

### Cycle 23 closed (PR #45 merged, PR #46 closed)

- **PR #45** (scaffolder, brief 044) merged at `bb41537`. Confirmed
  the stale-asm hypothesis (`nw4r_data.s` lingered in
  `build/us/asm/` after PR #39 carve). Added a Troubleshooting
  section to `AGENTS.md` documenting `rm -rf build/<region>/asm/
  && ninja` recovery, plus a defensive stderr warn in the vtable
  detector when `.obj` is found in >1 asm file. Brain-rebuilt;
  SHA-1 green.
- **PR #46** (decomper, brief 045) closed at decomper's request.
  Flip attempt #2 of `g3d_anmclr.cpp`. Per-TU report shows 100%
  across every section (data, code, sdata2, text) — the TU
  itself is matched. But DOL SHA-1 shifts by +8 bytes due to
  cascade. Root cause via `dtk elf info`: inline
  `GetAnmPlayPolicy` in `g3d_anmobj.h` has a function-static
  `policyTable[ANM_POLICY_MAX]` of 8 bytes that every TU
  including the header emits privately. Decomper's analysis +
  fix recommendation lined up correctly; the fix is header-lane,
  not source-lane.

### Cycle 24 dispatched

- **Brief 046** (scaffolder): move `policyTable` out of inline
  `GetAnmPlayPolicy` in `g3d_anmobj.h`. One header + one source
  edit. Unblocks the g3d_anmclr flip.
- **Brief 047** (decomper): wave 3 of vtable renames using PR
  #42's detector. Independent of 046. Target 25 from the
  ~264 remaining candidates.
- **Brief 048** (will be scoped after 046 lands): third attempt
  at the `g3d_anmclr.cpp` flip — should be third-time lucky if
  brief 046's cascade theory holds.

---

**Cycle 22 closed** (both PRs merged at `f11177c`):
- **PR #43** (scaffolder, brief 042) — drop `g3d_anmclr.cpp`'s
  `.sdata` carve; re-absorb `lbl_eu_80663458` back into
  `nw4r_dataa.s`. The orphan turned out to be two namespace-level
  function pointers (`PlayPolicy_Onetime` + `PlayPolicy_Loop` in
  `nw4r::g3d`), not a class static. SHA-1 verified, brain-rebuilt.
- **PR #44** (decomper, brief 043) — **25 vtable renames** in
  `config/us/symbols.txt` using PR #42's new detector. All at
  confidence 1.00. First production use of the detector validated
  the design. 264 vtable-shape candidates remain (room for wave 3+).

Cycle 21 (earlier today): PR #42 merged (vtable detector), PR #41
closed (g3d_anmclr flip blocker identified, split into 042 + 043).

Earlier today: opened **three upstream PRs** against `xbret/xenoblade`
for the eligible decomp work done in the recent fork cycles:

- [xbret#31](https://github.com/xbret/xenoblade/pull/31) — 22 symbol
  renames in `config/us/symbols.txt` (21 cf/CTTask vtables + spScene).
  Cherry-picked surgically; diff is exactly 22 insertions + 22
  deletions vs upstream main.
- [xbret#32](https://github.com/xbret/xenoblade/pull/32) —
  `g3d_anmclr.cpp` carve in `config/us/splits.txt` (nw4r_data.s →
  dataa + datab, 4 per-TU ranges). Pure config win, enables 88.24%
  → 97.18% NW4R data matching once the TU flips.
- [xbret#33](https://github.com/xbret/xenoblade/pull/33) —
  `tools/check_port_compat.py` (new tool, ~838 lines). Optional
  source-port pre-vetting tool. Fork-isms scrubbed.

PR #40 equivalent (em-dash fix) **not upstreamed**: the bug doesn't
exist on upstream's `include/functions.hpp` — that file's comment
block (where the em dash lived) was added by fork-only commit
`a10ebbc` as part of brief 010's extern-C wrap. Both bug and fix
are fork-local.

Yesterday's recap (Windows): 3 fork PRs merged (#38 renames, #39
carve+tool, #40 em-dash). Briefs 040 + 041 dispatched. Ported
spirit-caller's `.githooks/pre-push` (SHA-1-gate) +
`tools/install_git_hooks.py` — catches corrupted-build push before
brain has to review it.

## Headline

Today closed the cycle that had been hanging open since 2026-05-23:
PR #38 landed 22 placeholder renames (21 vtables + spScene), PR #39
landed the `g3d_anmclr` rodata carve + the `check_port_compat`
gain-check, and PR #40 cleared the long-standing sjiswrap warning on
`include/functions.hpp` by killing a UTF-8 em dash. Net: data
progress moved (NW4R 60→276 of 284 bytes matched), tooling
strengthened, build noise reduced. Next round: brief 040 (vtable
shape detection — PR #38's feedback) + brief 041 (retry the
g3d_anmclr flip — Stream B from old brief 038, now unblocked).

Also today: framework restructured from 3 separate clones to 3
worktrees (brain main, decomper + scaffolder detached HEAD), so
the agent-inbox hook can capture cross-agent replies for the brain
to read.

## Baseline gate (what every PR must preserve)

- `python configure.py --version us && ninja` builds clean.
- `build/us/main.dol` SHA1 stays `214b15173fa3bad23a067476d58d3933ad7037b7`.
- No new build warnings (sjiswrap on `include/functions.hpp` is now
  cleared; don't reintroduce non-ASCII outside Shift-JIS-safe
  ranges).

(JP and EU baselines still TBD — baseroms not yet extracted for
those regions.)

## Today's merges (just-landed)

- `8da284c` PR #40 — scaffolder: em dash → ASCII in
  `include/functions.hpp`. Closes brief 038. sjiswrap warning gone,
  SHA1 unchanged.
- `cf6b97`-ish (squash-merged) PR #38 — decomper: 22 placeholder
  renames in `config/us/symbols.txt` (21 vtables + 1 spScene). Cycle-20
  Stream A. Streams B/C deferred to brief 041 + future scaffolder work.
- `a847bb7`-ish (squash-merged) PR #39 — scaffolder:
  `tools/check_port_compat.py` gain-check + `g3d_anmclr` rodata carve
  in `config/us/splits.txt`. NW4R data: 60 → 276 of 284 matched bytes
  (97.18%).

## Cycle 22 outcome (just-closed)

- **PR #43 merged**: scaffolder dropped `g3d_anmclr.cpp`'s `.sdata`
  carve (1 line removed) and extended `nw4r_dataa.s`'s `.sdata` end
  to absorb `lbl_eu_80663458` (1 line edited). Closes brief 042.
  Scaffolder did their own local build via symlinked baserom —
  SHA-1 green there + brain confirmed locally on the merged result.
  NW4R Data ratio dipped from 97.18% to 97.10% as expected (the
  8 bytes move from per-TU count back to catch-all).
- **PR #44 merged**: decomper did **25 vtable renames** in
  `config/us/symbols.txt` using PR #42's new detector. All
  confidence 1.00, all derived from `__dt__<class>Fv` destructor
  entries. First production use validated the detector design.
  Skipped 2 collisions (one points at a curious double-define of
  `nw4r::g3d::ScnGroup` in `build/us/asm/` between `nw4r_data.s`
  and `nw4r_datab.s` — likely stale-asm artifact post-carve,
  worth a scaffolder sanity-check). Closes brief 043. SHA-1
  brain-verified.

## Cycle 23 — dispatched

- **Brief 044** (scaffolder): investigate + document the `ScnGroup`
  double-define artifact the decomper flagged in PR #44's notes
  (stale `build/us/asm/` files from pre-carve splits.txt state).
  Document the `rm -rf build/<region>/asm/ && ninja` recovery in
  AGENTS.md. Optional defensive update to the vtable detector.
- **Brief 045** (decomper): retry the `g3d_anmclr.cpp` flip now
  that brief 042 cleared the blocker. Closes the loop opened in
  briefs 039/041 — should hit NW4R Data 100% if it works.
  Same bail-and-report rule as brief 041 if a new blocker shows
  up.

### Upstream PRs awaiting xbret review

| PR | What | Risk | Notes |
|---|---|---|---|
| [xbret#31](https://github.com/xbret/xenoblade/pull/31) | 22 placeholder renames in US symbols.txt | None (TUs still NonMatching; names are informational) | 21 vtables + 1 spScene |
| [xbret#32](https://github.com/xbret/xenoblade/pull/32) | g3d_anmclr.cpp carve in US splits.txt | None today (SHA-1 unchanged); enables future flip | 88.24% → 97.18% NW4R data once TU flips |
| [xbret#33](https://github.com/xbret/xenoblade/pull/33) | New tools/check_port_compat.py | None (no config/build impact) | Optional — maintainer may decline if upstream doesn't do source-porting |

Each lives on a `upstream-*` branch on fork that's based on
`origin/main` (xbret upstream on Mac; on Windows the remote names
are swapped — `upstream/main`). Don't delete those branches until
the PRs are merged or closed.

## Next-brain TODO

1. If user fires cycle 23: write briefs 044 + 045 (or 044 +
   `g3d_anmclr` flip retry — see "Cycle 23" section above).
2. Watch the three upstream PRs (xbret#31/#32/#33) for review
   comments; respond where needed.
3. Refresh `build/us/report.json` top-10 if cycle 23 brings new
   matches. `CPadManager` (99.5%), `snd_TaskManager` (98.3%),
   `CDeviceFileJob` (96.2%) still top of the close-to-matching
   list.
4. Consider whether to extract JP / EU regions next.
   cntrl_alt_lenny's call — purely scope, not technical.
5. Agent-inbox check: `.git/agent-inbox/` on the Windows brain
   only (this Mac brain doesn't host decomper/scaffolder
   worktrees). Cycle 22 agents pushed PRs directly, so no inbox
   notes to harvest this round.

## Cross-machine handoff notes

- **Worktree structure:** Brain is the main checkout; decomper +
  scaffolder are worktrees of brain (`git worktree list` from any of
  them shows all three). Their `.git` is a pointer file, not a dir.
  Shared `.git/agent-inbox/` lives in `brain/.git/agent-inbox/`.
- **Toolchain:** Native Windows + ninja + Python 3.12.10. `wibo`
  v1.0.0-beta.5 auto-downloaded by `configure.py`.
- **DolphinTool location** (used for RVZ extraction):
  `C:\Users\leona\Games\Dolphin\DolphinTool.exe`. The `-g` flag
  outputs to a `DATA/` subfolder that must be flattened.
- **Baserom:** USA only, at `brain/orig/us/`. `decomper/orig/us/`
  is junctioned to brain's (sys + files). scaffolder doesn't need
  the baserom (toolchain-free role).
- **Upstream remote:** Configured in brain as
  `https://github.com/xbret/xenoblade.git`. Branch off `upstream/main`
  for upstream-targeted PRs. Worktrees share the remote config.
- **Open warnings:** None — sjiswrap warning was the last known one.
- **Pre-push hook:** `.githooks/pre-push` installed via
  `python tools/install_git_hooks.py`. On any worktree that has
  `build/us/main.dol`, it SHA-1-checks the DOL against the baseline
  before allowing push of changes under `config/`, `src/`, `libs/`,
  `include/`, or `configure.py`. Gracefully skips on
  scaffolder-style toolchain-free worktrees (no baserom). Bypass
  once with `git push --no-verify`. Each fresh worktree needs
  `python tools/install_git_hooks.py` once to set
  `core.hooksPath`.
