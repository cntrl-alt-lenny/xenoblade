### cloud/progress-and-targets

**Goal:** Two small, self-contained Python tools under `tools/` that
work *without* a successful baserom build. Both are useful from day
one and don't depend on the mwcc toolchain, `dtk`, or
`build/<ver>/report.json`.

This is cloud's **first brief**. Picked because it's pure-Python over
[`configure.py`](../../configure.py)'s Object table — cloud can
write, test, and self-verify it without running `ninja`, which is
exactly the role's constraint (see
[`AGENTS.md § Cloud`](../../AGENTS.md)).

## Scope

Two new scripts, in this order:

### Tool A — `tools/match_stats.py`

A static counter that reads `configure.py`'s `Object(...)` entries
and prints match progress *without* needing a built ROM or
`report.json`.

- **Input:** parse `configure.py` directly. The shape we care about
  is the long list of `Object(Matching|NonMatching|MatchingFor(...),
  "<path>")` calls. Regex or `ast.parse` — your call. `ast.parse` is
  safer if any `Object(...)` call spans multiple lines.
- **Output:** a small summary like
  ```
  Total TUs:           1165
    Matching (all):     217  (18.6%)
    MatchingFor(jp):    115   (9.9%)
    MatchingFor(eu):      0   (0.0%)
    MatchingFor(us):      0   (0.0%)
    NonMatching:        833  (71.5%)
  Total matched any:    332  (28.5%)

  By module (top 10 unmatched):
    src/kyoshin/...     <count>
    libs/RVL_SDK/...    <count>
    ...
  ```
- **CLI:**
  - `python3 tools/match_stats.py` — print the summary.
  - `python3 tools/match_stats.py --json` — machine-readable for CI.
  - `python3 tools/match_stats.py --module <prefix>` — filter to one
    subtree (e.g. `--module src/kyoshin/plugin`).
- **Why this and not `python3 configure.py progress`:** the existing
  `progress` mode requires `build/<ver>/report.json`, which only
  exists after a full successful build. New contributors and brief-
  writers need a count *before* they can build. `match_stats.py`
  fills that gap. It does NOT replace `progress` — `progress` is
  authoritative about bytes-matched percentages because it reads
  objdiff's report; `match_stats.py` is authoritative about
  TU-count progress because it reads the source of truth
  (`configure.py`).

### Tool B — `tools/next_targets.py`

A heuristic picker that surfaces promising unmatched TUs.

- **Input:** parse `configure.py` for Object entries (share code with
  Tool A — extract into a small `tools/_object_table.py` module if it
  helps). Optionally also read `config/<region>/symbols.txt` to get
  function counts / sizes per TU.
- **Heuristic:** rank unmatched TUs by score, prefer:
  1. TUs whose siblings in the same directory are mostly `Matching`
     (templates next door) — weighted heavily.
  2. Smaller TUs (lower function count, smaller `.text`). If
     `symbols.txt` is too coarse to estimate `.text` size, function
     count is fine.
  3. TUs in the same module as an already-open brief (so a wave of
     sibling matches is reachable).
- **Output:**
  ```
  Suggested next targets (15):
    score=...  src/kyoshin/plugin/ocBuiltin.cpp    4 funcs  (3/12 siblings matched)
    score=...  src/kyoshin/plugin/ocThread.cpp     6 funcs  (3/12 siblings matched)
    ...
  ```
- **CLI:**
  - `python3 tools/next_targets.py` — top 15 across the project.
  - `python3 tools/next_targets.py --module src/kyoshin` — scoped.
  - `python3 tools/next_targets.py --limit 50` — show more.
  - `python3 tools/next_targets.py --json` — machine-readable.

## Non-scope

- **Do not modify `configure.py`'s Object table** — that's decomper's
  lane, and your tools only *read* it.
- **Do not touch `src/`** — same reason.
- **Do not touch CLAUDE.md, AGENTS.md, docs/state.md** — those are
  brain's. If your tools surface a structural issue with the Object
  table that's worth documenting, flag it in the PR body and let
  brain pick it up in a follow-up.
- **Do not build a UI / dashboard.** CLI output only. Markdown
  rendering for a README badge can come later.
- **Do not depend on packages outside the stdlib.** Python 3.11+,
  `argparse`, `ast`, `pathlib`, `json`, `dataclasses` are all fine.
  `configure.py` itself is stdlib-only.

## Success criteria

- [ ] `tools/match_stats.py` exists, runs cleanly, exits 0 on this
      repo.
- [ ] `tools/next_targets.py` exists, runs cleanly, exits 0.
- [ ] Both scripts run end-to-end on `cntrl-alt-lenny`'s clone
      *without* needing `compilers/`, `orig/`, or `build/` to be
      populated. (Cloud cannot verify this from a cloud session —
      brain will verify on the local machine during PR review.)
- [ ] Both scripts have a `--json` mode that round-trips through
      `json.loads` cleanly.
- [ ] `tools/match_stats.py` agrees with the day-1 counts in
      [`docs/state.md`](../state.md): 217 / 115 / 833 (within
      whatever the table state is at the time you read it).
- [ ] If you add shared code, it lives in `tools/_object_table.py`
      (leading underscore = internal). Don't widen the public tool
      surface unless explicitly briefed.
- [ ] Code is `ruff`-clean: `python3 -m ruff check tools/`.

## What cloud verifies vs. what brain verifies

Cloud verifies (no baserom needed):

- `python3 tools/match_stats.py` runs and prints sensible numbers.
- `python3 tools/next_targets.py` runs and prints a ranked list.
- `--json` modes parse back.
- Numbers from Tool A match a manual `grep -c` against
  `configure.py` — sanity check.
- `ruff` clean on the new scripts.

Brain verifies on the local machine after the PR lands:

- `python3 tools/match_stats.py` agrees with `python3 configure.py
  progress` for the TU-count line (after a build has populated
  `report.json`).
- `next_targets.py`'s top picks are real, unmatched, and the sibling
  counts look right under spot-check.

## PR

- **Branch:** `cloud/progress-and-targets`
- **Push to:** `fork` remote (`cntrl-alt-lenny/xenoblade`), not
  `origin`. See [`AGENTS.md § PRs and the fork remote`](../../AGENTS.md#prs-and-the-fork-remote).
- **PR title:** "tools: match_stats.py + next_targets.py" or similar.
- **PR body must include:**
  - **Summary** — one paragraph.
  - **What changed** — bullets (`tools/match_stats.py` added,
    `tools/next_targets.py` added, `tools/_object_table.py` added if
    you split shared code).
  - **Test plan** — what you ran (`python3 tools/match_stats.py`,
    `python3 tools/next_targets.py`, `ruff`), with sample output.
  - **What needs brain's local check** — explicit list (cross-
    reference against `python3 configure.py progress`).
  - **Scope** — one line: `tools/` only, no `src/`, no `configure.py`
    Object table changes.

## Notes for the cloud session

- `configure.py` is large (~100KB). Don't try to read the whole file
  in one go to RAM for parsing — `ast.parse` on a Path is fine, or
  read once and use the resulting AST.
- The Object call shape you're looking for is roughly:
  ```python
  Object(Matching, "kyoshin/plugin/pluginMath.cpp", mw_version="Wii/1.0a")
  Object(NonMatching, "kyoshin/plugin/ocBuiltin.cpp")
  Object(MatchingFor("jp"), "kyoshin/plugin/something.cpp")
  ```
  The status arg is the first positional. The path is the second
  positional. Keyword args (`mw_version`, `extra_cflags`) are
  optional and not relevant to either tool.
- The path is relative to `src/` for game code and to repo root for
  some library code — keep it as a string, don't try to resolve it.
- For `next_targets.py`'s "sibling matched" score, group by
  `os.path.dirname(path)` over the parsed list — same directory ⇒
  siblings. Module is just the first 1–2 components of the path
  (`src/kyoshin/plugin` ⇒ module `kyoshin/plugin`).
