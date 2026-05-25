# 041 — Retry the `g3d_anmclr.cpp` flip (US: NonMatching → Matching)

### decomper/libs

**Goal:** Flip `libs/nw4r/src/g3d/g3d_anmclr.cpp` from NonMatching to
Matching for the US region. The previous attempt (cycle-20 Stream B
in PR #38) was blocked on a multi-define in `nw4r_data.o`; that
blocker was cleared by PR #39's splits.txt carve.

**Why now:** PR #39 (just merged) split `nw4r_data.s` into
`nw4r_dataa.s` + `nw4r_datab.s` and gave `g3d_anmclr.cpp` its own
exclusive ranges for `.rodata` / `.data` / `.sdata` / `.sdata2`
(JP-pattern-following carve). The TYPE_NAME constants and vtables
that the source needs are now uniquely owned by g3d_anmclr.cpp's
slot, so the flip should compile + link cleanly. PR #39 verified
SHA-1 stays green with the carve in place.

**File:** [`libs/nw4r/src/g3d/g3d_anmclr.cpp`](../../libs/nw4r/src/g3d/g3d_anmclr.cpp)
(decomp territory by convention — `libs/` matching work goes through
decomper even though the directory tree is scaffolder's structurally).

**Scope:** `libs/nw4r/src/g3d/g3d_anmclr.cpp`, plus `configure.py` if
the flip requires changing the object's `Object(NonMatching, ...)`
→ `Object(Matching, ...)` line. Read-only across everything else.

**Non-scope:** Don't touch `config/us/symbols.txt` (renames are a
separate brief). Don't touch other libs/nw4r/g3d files. If the flip
fails for a reason that isn't the previous multi-define, bail and
report what blocks now — don't widen scope.

**Success:**
- `g3d_anmclr.cpp` reports 100.00% matched in US ninja progress
  summary.
- `build/us/main.dol` SHA1 still
  `214b15173fa3bad23a067476d58d3933ad7037b7`.
- One source file flipped from NonMatching to Matching in
  `configure.py` (or the object table file the project uses).
- PR diff: one source file + one configure line.

**Branch:** `decomper/g3d-anmclr-flip-us`, based off `origin/main`.

**Setup:** Your worktree has the baserom junctioned in at
`orig/us/sys/main.dol` (SHA1 verified). Run
`python configure.py --version us && ninja` to bootstrap the build
cache, then iterate with objdiff (`objdiff.json` generated on first
build).

**Workflow loop:**
1. Open `libs/nw4r/src/g3d/g3d_anmclr.cpp` in your editor + the
   corresponding `build/us/.../g3d_anmclr.o` in objdiff.
2. Confirm the diff shape is consistent with the carve assumption —
   PR #39's `.rodata` / `.data` / `.sdata` / `.sdata2` ranges should
   now be owned exclusively by this TU.
3. If the donor source (from SS or NSMBW per the user's external-source
   tools) compiles + links + matches, flip the configure entry and
   open the PR.
4. If it doesn't match, capture the diff in the PR body and stop —
   brain will scope a follow-up.

Brain will rebuild on the PR branch and verify both the per-TU 100%
and the DOL hash.
