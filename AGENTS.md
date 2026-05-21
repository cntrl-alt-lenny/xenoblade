# AGENTS.md — who's working on what

Coordination manifest for every AI agent contributing to this decomp
(Claude, Codex, future ones). **Every agent reads this before starting
work** and updates it when their scope changes.

For humans: this is a plain-English map of which agent owns which parts
of the repo, so two agents don't edit the same file and clobber each
other's work. cntrl_alt_lenny edits it indirectly by telling the "brain"
agent in plain English — see *Adding or retiring agents* near the bottom.

## Active agents

| Slug              | Where it runs                                                                             | Role                                                                                                                                                                                   | Owns these paths                                               | Hands-off paths                                                                 |
|-------------------|-------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------|---------------------------------------------------------------------------------|
| **cntrl_alt_lenny** | meatspace                                                                                 | Human project owner. Sets priorities, picks direction, merges PRs, adds/retires agents, final authority.                                                                              | —                                                              | —                                                                               |
| **brain**         | Any LLM session (Claude Code, Codex CLI, …) on cntrl_alt_lenny's PC or Mac, with toolchain + baserom | **Coordinator.** Runs `ninja` locally to verify PRs, maintains this file + `docs/state.md`, writes task briefs, reviews incoming PRs, decides the next task. **Default on every PR: review locally → summarize in plain English to cntrl_alt_lenny → offer to merge → execute on OK.** Self-merges autonomously when cntrl_alt_lenny is AFK, flagging in the PR body. | `AGENTS.md`, `CLAUDE.md`, `docs/briefs/`, `docs/state.md`      | `src/`, `tools/`, `libs/`, `include/`, `config/<ver>/symbols.txt`, `configure.py` Object table |
| **cloud**         | Any LLM session without local toolchain access (Claude web, Codex web, …) — OR local without baserom | **Scaffolder & reviewer.** Writes tools, library headers, surveys, research; reviews PRs via GitHub MCP integrations. Cannot run local builds, so delegates verification to brain.     | `tools/`, `libs/` (header expansion), `include/`               | `src/`, `config/<ver>/symbols.txt`, `configure.py` Object table, `AGENTS.md` (proposes via PR; brain merges) |
| **decomper**      | Any LLM session on cntrl_alt_lenny's PC or Mac, with toolchain + baserom (separate session from brain) | Primary decomper. Matches individual TUs against the baserom, writes C/C++ source, flips `Object(NonMatching, ...)` to `Object(Matching, ...)` in `configure.py` as functions match. Renames placeholder symbols in `config/<ver>/symbols.txt`. | `src/`, `config/<ver>/symbols.txt`, `configure.py` Object entries (status + extra_cflags + mw_version per-TU only) | `tools/`, `libs/`, `include/`, `AGENTS.md`, top-level `configure.py` structure  |

Extend this table when a new agent joins; see *Adding or retiring
agents* below.

### Claude Code subagent configs

The three role definitions are also shipped as Claude Code subagent
files under `.claude/agents/`:

- [`.claude/agents/brain.md`](.claude/agents/brain.md) — coordinator
- [`.claude/agents/decomper.md`](.claude/agents/decomper.md) — function matcher
- [`.claude/agents/cloud.md`](.claude/agents/cloud.md) — scaffolder

Each file captures the role's scope + hands-off paths + workflow loop
so a fresh Claude Code session can load the appropriate subagent
(`/agents` picker, or `Task({ subagent_type: "brain" })` from a
parent session) instead of re-discovering the conventions from
AGENTS.md cold. The subagent specs are derived from this file — if
you change the owns/hands-off columns here, update the matching
`.claude/agents/*.md` too (and vice versa).

### Why the brain runs locally (PC or Mac), not on a cloud session

The brain needs to actually execute `ninja`, `python configure.py
progress`, etc. to verify that incoming PRs don't regress the build.
Web/cloud LLM sessions don't have the baserom or the toolchain, so
they can *design* work and *review diffs* but can't *prove the
build still matches*. Putting the brain on a local machine means
one session can both decide and verify, which is the difference
between coordinating and guessing.

### Slugs are roles, not LLM providers

**Any** LLM session that meets a slot's *Where it runs* requirement
can take that slot. Claude Code, Codex CLI, future Gemini / GPT /
whatever sessions can all take any role. The slug is the **role**,
not the **model**. When cntrl_alt_lenny opens a chat and says
*"you are the decomper"*, that session becomes `decomper` for as long
as it's the one working the role.

Handoff is stateless. Whichever local session has the toolchain
installed, a current `orig/<region>/` extract, and has read this
file + `docs/state.md` is the active `brain` for that stretch; the
next one can pick up from there.

### Brain onboarding on a fresh machine

If you're a brand-new `brain` session starting cold on a PC or Mac
that has never built this repo, do these one-time steps before you
touch any PR. cntrl_alt_lenny will typically say something like *"you
are the brain, review everything"* — that's your cue to run this
checklist. Works the same regardless of which LLM (Claude Code,
Codex CLI, etc.) is backing the session.

1. **Be at the repo root.** `git clone https://github.com/xbret/xenoblade`
   then `cd` into it, or `cd` into an existing clone.
2. **Sync with GitHub.** `git fetch origin && git pull --ff-only`.
3. **Extract the baserom.** Use Dolphin Emulator to extract your own
   legitimate copy of the game to `orig/jp/` (or `orig/eu/` /
   `orig/us/`). Keep at minimum `sys/main.dol` and `files/rels/*.rel`.
   The expected `main.dol` SHA-1 per region is in
   [`CLAUDE.md`](CLAUDE.md). Ask cntrl_alt_lenny to share their
   extract from a machine that already has the right hash — don't
   re-rip if you can avoid it; ripper-version drift causes hash
   mismatches.
4. **Install Python deps.** Python 3.11+ required. No `requirements.txt`
   in the repo yet — Python stdlib only at the moment.
5. **Configure.** `python configure.py` (defaults to `jp`). Generates
   `build.ninja`, downloads `dtk` and `objdiff-cli` if missing.
6. **First build.** `ninja`. Auto-downloads the mwcc compilers if
   `compilers/Wii/1.1/` (and friends) are missing. Takes a few
   minutes on first run.
   - **macOS prerequisite**: Game Porting Toolkit Wine cask. Apple
     Silicon also needs Rosetta 2. See
     [`CLAUDE.md`](CLAUDE.md#platform-notes).
7. **Confirm the baseline.** `ninja` verifies the rebuilt main.dol
   against `config/jp/build.sha1`. Green = ready.
8. **Read [`docs/state.md`](docs/state.md)** and tackle whatever the
   *Next-brain TODO* section lists. If `docs/state.md` doesn't exist
   yet, write it: scope what's `Matching` vs `NonMatching`, identify
   1–3 starter targets, list open briefs (none yet — this is day 1).

Afterwards, your loop is: fetch, read `docs/state.md`, review any open
PRs (`gh pr list --state open`), verify them locally (`python
configure.py && ninja`), merge or comment, update `docs/state.md`,
write briefs for cntrl_alt_lenny to paste to other agents, repeat.

### Worktree convention (multi-agent on the same machine)

When `brain`, `decomper`, and `cloud` are running on the same physical
machine (the common case for cntrl_alt_lenny's setup), **they must
work in separate git worktrees** so they don't fight over branch
state in the same working directory. Two equivalent mechanisms exist;
either is fine — pick by host:

#### Mechanism A — manual sibling worktrees (Mac convention)

Standard layout, three sibling directories at the same depth:

| Worktree path                          | Slug      | Purpose                                                                                                  |
|----------------------------------------|-----------|----------------------------------------------------------------------------------------------------------|
| `~/Dev/xenoblade`                      | `brain`   | Main repo. Brain pulls main, reviews PRs, runs build verifications here.                                |
| `~/Dev/xenoblade-decomper`             | `decomper`| Sibling worktree. Decomper checks out its own `decomper/<scope>` branches without touching brain's working state. |
| `~/Dev/xenoblade-cloud`                | `cloud`   | Sibling worktree. Cloud checks out its own `cloud/<scope>` branches the same way.                       |

Add the sibling worktrees once per machine:

```sh
git worktree add --detach ~/Dev/xenoblade-decomper
git worktree add --detach ~/Dev/xenoblade-cloud
cp -r ~/Dev/xenoblade/orig/jp/* ~/Dev/xenoblade-decomper/orig/jp/  # after Dolphin extract
cp -r ~/Dev/xenoblade/orig/jp/* ~/Dev/xenoblade-cloud/orig/jp/
```

Each worktree gets its own copy of the gitignored extracted files
under `orig/<region>/`, and its own `build/` directory. The `.git`
is shared via worktree mechanics, so commits/branches are visible
across all three — but working-tree state (modified files, untracked
files, current checkout) is isolated.

The sibling worktrees start in detached HEAD state. When a session
starts work, it creates a branch:

```sh
cd ~/Dev/xenoblade-decomper
git checkout -b decomper/<scope>
```

#### Mechanism B — Claude Code automatic sandbox worktrees (Windows convention)

Claude Code on Windows (or anywhere) automatically creates a
per-session sandbox worktree inside `.claude/worktrees/<auto-name>/`
each time an agent session is launched. These provide identical
isolation to the manual sibling worktrees above — decomper and
cloud each get their own checkout of their working branch,
independent of brain's main working state. No manual `git worktree
add` needed.

Both mechanisms achieve the same isolation goal. Pick by host
convention:

- **Mac:** Mechanism A (manual sibling worktrees).
- **Windows:** Mechanism B (Claude Code automatic sandbox worktrees).

Brain does not strictly need either mechanism for review/merge work
on its own — both mechanisms only matter when decomper and cloud
run in parallel.

## PRs and the fork remote

This repo lives at [`xbret/xenoblade`](https://github.com/xbret/xenoblade).
cntrl_alt_lenny does **not** own that repo — he contributes via a
personal fork at
[`cntrl-alt-lenny/xenoblade`](https://github.com/cntrl-alt-lenny/xenoblade).

Every local clone on cntrl_alt_lenny's machines should have two git
remotes set up:

| Remote   | URL                                       | Purpose                                          |
|----------|-------------------------------------------|--------------------------------------------------|
| `origin` | `https://github.com/xbret/xenoblade.git`  | Upstream. **Pull** from here; never push.        |
| `fork`   | `https://github.com/cntrl-alt-lenny/xenoblade.git` | The user's fork. **Push** branches here. |

Verify with `git remote -v`. If `fork` is missing, add it:

```sh
git remote add fork https://github.com/cntrl-alt-lenny/xenoblade.git
```

### How a PR flows

1. Branch off `origin/main`:
   `git checkout -b decomper/<scope> origin/main`
   (or `cloud/<scope>` / `brain/<scope>`).
2. Commit work locally.
3. Push to the **fork**, not origin:
   `git push -u fork decomper/<scope>`.
4. Open a PR from `cntrl-alt-lenny:<branch>` → `xbret:main`:
   `gh pr create --repo xbret/xenoblade --base main --head cntrl-alt-lenny:<branch>`.
   `gh` will figure out the head automatically once the branch is
   pushed; the explicit `--head` form above is the unambiguous
   spelling.
5. After upstream merges, delete the fork-side branch:
   `git push fork --delete <branch>` and `git branch -d <branch>`
   locally.

### Listing PRs

- **Upstream open PRs** (what brain reviews):
  `gh pr list --repo xbret/xenoblade --state open`.
- **Fork-side draft PRs** (rare; only if the user opens a self-review
  PR against their fork): `gh pr list --repo cntrl-alt-lenny/xenoblade
  --state open`.

`gh pr list` with no `--repo` defaults to whichever remote the current
branch is tracking, which can surprise you — always be explicit when
checking PR state.

### Brain's merge command, fork-aware

Brain merges by approving + merging the upstream PR after
cntrl_alt_lenny's OK:

```sh
gh pr merge <N> --repo xbret/xenoblade --squash --delete-branch
```

`--delete-branch` removes the branch on the fork side as part of the
merge — saves a separate `git push fork --delete` step.

## PR conventions

- **Branch names:** `decomper/<kebab-scope>` for matches,
  `cloud/<kebab-scope>` for tools/libs/docs, `brain/<kebab-scope>`
  for coordination updates.
- **One concern per PR**: one match or coherent wave of sibling
  matches; one tool or one focused tool set; one coordination
  update.
- **Decomper PR body** must include:
  - Which TU(s) were flipped from `NonMatching` to `Matching` (or
    `MatchingFor("<region>")`).
  - Confirmation that `ninja` still passes the SHA-1 gate for every
    region the change touches.
  - Match progress delta: before/after counts.
- **Cloud PR body** must include:
  - Test plan section: what cloud verified locally (unit tests,
    ruff, smoke tests against `config/`), and explicit list of what
    brain needs to verify with a local build.
- **Brain reviews → cntrl_alt_lenny → merges.** Decomper and cloud
  never self-merge except in a production fire (see below).

## Production-fire spot authority

When `ninja` regresses from a known-green baseline and blocks every
downstream PR, the agent who can produce the fix may self-merge it
without waiting. Scope: production fires only, never feature work.
Flag in the PR body as "self-merged per AGENTS.md § spot authority"
with the urgency rationale.

## Adding or retiring agents

cntrl_alt_lenny adds or retires agents by telling the **brain** in
plain English ("add a permuter agent that does X", "retire cloud,
we're folding its scope into decomper"). The brain then:

1. Edits the *Active agents* table above.
2. Edits the matching `.claude/agents/*.md` subagent file (or adds
   a new one).
3. Updates `docs/state.md` to note the change.
4. Commits + opens a PR. cntrl_alt_lenny reviews and merges.

Never edit AGENTS.md directly as decomper or cloud — propose via PR
and let brain merge.

## Open briefs

- [`001-kyoshin-ocBuiltin`](docs/briefs/001-kyoshin-ocBuiltin.md) —
  decomper. Smallest unmatched kyoshin/plugin TU (4 fns, 356 bytes
  `.text`). First decomper brief; matched plugin/ siblings nearby for
  templates.
- [`002-cloud-progress-and-targets`](docs/briefs/002-cloud-progress-and-targets.md) —
  cloud. Two no-baserom-needed tools: a static match counter that
  reads `configure.py` directly, and a next-targets picker that
  surfaces small unmatched TUs next to matched siblings. First cloud
  brief.
