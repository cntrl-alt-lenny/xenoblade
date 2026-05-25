# Decomp Briefs

Short, scoped task descriptions for individual decomp efforts.
Each brief lives in its own file (`NNN-<slug>.md`).

A brief is a short spec the brain writes for another agent. It pins
down scope, success criteria, and the branch convention so the agent
can pick it up cold without re-discovering context.

## Format

```
### <agent-slug>/<scope>

**Goal:** one sentence describing what's being built.
**Scope:** files / directories this task may touch.
**Non-scope:** explicit "don't touch these".
**Success:** how we'll know it's done (tests pass / PR merges cleanly / etc).
**Branch:** suggested branch name following the AGENTS.md convention.
```

## Briefs

<!-- Brain maintains this index manually or via a generator tool.
     Format: "| NNN | [`<slug>`](NNN-<slug>.md) | <one-line goal> |" -->

| #   | Brief | Goal |
|-----|-------|------|
