# CLAUDE.md — Xenoblade Chronicles decomp project context

This file gives any Claude Code session (and any other LLM agent) the
project-specific context needed to make a meaningful contribution.
Read it before doing anything. The role split (brain / decomper /
scaffolder) lives in [AGENTS.md](AGENTS.md) — read that too to know
which role you're acting in.

## Project

This is a fork of [xbret/xenoblade](https://github.com/xbret/xenoblade)
— a work-in-progress **matching decompilation** of *Xenoblade Chronicles*
for the Wii. Goal: a byte-identical rebuild of the original DOL across
all three regions (JP / EU / US).

The fork (`cntrl-alt-lenny/xenoblade`) layers the
[decomp-agent-framework](https://github.com/cntrl-alt-lenny/decomp-agent-framework)
on top of upstream so multiple LLM sessions can coordinate without
clobbering each other. The decomp work itself is identical to upstream;
the framework is purely coordination.

## Toolchain

- **MWCC Wii/1.1** — primary linker version.
- Specific objects also compile under `GC/3.0a5.2`, `Wii/1.0a`, and
  `Wii/1.0` — see `configure.py` for the per-object mapping
  (`Object(... mw_version=...)`).
- SDK HBM define: `20090303` for JP, `20100224` for EU/US — set
  automatically based on `--version`.
- Build wraps Windows tooling via [wibo](https://github.com/decompals/wibo)
  v1.0.0-beta.5 (auto-downloaded by `configure.py`).

## Regions and expected hashes

| Region | `configure.py` flag      | Expected `main.dol` SHA1                   |
|:------:|--------------------------|--------------------------------------------|
| JP     | `--version jp` (default) | `a564033aee46988743d8f5e6fdc50a8c65791160` |
| EU     | `--version eu`           | `10d34dbf901e5d6547718176303a6073ee80dda2` |
| US     | `--version us`           | `214b15173fa3bad23a067476d58d3933ad7037b7` |

When opening a brief or PR for a function, mention which regions it
matches in (some objects use `MatchingFor()` to mark single-region
matches).

## Baserom setup

The repo does **not** contain game assets. You need an extracted copy
of the game on disk:

```
orig/<region>/
├── sys/main.dol          # required
└── files/rels/*.rel      # required for .rel matching
```

Other extracted files (`opening.bnr`, `apploader.img`, …) can be
deleted to save space — only `sys/main.dol` and `files/rels/*.rel`
are needed by the build.

**Extraction**: open the ISO/RVZ in Dolphin Emulator (right-click →
*Properties* → *Filesystem* → right-click root → *Extract Entire
Disc…*) and point it at `orig/<region>/`. Or use the
[`DolphinTool`](https://wiki.dolphin-emu.org/index.php?title=DolphinTool)
CLI if you have it.

## Build commands

From any clone (`brain/`, `decomper/`, `scaffolder/`):

```sh
python configure.py [--version us]    # writes build.ninja for the region
ninja                                  # actually builds
```

Drop `--version` to default to JP. First successful build also writes
`objdiff.json`; once that exists, drive function-by-function matching
with the [objdiff](https://github.com/encounter/objdiff) GUI.

**The brain's job** (per `AGENTS.md`) is to actually run `ninja` and
confirm the produced `build/<region>/main.dol` SHA1 matches the table
above before merging any PR. Treat the hash as the truth — don't
declare a function "matched" without verifying the full-DOL hash
still lines up.

## PR convention: upstream vs fork

This fork carries framework files (`.claude/`, `AGENTS.md`, `docs/`)
that upstream doesn't have and isn't asking for. **When you intend
the work to land in `xbret/xenoblade` upstream, branch off
`upstream/main` instead of `origin/main`:**

```sh
git fetch upstream
git checkout -b <fix-foo> upstream/main
# work, commit
git push -u origin <fix-foo>
# on GitHub: open PR cntrl-alt-lenny:<fix-foo> → xbret:main
```

That keeps the framework files out of the upstream diff so the
maintainer sees only the actual decomp change. Each clone already
has the upstream remote configured:

```sh
git remote -v
# origin    https://github.com/cntrl-alt-lenny/xenoblade.git
# upstream  https://github.com/xbret/xenoblade.git
```

If the work is fork-only (e.g. framework changes, vibe-coder docs,
local tooling), branching off `origin/main` is fine.

## Per-role ownership (quick reference)

Full table in `AGENTS.md`. Summary:

- **brain** — `AGENTS.md`, `CLAUDE.md`, `docs/briefs/`, `docs/state.md`
- **decomper** — `src/`, `config/<region>/` (renames + TU completion),
  `assets/`
- **scaffolder** — `tools/`, `libs/`, `include/`

Don't edit outside your role's paths without coordinating via the
brain. Cross-role changes go through PR + brain review.

## Where things live

- `src/` — decompiled C source (decomper's primary working area).
- `include/`, `libs/` — headers + library code (scaffolder's).
- `config/<region>/` — `symbols.txt`, `splits.txt`, `build.sha1` per
  region.
- `tools/` — project-specific helper scripts (scaffolder's).
- `orig/<region>/` — extracted baserom (gitignored).
- `build/` — ninja output (gitignored).
- `objdiff.json` — generated diff config (gitignored).

## Working with cntrl_alt_lenny

The human running this is a hobbyist vibe-coder — does this on
weekends, doesn't write C directly. The decomper agent writes the C;
the brain's job is to translate "did this PR work?" into plain
English. When summarising a build result, lead with whether the DOL
hash matched — that's the headline. The rest (compiler warnings,
function diffs) is supporting detail.

Defer to cntrl_alt_lenny on direction and priority. Self-merge only
when explicitly AFK and the change is low-risk (see `AGENTS.md` §
"brain self-merge protocol").
