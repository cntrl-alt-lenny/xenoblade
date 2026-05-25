# AGENTS.md — who's working on what

Coordination manifest for every AI agent contributing to this decomp
(Claude, Codex, future ones). **Every agent reads this before starting
work** and updates it when their scope changes.

For humans: this is a plain-English map of which agent owns which parts
of the repo, so two agents don't edit the same file and clobber each
other's work. cntrl_alt_lenny edits it indirectly by telling the
"brain" agent in plain English — see *Adding or retiring agents* near
the bottom.

## Active agents

| Slug              | Where it runs                                                                                          | Role                                                                                                                                                                                                                  | Owns these paths                                          | Hands-off paths                                                              |
|-------------------|--------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------|------------------------------------------------------------------------------|
| **cntrl_alt_lenny** | meatspace                                                                                              | Human project owner. Sets priorities, picks direction, merges PRs, adds/retires agents, final authority.                                                                                                              | —                                                         | —                                                                            |
| **brain**         | Any LLM session (Claude Code, Codex CLI, …) on a PC or Mac, with toolchain + baserom                  | The **brain**. Coordinator. Runs the project's build / check commands to verify PRs locally, maintains this file + `docs/state.md`, writes task briefs, reviews incoming PRs, decides the next task. **Default on every PR: review locally → summarize in plain English to cntrl_alt_lenny → offer to merge → execute on OK.** Self-merges autonomously when cntrl_alt_lenny is AFK, flagging in the PR body. | `AGENTS.md`, `CLAUDE.md`, `docs/briefs/`, `docs/state.md` | `src/`, `tools/`, `libs/`, `include/`, `config/` symbol/delinks files        |
| **scaffolder**    | Any LLM session without local toolchain access (Claude web, Codex web, …)                              | **Scaffolder & reviewer.** Writes tools, library headers, surveys, research; reviews PRs via GitHub MCP integrations. Cannot run local builds, so delegates verification to brain.                                  | `tools/`, `libs/`, `include/`                             | `src/`, `config/` symbol/delinks files, `AGENTS.md` (proposes via PR; brain merges) |
| **decomper**      | Any LLM session on a PC or Mac, with toolchain + baserom (separate session from brain)                | Primary decomper. Matches individual functions against the baserom, writes C source, renames symbols as functions match.                                                                                              | `src/`, `config/` (renames + TU completion), `assets/`    | `tools/`, `libs/`, `include/`, `AGENTS.md`                                   |

Extend this table when a new agent joins; see *Adding or retiring
agents* below.

### Claude Code subagent configs

The three role definitions are also shipped as Claude Code subagent
files under `.claude/agents/`:

- [`.claude/agents/brain.md`](.claude/agents/brain.md) — coordinator
- [`.claude/agents/decomper.md`](.claude/agents/decomper.md) — function matcher
- [`.claude/agents/scaffolder.md`](.claude/agents/scaffolder.md) — scaffolder

Each file captures the role's scope + hands-off paths + workflow loop
so a fresh Claude Code session can load the appropriate subagent
(`/agents` picker, or `Task({ subagent_type: "brain" })` from a parent
session) instead of re-discovering the conventions from AGENTS.md
cold. The subagent specs are derived from this file — if you change
the owns/hands-off columns here, update the matching
`.claude/agents/*.md` too (and vice versa).

### Why the brain runs locally (PC or Mac), not on a cloud session

The brain needs to actually execute the project's build, diff, and
check commands to verify that incoming PRs don't regress the build.
Web/cloud LLM sessions don't have the baserom or the toolchain, so
they can *design* work and *review diffs* but can't *prove the ROM
still builds*. Putting the brain on a local machine means one session
can both decide and verify, which is the difference between
coordinating and guessing.

### Slugs are roles, not LLM providers

**Any** LLM session that meets a slot's *Where it runs* requirement
can take that slot. The slug is the **role**, not the **model**. When
cntrl_alt_lenny opens a chat and says *"you are the decomper"*, that
session becomes `decomper` for as long as it's the one working the
role — regardless of which LLM backs it.

Handoff is stateless. Whichever local session has the toolchain
installed, a current baserom, and has read this file +
`docs/state.md` is the active `brain` for that stretch; the next one
can pick up from there.

### Brain onboarding on a fresh machine

If you're a brand-new `brain` session starting cold, do these
one-time steps before you touch any PR. cntrl_alt_lenny will
typically say something like *"you are the brain, review everything"*
— that's your cue to run this checklist.

1. **Be at the repo root.** Clone the project then `cd` into it, or
   `cd` into an existing clone.
2. **Sync with GitHub.** `git fetch origin && git pull --ff-only`.
3. **Drop the baserom in place.** Place the baserom file at the path
   `CLAUDE.md` specifies, with the SHA-1 it pins.
4. **Install project deps.** Follow `CLAUDE.md`'s "Quick start" /
   prerequisites section.
5. **Run the project's configure / build commands** to verify the
   baseline.
6. **Read [`docs/state.md`](docs/state.md)** and tackle whatever the
   *Next-brain TODO* section lists.

Afterwards, your loop is: fetch, read `docs/state.md`, review any
open PRs (`gh pr list --state open`), verify them locally, merge or
comment, update `docs/state.md`, write briefs for cntrl_alt_lenny to
paste to other agents, repeat.

### Worktree convention (multi-agent on the same machine)

When `brain`, `decomper`, and `scaffolder` are running on the same
physical machine (the common case), **they must work in separate git
worktrees** so they don't fight over branch state in the same working
directory. Two equivalent mechanisms exist; either is fine — pick by
host:

#### Mechanism A — manual sibling worktrees (Mac convention)

Standard layout, three named sibling directories under a single
project parent:

| Worktree path                                  | Slug         | Purpose                                                                  |
|------------------------------------------------|--------------|--------------------------------------------------------------------------|
| `~/Dev/xenoblade/brain`                  | `brain`      | Main repo (owns `.git/`). Brain pulls main, reviews PRs, builds verifications. |
| `~/Dev/xenoblade/decomper`               | `decomper`   | Sibling worktree. Decomper checks out its own `decomper/<scope>` branches without touching brain's working state. |
| `~/Dev/xenoblade/scaffolder`             | `scaffolder` | Sibling worktree. Scaffolder checks out its own `scaffolder/<scope>` branches the same way. |

Add the sibling worktrees once per machine:

```bash
git worktree add ~/Dev/xenoblade/decomper   main
git worktree add ~/Dev/xenoblade/scaffolder main
# Copy any local-only baserom files into each sibling's expected path.
```

Each worktree gets its own copy of any local-only files (baserom,
build outputs) and its own `build/` directory. The `.git` is shared
via worktree mechanics, so commits/branches are visible across all
three — but working-tree state (modified files, untracked files,
current checkout) is isolated.

When starting a new decomper or scaffolder session, point it at the
corresponding sibling directory instead of the main clone.

#### Mechanism B — Claude Code automatic sandbox worktrees (Windows convention)

Claude Code on Windows (or anywhere) automatically creates a
per-session sandbox worktree inside `.claude/worktrees/<auto-name>/`
each time an agent session is launched. These provide identical
isolation to the manual sibling worktrees above — decomper and
scaffolder each get their own checkout of their working branch,
independent of brain's main working state. No manual `git worktree
add` needed.

Example layout that appears automatically when both agents are running:

```
~/Dev/xenoblade/brain/   (or wherever the brain checkout lives)
├── (brain main checkout — current branch + working state)
└── .claude/worktrees/
    ├── <auto-name-1>/      ← decomper's session, on decomper/<scope>
    └── <auto-name-2>/      ← scaffolder's session, on scaffolder/<scope>
```

The automatic worktrees share the main checkout's local-only files
(no copy needed) and are cleaned up when their session ends.

**Side-effect to know about:** when brain runs `gh pr merge
--delete-branch`, the local-branch cleanup can fail with *"branch X
used by worktree at .claude/worktrees/Y"* — that's harmless; the
server-side squash-merge still succeeds. The Claude Code worktree
releases the branch when its session ends.

#### Which mechanism to use

Both achieve the same isolation goal. Pick by host convention:

- **Mac / Linux:** mechanism A (manual sibling worktrees).
- **Windows:** mechanism B (Claude Code automatic sandbox worktrees)
  — no manual setup needed.

Brain does not strictly need either mechanism for review/merge work
on its own — both mechanisms only matter when decomper and scaffolder
run in parallel.

### State of play (moved)

The churn-heavy brain log — matched counts, merged PRs, in-flight
work, next-brain TODOs — lives in [`docs/state.md`](docs/state.md).
This file (AGENTS.md) is now just the role manifest and the rules;
things that change every working chunk land in `docs/state.md` so
this file stays stable and only turns over when agents, scopes, or
rules change.

The brain updates `docs/state.md` at the end of every session; a
fresh brain reads it cold to catch up in under a minute.

## Rules every agent follows

1. **Before starting any task**, run `git fetch origin` and read this
   file (top to bottom). State on disk may be behind what's on GitHub.
2. **Never push to `main` directly.** Every change is a pull request.
   The brain reviews locally, summarizes to cntrl_alt_lenny in plain
   English, and merges on OK. cntrl_alt_lenny retains veto — the
   brain's job is to make the review/merge decision easy to approve,
   not to outsource the click.
3. **One branch per task.** Branch name = `<agent-slug>/<kebab-scope>`,
   e.g. `decomper/ov011-tail-wrappers`, `scaffolder/tier-delta`,
   `brain/agents-rename`. One branch, one PR, one concern.
4. **Stay inside your "Owns" column.** If the task needs a change in
   another agent's territory, either open a PR in that agent's scope
   (as them, not you) or ask cntrl_alt_lenny / the brain to
   re-partition.
5. **Open a PR when done.** Don't merge your own PR — that's the
   brain's job (including for brain-authored PRs, on
   cntrl_alt_lenny's OK). Don't force-push. Describe in the PR body:
   what changed, why, any follow-ups.

### Scaffolder autonomous work

`scaffolder` fills idle time between briefs. Defaults:

- **May open unbriefed:** new scripts in `tools/`, improvements to
  existing analyzer scripts, CI changes, PR reviews via GitHub MCP,
  docs restructuring inside `docs/`.
- **Requires a brief first:** anything under `libs/` — header
  scaffolding drifts fast without a concrete call-site. Wait for the
  brain to scope one.
- **When unsure:** open the PR, flag it under a "Brain please confirm
  scope" heading, and **don't** request merge — the brain approves,
  rescopes, or closes.

## Branch naming

`<agent-slug>/<kebab-case-scope>` — for example:

- `scaffolder/add-sdk-headers`
- `decomper/ov011-tail-wrappers`
- `brain/agents-rename`

The slug left of `/` identifies which role owns pushes to that
branch. No-one else touches it without coordination.

## Pull-request workflow

1. Push your branch: `git push -u origin <branch>`.
2. Open a PR titled with a short summary of the change (under 70 chars).
3. PR description says: **what** changed, **why** (link the task
   brief or a sentence of context), anything the reviewer should know.
4. **Brain reviews locally** — pulls the branch, runs the project's
   verification subset, then summarizes for cntrl_alt_lenny in plain
   English: what changed, why it's safe, what's next.
   cntrl_alt_lenny doesn't need to read the diff — the summary is
   the interface.
5. **Brain offers to merge.** On cntrl_alt_lenny's OK (explicit
   "merge it" or a thumbs-up), merge with `gh pr merge <N> --squash
   --delete-branch`. When cntrl_alt_lenny is AFK, the brain
   self-merges and notes so in the PR body.
6. After merge, delete the branch. If `--delete-branch` fails from a
   worktree because `main` is checked out in the main clone, finish
   with `git push origin --delete <branch>`.

## Adding or retiring agents

cntrl_alt_lenny says, in plain English, something like:

> *"Add Codex as an agent. It'll generate SDK header declarations
> under `libs/sdk/include/`. Move that path off scaffolder."*

The brain then:

1. Adds a row to the *Active agents* table with the new slug, role,
   owned paths, hands-off paths.
2. Moves any overlapping paths off other agents so nothing is
   double-owned.
3. Opens a PR with the change. cntrl_alt_lenny merges.
4. Writes the first task brief for the new agent.

To retire or pause an agent, move the row to a new *Retired agents*
section at the bottom with a one-line note. Don't delete history.

## Task briefs

When the brain writes a task for another agent, it goes into
`docs/briefs/NNN-<slug>.md` and gets a one-line pointer here so
agents can see the open queue without opening every file. Format of
the brief itself:

```
### <agent-slug>/<scope>

**Goal:** one sentence describing what's being built.
**Scope:** files / directories this task may touch.
**Non-scope:** explicit "don't touch these".
**Success:** how we'll know it's done (tests pass / PR merges cleanly / etc).
**Branch:** suggested branch name following the convention above.
```

### Open briefs

- [040](docs/briefs/040-scaffolder-vtable-shape-detection.md) — **scaffolder**: vtable-shape detector in `tools/suggest_symbol_name.py` (PR #38 feedback item).
- [041](docs/briefs/041-decomper-g3d-anmclr-flip-retry.md) — **decomper**: retry `libs/nw4r/src/g3d/g3d_anmclr.cpp` flip (US), now unblocked by PR #39's carve.

### Closed briefs (reference)

- 038 — scaffolder: sjiswrap Shift-JIS warning on `include/functions.hpp`. **Done** via PR #40 (em dash U+2014 in comment → ASCII `--`). Warning gone, SHA1 unchanged.
- 039 — decomper: close one ≥87% partial-match TU to 100%. **Abandoned** — decomper set up the build but didn't pick a target or push. Superseded by brief 041 (different but related goal).
