# Decomp workflow — plain-language guide

A walking tour of how this project actually gets built, aimed at
anyone who is new to decompilation or to "vibe coding" with AI
agents. For the full technical spec see `CLAUDE.md`; for agent
coordination see `AGENTS.md`; for what's in flight right now see
`docs/state.md`.

## What we're trying to do

Rebuild Xenoblade Chronicles from C source code, byte-for-byte identical to
the original ROM.

That phrase — "byte-for-byte identical" — is the whole game. If the
rebuilt ROM's SHA-1 matches the original dump, every function has
been perfectly reconstructed. If a single byte differs, the SHA-1 is
totally different. There's no "almost matching".

So the project is a long series of small wins: match one function,
commit, match the next, commit, until the whole ROM is in C source
and the hashes line up.

## The cast

Three AI agents, one human. Each has a narrow job.

| Agent | Where it lives | What it does |
|---|---|---|
| **cntrl_alt_lenny** | meatspace | You. Sets priorities, picks direction, merges PRs. |
| **brain** | local LLM session (Claude Code or Codex CLI), PC or Mac | Reviews and merges PRs. Runs the build / diff / check commands locally to verify each PR doesn't break the build. Writes task briefs. Keeps `AGENTS.md` / `docs/state.md` current. |
| **decomper** | local LLM session (separate from brain) | The actual decomper. Matches individual functions. Writes C source in `src/`. Renames symbols. |
| **scaffolder** | LLM session without local toolchain (Claude web, Codex web) | Scaffolder and reviewer. Writes tools (`tools/`), library headers (`libs/`), docs. Can't run the build, so delegates verification to brain. |

Why the split? Matching a function is a focused, iterative task (one
person on one function at a time). Tool-building is parallel work
that doesn't need the baserom. Reviewing PRs needs a local build to
verify. Separating those three roles keeps everyone unblocked.

## The matching loop

This is the core of the project. Skipping ahead: if you can picture
one function being matched end to end, you understand the whole flow.

1. **Pick.** The decomper consults the project's "next target" tool
   for the worklist — unmatched functions sorted easiest-first — or
   follows a brief (`docs/briefs/NNN-*.md`) that already picked the
   target.

2. **Context.** They look at callers, callees, and data refs with the
   project's context-bundler / callsite tool — so they know what role
   the function plays in the larger picture.

3. **Draft C.** They write `src/<module>/<name>.c` with their best
   guess at the original source.

4. **Build.** The project's build command (typically `ninja` or
   `make`) runs the compiler + linker and rebuilds the ROM.

5. **Diff.** The project's diff tool runs the byte-level comparison.
   The diff TUI shows instruction-by-instruction where the rebuild
   differs from the baserom.

6. **Iterate.** If there's a diff, the decomper tweaks the C (maybe
   change `int` to `unsigned short`, reorder a loop, move a local
   variable declaration) and re-runs. Most matches take 2-20 rounds.

7. **Mark complete.** Once the diff says 100%, the decomper edits the
   project's TU-tracking file to add the "complete" marker under that
   TU's header.

8. **Rename.** The project's rename-symbol tool swaps the
   delinker-generated placeholder name for the real name.

9. **Commit + PR.** Commit the new `.c` file plus the symbol /
   delinks changes. Push to a `decomper/*` branch. Open a PR.

10. **Review + merge.** Brain reviews, runs the project's module /
    consistency check to confirm no module regressed, and merges.

Now repeat until the rebuilt ROM hashes equal the original.

## Local setup extras (optional but recommended)

If your project ships a `.githooks/` directory with a pre-push
hook (e.g. running a match-invariants validator), enable it once
per clone:

```bash
git config core.hooksPath .githooks
# Or use the project's installer script if one exists.
```

### Claude Code hooks (if you run Claude Code)

`.claude/settings.json` wires three hooks that fire inside the agent
loop:

- **PostToolUse on Edit / Write / MultiEdit** →
  `.claude/hooks/post_edit.py` runs `ruff check` on any edited
  `tools/*.py` or `tests/*.py` file, then `python -m unittest
  discover -s tests` if ruff was clean. Non-blocking — surfaces
  issues in tool output so the agent can fix before committing.
- **PreToolUse on Bash** → `.claude/hooks/pre_bash.py` inspects the
  Bash command for `git push`; if it matches, optionally runs a
  project-defined pre-push command (configured via
  `DECOMP_HOOK_PREPUSH_CMD`) and BLOCKS (exit 2) on errors. Bypass
  with `SKIP_PREPUSH_HOOK=1 git push ...` or `git push --no-verify`.
- **Stop** → `.claude/hooks/save_agent_reply.py` captures the final
  assistant turn of every agent session and writes it to a shared
  inbox at `<repo-shared-git-dir>/agent-inbox/<role>-latest.md`
  (i.e. `.git/agent-inbox/` of the main clone). The brain reads
  these to see what the decomper / scaffolder said in sessions that
  didn't ship a PR — blocked-on-non-scope, research-only, aborted —
  without the human user shuttling text manually. Role is inferred
  from the worktree's basename (`brain` / `decomper` / `scaffolder`
  per the worktree-convention section of AGENTS.md). Inbox lives
  inside `.git/` so it's never version-controlled, never needs a
  gitignore entry, and travels with no per-machine setup beyond what
  the project already requires (`python3` + `git`). Non-blocking by
  design: any error exits silently.

These hooks are opt-in per Claude Code session — they only fire
when Claude Code reads `.claude/settings.json`.

## What a PR means in this setup

A pull request is just a git branch with a note attached. The flow
is:

1. An agent writes code on a branch named like `scaffolder/foo` or
   `decomper/bar`. The `<agent>/<slug>` shape is a convention so
   everyone can see at a glance who made it.
2. The agent pushes the branch and opens a PR via the GitHub API.
   This doesn't change `main`; it just says "here's a proposed
   change".
3. Brain reviews it: reads the diff, runs the project's build / diff
   / check locally to verify it doesn't break the build, summarizes
   in plain English, and either merges or asks questions.
4. You (cntrl_alt_lenny) get a summary from brain and the final say
   on controversial ones.

**No agent merges their own PRs.** That's the safety boundary. Every
change passes through brain's local verification before landing on
`main`.

## Where to dig deeper

- `CLAUDE.md` — toolchain, baserom hashes, build commands, region
  matrix; project-specific.
- `AGENTS.md` — full role manifest, branch convention, worktree
  setup, brief format.
- `docs/state.md` — what's in flight right now.
- `docs/briefs/` — the open + closed brief log.
