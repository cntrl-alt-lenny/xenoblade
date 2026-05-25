# State of play

Churn-heavy brain log. Split out of `AGENTS.md` so the manifest stays
stable while this file turns over every working chunk.

The brain updates this file at the end of every session so the next
brain (possibly on a different machine or LLM) can catch up in under
a minute. Keep it short. If you're the brain reading this cold:
`git log --oneline -20` and the open-PR list fill in whatever this
misses.

**Last updated:** 2026-05-25. Brain on Windows 11 PC (`C:\Users\leona\Dev\xenoblade\brain`). US build green @ SHA1 `214b15173fa3bad23a067476d58d3933ad7037b7`; framework freshly committed (`b556c8b`); briefs 038 + 039 dispatched.

## Headline

The three-agent decomp framework (`.claude/`, `AGENTS.md`, `CLAUDE.md`,
`docs/`) is now committed to `origin/main` so `git clone` on a new
machine pulls the workflow ready-to-go. US RVZ extracted, US build
verified at expected SHA1. First tracked-in-repo briefs (038, 039)
dispatched to scaffolder + decomper.

## Baseline gate (what every PR must preserve)

- `python configure.py --version us && ninja` builds clean.
- `build/us/main.dol` SHA1 stays `214b15173fa3bad23a067476d58d3933ad7037b7`.
- No new warnings beyond the known one (sjiswrap on
  `include/functions.hpp` — see brief 038 for the fix-in-flight).

(JP and EU baselines TBD — baserom not yet extracted for those regions.)

## Today's merges (just-landed)

- `b556c8b` Install three-agent decomp framework. Layers
  `decomp-agent-framework` on top of the fork; updates `.gitignore`
  to ship framework files with the fork; documents the
  upstream-PR-safe `branch off upstream/main` convention; adds
  `CLAUDE.md`.

## In flight (post this brain-PR)

- **Brief 038** (scaffolder): investigate `include/functions.hpp`
  Shift-JIS warning. No PR yet.
- **Brief 039** (decomper): close one partial-match TU to 100%.
  No PR yet.

## Next-brain TODO

1. Review the next two incoming PRs (one each from scaffolder and
   decomper). Run the build, verify the SHA1, summarise in plain
   English for cntrl_alt_lenny, offer to merge.
2. After brief 039 lands, look at `build/us/report.json` again and
   dispatch the next decomp target. The 99.5% / 98.3% / 96.2% units
   are the top-of-queue.
3. Consider whether to extract JP / EU regions next, or push
   further on US. cntrl_alt_lenny's call.

## Cross-machine handoff notes

- **Toolchain:** Native Windows + ninja + Python 3.12.10. No WSL.
  `wibo` v1.0.0-beta.5 auto-downloaded by `configure.py`.
- **DolphinTool location** (used for RVZ extraction):
  `C:\Users\leona\Games\Dolphin\DolphinTool.exe`. The `-g` flag
  outputs to a `DATA/` subfolder that must be flattened (move
  `DATA/sys` and `DATA/files` up to the output root) before the
  build will find the files.
- **Baserom:** USA only, at `brain/orig/us/`. `decomper/orig/us/`
  is junctioned to brain's (sys + files). scaffolder doesn't need
  the baserom (toolchain-free role).
- **Upstream remote:** Configured in each clone as
  `https://github.com/xbret/xenoblade.git`. Must be re-added on
  fresh clones — remotes don't ship with the repo.
- **Open warning:** sjiswrap fires on `include/functions.hpp`. Not
  fatal; brief 038 is investigating.
