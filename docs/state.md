# State of play

Churn-heavy brain log. Split out of `AGENTS.md` so the manifest stays
stable while this file turns over every working chunk.

The brain updates this file at the end of every session so the next
brain (possibly on a different machine or LLM) can catch up in under
a minute. Keep it short. If you're the brain reading this cold:
`git log --oneline -20` and the open-PR list fill in whatever this
misses.

**Last updated:** YYYY-MM-DD. Brain on <machine>. <one-sentence
headline of where we are: e.g. "still pre-SHA1; module check at X/Y;
matching wave N in flight">.

## Headline

<!-- One paragraph: what just landed, why it matters, what's next. -->

## Baseline gate (what every PR must preserve)

<!-- The project's "do not regress" check. Examples:
     - `ninja sha1` PASSES for all configured regions
     - module check stays at 24/27 OK
     - all `dsd check modules` passes
   Write the actual command(s) the brain runs pre-merge.
-->

## Today's merges (just-landed)

<!-- Bulleted list, most recent first.
     Format: "- **PR #NNN — <branch> / <one-line summary>.** <details>"
-->

## In flight (post this brain-PR)

<!-- Open PRs the brain hasn't merged yet, with a one-liner on each.  -->

## Next-brain TODO

<!-- What the next brain session should do first.  Keep this current —
     it's the single most-read section. -->

## Cross-machine handoff notes

<!-- Anything machine-specific or environment-specific the next brain
     needs to know. -->
