# State of play

Churn-heavy brain log. Split out of `AGENTS.md` so the manifest stays
stable while this file turns over every working chunk.

The brain updates this file at the end of every session so the next
brain (possibly on a different machine or LLM) can catch up in under
a minute. Keep it short. If you're the brain reading this cold:
`git log --oneline -20` and the open-PR list fill in whatever this
misses.

**Last updated:** 2026-05-26 (morning). Brain on Mac. US build green
@ SHA1 `214b15173fa3bad23a067476d58d3933ad7037b7`. Opened **three
upstream PRs** against `xbret/xenoblade` for the eligible decomp
work done in the recent fork cycles:

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

## In flight (post this brain-PR)

- **Brief 040** (scaffolder): vtable-shape detector in
  `tools/suggest_symbol_name.py`. No PR yet.
- **Brief 041** (decomper): retry `g3d_anmclr.cpp` flip US.
  No PR yet.

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

1. Review the two incoming PRs (brief 040 from scaffolder, 041 from
   decomper). Run the build, verify SHA1, summarise in plain English
   for cntrl_alt_lenny, offer to merge.
2. Check `.git/agent-inbox/` for scaffolder-latest.md and
   decomper-latest.md — the Stop hook should now capture cross-agent
   replies since all three are worktrees of brain.
3. After brief 041 lands (g3d_anmclr at 100%), refresh
   `build/us/report.json` top-10 and dispatch the next decomper TU.
   `CPadManager` (99.5%), `snd_TaskManager` (98.3%),
   `CDeviceFileJob` (96.2%) remain at top.
4. Consider whether to extract JP / EU regions next. cntrl_alt_lenny's
   call — purely scope, not technical.

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
