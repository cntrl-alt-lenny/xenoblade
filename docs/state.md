# docs/state.md — current in-flight work

Brain's running snapshot of the decomp. Updated by **brain only**; every
other agent reads it before starting work and after every merge to find
out what's next.

If you're a fresh `brain` session, read this *and*
[`AGENTS.md`](../AGENTS.md) before reviewing any PR.

## At-a-glance

- **Date of last update:** 2026-05-22
- **Primary target region:** JP (`a564033aee46988743d8f5e6fdc50a8c65791160`)
- **Match progress (from `python3 tools/match_stats.py`):**
  - `Matching` (all regions): **218 TUs**
  - `MatchingFor("jp")`: **115 TUs**
  - `NonMatching`: **833 TUs**
  - **Total matched any region: 333 / 1166 (~28.6%)**
  - No `MatchingFor("eu")` or `MatchingFor("us")` yet — every region-
    specific match so far is JP-only.
- **Open PRs upstream (`xbret/xenoblade`):** none.
- **Open PRs on fork (`cntrl-alt-lenny/xenoblade`):** none — both day-1
  PRs merged into fork main today.
- **Fork main vs upstream main:** fork is **1 commit ahead** of
  `xbret/main` (consolidated commit `44a4b9a`). Upstream cascade
  pending — opening an upstream PR is cntrl_alt_lenny's call.
- **Open briefs:** 1 (decomper / kyoshin-ocBuiltin — still untouched).
- **Live agents this week:** brain (this session), scaffolder (delivered
  brief 002), decomper (no work yet — needs a re-kick).

`python3 configure.py progress` only works *after* a successful `ninja`
build — it reads `build/<ver>/report.json`. If you see "Report file
build/jp/report.json does not exist", run `ninja` once first.

## In-flight briefs

### [`001-kyoshin-ocBuiltin`](briefs/001-kyoshin-ocBuiltin.md) — decomper

- **Status:** still untouched. Decomper did not start in the first
  cycle — brain re-kicked today (2026-05-22).
- **Goal:** match `kyoshin/plugin/ocBuiltin.cpp` against the US baserom,
  flip its Object entry to `MatchingFor("us")`. Project's first
  region-specific match outside JP.
- **Size:** 4 functions / 356 bytes `.text`. Smallest unmatched TU in
  `kyoshin/plugin/` (confirmed by today's `next_targets.py` run —
  ranks #3 in the `kyoshin/plugin` scope behind `pluginTime.cpp` and
  `pluginHelp.cpp`, both even smaller).
- **Branch (when started):** `decomper/kyoshin-ocBuiltin`.
- **Blocks:** nothing. Picked precisely because surrounding plugin/
  siblings are already matched (templates next door).

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
4. **Check brief 001 status**: has decomper opened a PR for
   `kyoshin/plugin/ocBuiltin.cpp` yet? If yes, review it. If still no
   (this is now the second cycle for brief 001), flag in the next
   message that we may need to swap to a different decomper session
   or simplify the brief.
5. **After any merge:** re-run `python3 tools/match_stats.py` to
   refresh the *Match progress* numbers in this file, log the merge
   in the *Recent activity log*, and either commit straight to fork
   main (routine bookkeeping) or open a `brain/<scope>` PR if the
   change is substantive enough to want a review trail.
6. **Upstream cascade decision** (currently pending — 1 commit ahead):
   cntrl_alt_lenny can ask brain to open an upstream PR from
   `cntrl-alt-lenny:main` → `xbret:main` to send merged fork work to
   the project. Until that lands, fork main stays ahead of upstream.

## Recent activity log

- **2026-05-22** — First review/merge cycle. Brain consolidated all of
  day-1's scaffolding (multi-agent manifest, briefs 001+002,
  `.gitignore` ROM patterns, `download_tool.py` curl fallback,
  `cloud → scaffolder` rename) **plus** scaffolder's brief 002
  deliverable (`tools/_object_table.py` + `tools/match_stats.py` +
  `tools/next_targets.py`) into a single squash commit on fork main
  (`44a4b9a`). Branch chain `brain/initial-setup` →
  `brain/rename-cloud-to-scaffolder` → `scaffolder/progress-and-targets`
  collapsed at merge time and deleted afterward. Verified ninja still
  green on US build (`build/us/main.dol: OK`). Fork main is now
  1 commit ahead of `origin/main` — upstream PR not yet opened.
- **2026-05-22** — Discovered decomper had not started brief 001
  (worktree on stale `decomper/initial-setup` with no work, no
  branch on fork). Re-kicked decomper for next cycle. Worktree
  detached to fork main and the stale branch deleted.
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
