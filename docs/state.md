# docs/state.md — current in-flight work

Brain's running snapshot of the decomp. Updated by **brain only**; every
other agent reads it before starting work and after every merge to find
out what's next.

If you're a fresh `brain` session, read this *and*
[`AGENTS.md`](../AGENTS.md) before reviewing any PR.

## At-a-glance

- **Date of last update:** 2026-05-21
- **Primary target region:** JP (`a564033aee46988743d8f5e6fdc50a8c65791160`)
- **Match progress (from `configure.py` Object table):**
  - `Matching` (all regions): **217 TUs**
  - `MatchingFor("jp")`: **115 TUs**
  - `NonMatching`: **833 TUs**
  - **Total matched any region: 332 / 1165 (~28%)**
  - No `MatchingFor("eu")` or `MatchingFor("us")` yet — every region-
    specific match so far is JP-only.
- **Open PRs upstream (`xbret/xenoblade`):** none.
- **Open briefs:** 1 (decomper / kyoshin-ocBuiltin — first match brief).
- **Live agents this week:** brain (this session), decomper (not yet
  started), cloud (not yet started).

`python3 configure.py progress` only works *after* a successful `ninja`
build — it reads `build/<ver>/report.json`. If you see "Report file
build/jp/report.json does not exist", run `ninja` once first.

## In-flight briefs

### [`001-kyoshin-ocBuiltin`](briefs/001-kyoshin-ocBuiltin.md) — decomper

- **Status:** drafted, not yet picked up.
- **Goal:** match `kyoshin/plugin/ocBuiltin.cpp` against the US baserom,
  flip its Object entry to `MatchingFor("us")`. Project's first
  region-specific match outside JP.
- **Size:** 4 functions / 356 bytes `.text`. Smallest unmatched TU in
  `kyoshin/plugin/`.
- **Branch (when started):** `decomper/kyoshin-ocBuiltin`.
- **Blocks:** nothing. Picked precisely because surrounding plugin/
  siblings are already matched (templates next door).

### [`002-cloud-progress-and-targets`](briefs/002-cloud-progress-and-targets.md) — cloud

- **Status:** drafted, not yet picked up.
- **Goal:** two small, no-baserom-needed tools — (a) a self-contained
  `tools/match_stats.py` that reads `configure.py`'s Object table
  directly and prints per-module match counts (works without
  `report.json`), and (b) a `tools/next_targets.py` that picks the
  smallest unmatched TUs sitting next to matched siblings.
- **Branch (when started):** `cloud/progress-and-targets`.
- **Blocks:** nothing. Both tools are pure-Python over `configure.py`
  + `config/<ver>/symbols.txt`; cloud doesn't need a built ROM.

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
   --state open` (in case there's a draft against the fork itself).
3. **Confirm the build baseline**: from a clean `build/` if you can
   afford the rebuild time, `rm -rf build && python3 configure.py &&
   ninja`. Green = baseline holds.
4. **Check brief 001 status**: has decomper opened a PR for
   `kyoshin/plugin/ocBuiltin.cpp` yet? If yes, review it; if no, no
   action — it's their queue, not yours.
5. **Check brief 002 status**: has cloud opened a PR for
   `tools/match_stats.py` + `tools/next_targets.py`? Same review-or-
   wait logic.
6. **After any merge:** update this file's *Match progress* counts
   and *Open briefs* list, then commit on `brain/<scope>`.

## Recent activity log

- **2026-05-21** — Initial scaffold landed (`46ade67`,
  `7652286`, `d31723f`, `d968d0c`). Multi-agent coordination
  manifest, ROM-image gitignore patches, `download_tool.py` curl
  fallback, and the first decomper brief (001-kyoshin-ocBuiltin).
  No matches yet from this brain session — that's decomper's turn.
- **2026-05-21** — `docs/state.md` created (this file). Fork/origin
  workflow section added to `AGENTS.md`. Cloud brief 002 drafted.
