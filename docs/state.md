# docs/state.md — current in-flight work

Brain's running snapshot of the decomp. Updated by **brain only**; every
other agent reads it before starting work and after every merge to find
out what's next.

If you're a fresh `brain` session, read this *and*
[`AGENTS.md`](../AGENTS.md) before reviewing any PR.

## At-a-glance

- **Date of last update:** 2026-05-22 (cycle 2 — afternoon)
- **Primary target region:** JP nominally, but this brain machine only
  has US extracted, so US is the working region for verification.
- **Match progress (from `python3 tools/match_stats.py`):**
  - `Matching` (all regions): **218 TUs**
  - `MatchingFor("jp")`: **115 TUs**
  - `MatchingFor("us")`: **1 TU** (new this cycle — `kyoshin/plugin/ocBuiltin.cpp`)
  - `NonMatching`: **832 TUs**
  - **Total matched any region: 334 / 1166 (~28.6%)**
  - `--region us` ground truth: 217 / 1160 matched in the US build
    (cross-checked against `build/us/report.json`).
- **Open PRs upstream (`xbret/xenoblade`):** none.
- **Open PRs on fork (`cntrl-alt-lenny/xenoblade`):** none — both
  cycle-2 PRs merged into fork main.
- **Fork main vs upstream main:** fork is **4 commits ahead** of
  `xbret/main` (`44a4b9a` scaffolding, `284f1dc` bookkeeping,
  `f46d0fc` region-aware stats, `182e046` ocBuiltin match). Upstream
  cascade still pending — cntrl_alt_lenny's call.
- **Open briefs:** 1 (`004-retag-region-specific-matching`, drafted
  by scaffolder; needs JP/EU baseroms to verify, so queued for
  decomper but not yet kicked).
- **Live agents this cycle:** brain (this session), decomper (matched
  ocBuiltin — first MatchingFor("us") on the project), scaffolder
  (delivered brief 003 and drafted 004 from drift investigation).

`python3 configure.py progress` only works *after* a successful `ninja`
build — it reads `build/<ver>/report.json`. If you see "Report file
build/jp/report.json does not exist", run `ninja` once first.

## In-flight briefs

### [`004-retag-region-specific-matching`](briefs/004-retag-region-specific-matching.md) — decomper (queued)

- **Status:** drafted by scaffolder, not yet kicked. Brain endorses
  the framing (decomper owns `Object(...)` status flips per AGENTS.md).
- **Blocked on:** **JP and EU baseroms.** Brief success criteria
  require all three regions to `ninja` green; this brain machine only
  has US extracted. Either extract JP/EU first, or merge with US-only
  verification and explicitly note the JP/EU side as unverified.
- **Scope:** three single-line `configure.py` edits — retag
  `assert.c` + `encjapanese.c` as `MatchingFor("jp")`, retag
  `encunicode.c` as `MatchingFor("eu", "us")`. Tooling already
  treats these correctly (scaffolder's `--region` flag uses
  `splits.txt` as ground truth) — this is a cosmetic-but-canonical
  fix per the CLAUDE.md convention.

### Cycle 2 outbound (drafted in handoff message, not yet a file)

- **Brief 005 (decomper)** — match `kyoshin/plugin/pluginTime.cpp`
  against US. 168 bytes `.text`, smallest unmatched TU in
  `kyoshin/plugin/`. Same template situation as ocBuiltin (sibling
  matches one directory up). When/if it also matches JP, promote to
  plain `Matching`. Branch: `decomper/kyoshin-pluginTime`.
- **Brief 006 (scaffolder)** — add `vmBuiltinOCRegist` to
  `libs/monolib/include/monolib/vm/yvm2.h` (decomper flagged the
  missing declaration in PR #4) and build a `tools/header_gaps.py`
  surveyor that finds other `extern` forward-declares in `src/` that
  should live in headers instead. Branch:
  `scaffolder/header-gaps-survey`.

Both will be formalised as `docs/briefs/005*.md` and `006*.md` by
brain after the agents pick them up — for now the handoff message is
the brief.

## Repository layout reminders

- **Working clone:** `~/Dev/xenoblade/brain/`. macOS host, Apple
  Silicon. `wine` installed via Game Porting Toolkit cask. `python3`
  is the interpreter — `python` is *not* aliased on this machine, so
  read every CLAUDE.md command as `python3` even when it says
  `python`. Don't rename CLAUDE.md — that command spelling is
  inherited from upstream and edits create merge friction.
- **GitHub remotes:**
  - `origin` → `xbret/xenoblade` (the upstream project, not the
    user's repo).
  - `fork`   → `cntrl-alt-lenny/xenoblade` (the user's fork; this
    is where every branch gets pushed).
  - PRs flow `fork/<branch>` → `origin/main`. See
    [`AGENTS.md § PRs and the fork remote`](../AGENTS.md#prs-and-the-fork-remote).
- **No `build/` artifacts committed** — `.gitignore` covers them.
  First `ninja` invocation downloads `dtk`, `objdiff-cli`, and the
  mwcc compilers into `compilers/<mw_version>/`.

## Next-brain TODO

When the next brain session picks up:

1. **Check for PRs upstream first**: `gh pr list --repo xbret/xenoblade
   --state open`. If anything is open, that's the highest-priority
   review work.
2. **Check the user's fork**: `gh pr list --repo cntrl-alt-lenny/xenoblade
   --state open`. After the first cycle, the expectation is **one PR
   per active agent** (decomper for brief 001, scaffolder for whatever
   brief they're working).
3. **Confirm the build baseline**: this brain machine only has the
   **US** baserom extracted (`orig/us/sys/main.dol`); `orig/jp/` is
   empty. Run `python3 configure.py --version us && ninja` to verify
   `build/us/main.dol: OK` against the SHA-1 gate. If/when the user
   extracts JP, switch primary verification to JP.
4. **Check cycle-3 brief status**: cycle-3 outbound briefs (drafted
   in handoff messages, not yet `.md` files) are 005 (decomper /
   `pluginTime.cpp`) and 006 (scaffolder / `header_gaps.py` +
   `vmBuiltinOCRegist`). If their PRs (#5 and #6 by number, presumably)
   exist, review them. If they don't, no action — wait.
5. **Brief 004 stays queued** until JP/EU baseroms are extracted on
   the active brain machine. Don't kick it without that — partial
   verification (US only) would land but the brief's success criteria
   asks for all three.
6. **After any merge:** re-run `python3 tools/match_stats.py` to
   refresh the *Match progress* numbers in this file, log the merge
   in the *Recent activity log*. Use `--cross-check
   build/<region>/report.json` as a sanity step now that scaffolder's
   tool exists — drift between configure.py status and the build
   report should be caught at merge time, not discovered weeks later.
7. **Upstream cascade decision** (currently pending — fork is **4
   commits ahead**): each cycle that lands on fork main without an
   upstream PR widens the gap. cntrl_alt_lenny can ask brain to open
   an upstream PR from `cntrl-alt-lenny:main` → `xbret:main` to
   submit the merged fork work to xbret. Worth raising again next
   review.
8. **JP/EU baserom extraction** is the unblock for brief 004 and any
   non-US match work. Suggest cntrl_alt_lenny extracts JP next so
   the project's primary region (per CLAUDE.md) becomes verifiable
   on this brain.

## Recent activity log

- **2026-05-22 (cycle 2 / afternoon)** — Decomper landed brief 001
  (`kyoshin/plugin/ocBuiltin.cpp` → `MatchingFor("us")`, commit
  `182e046`). Project's first US-region match. All 4 functions
  byte-identical, SHA-1 gate green on a clean rebuild of the TU.
  Scaffolder landed brief 003 (`tools/match_stats.py --region` +
  `--cross-check`, commit `f46d0fc`) — the drift investigation
  surfaced a 3-TU mistag bug (assert.c, encjapanese.c, encunicode.c
  tagged `Matching` but only shipping in subsets of regions),
  written up as brief 004 for a future decomper pass. Cross-check
  vs US `report.json` now PASSes (216 == 216 complete_units).
  Sjiswrap encoding warning during decomper's compile (UTF-8
  em-dashes in source comments) — non-fatal, flagged to decomper
  for future ASCII-only convention.
- **2026-05-22 (cycle 1 / morning)** — First review/merge cycle. Brain
  consolidated all of day-1's scaffolding (multi-agent manifest,
  briefs 001+002, `.gitignore` ROM patterns, `download_tool.py` curl
  fallback, `cloud → scaffolder` rename) **plus** scaffolder's brief 002
  deliverable (`tools/_object_table.py` + `tools/match_stats.py` +
  `tools/next_targets.py`) into a single squash commit on fork main
  (`44a4b9a`). Branch chain `brain/initial-setup` →
  `brain/rename-cloud-to-scaffolder` → `scaffolder/progress-and-targets`
  collapsed at merge time and deleted afterward. Verified ninja still
  green on US build (`build/us/main.dol: OK`). State.md bookkeeping
  commit `284f1dc` on fork main same morning.
- **2026-05-22 (cycle 1)** — Discovered decomper had not started brief
  001 in the first attempt (worktree on stale `decomper/initial-setup`
  with no work, no branch on fork). Re-kicked decomper — they delivered
  in cycle 2 (above).
- **2026-05-21** — Initial scaffold landed (`46ade67`,
  `7652286`, `d31723f`, `d968d0c`). Multi-agent coordination
  manifest, ROM-image gitignore patches, `download_tool.py` curl
  fallback, and the first decomper brief (001-kyoshin-ocBuiltin).
- **2026-05-21** — `docs/state.md` created. Fork/origin workflow
  section added to `AGENTS.md`. Scaffolder brief 002 drafted
  (originally as `002-cloud-…`; renamed in the same wave as the
  role rename below).
- **2026-05-21** — Cloud agent renamed to **scaffolder** on branch
  `brain/rename-cloud-to-scaffolder`. The prior slug implied where
  the agent runs; the new slug names what it does (scaffolds tools,
  libs, CI, research). Parallel with `decomper` (both `-er` names).
  In-repo spec updated; sibling worktree filesystem rename is a
  separate follow-up cntrl_alt_lenny will run with `git worktree
  move`. Historical PRs / branches on the `cloud/` prefix remain
  valid in git history.
