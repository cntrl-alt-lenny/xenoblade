# 040 — Detect vtable shape in `tools/suggest_symbol_name.py`

### scaffolder/tools

**Goal:** Extend `tools/suggest_symbol_name.py` to recognise the
classical MWCC vtable shape directly from `.data` contents and emit
`__vt__<mangled-class>` as a Tier-1 (confidence 1.00) suggestion,
bypassing the directory-vote heuristic that misfired during the
cycle-20 rename wave.

**Why now:** PR #38's body flagged this as the top scaffolder feedback
item:

> "`suggest_symbol_name.py` could detect vtable shape (.data, size
> 0x14-0xA0, first .4byte points to .rodata RTTI label, middle entry
> is a `__dt__`...`Fv` symbol) and emit `__vt__<mangled-class>`
> directly, bypassing directory-vote misdirection."

In that wave, 21 of 22 renames were vtables, but the directory-vote
suggester returned misleading hints (CArtsSet/CBattery/CMenuFade at
0.91) because most reader TUs sit in unrelated directories. The
decomper had to inspect `.data` shape by hand to pick the right
class. Automating that saves the manual step on future rename waves.

**Scope:** `tools/suggest_symbol_name.py` (primary). Tests under
`tests/` if you add a unit test for the shape detector. Read-only
across `src/`, `config/`, `libs/`, `include/`.

**Non-scope:** Don't refactor the existing directory-vote scorer —
add the vtable-shape detector as a separate, higher-confidence
branch that fires *before* directory-vote when the shape matches.
Don't change the command-line interface (existing callers should
keep working).

**Success:**
- Vtable-shape detection fires on the 21 vtables from PR #38 and
  returns the right `__vt__<mangled-class>` name at confidence 1.00.
- Existing tests still pass: `python -m unittest discover tests` (or
  the project's equivalent — check `AGENTS.md` if unsure).
- Linter clean: `python -m ruff check tools/suggest_symbol_name.py`
- A short demo in the PR body showing one or two vtable detections
  end-to-end (input .data range → predicted name).

**Branch:** `scaffolder/vtable-shape-detection`, based off
`origin/main` (not upstream — this is fork-side tooling).

**Detection algorithm (cribbed from PR #38's hint):**
1. `.data` range, size between 0x14 and 0xA0.
2. First `.4byte` points to a `.rodata` label that looks like an RTTI
   table (typeinfo-shaped: class-name string nearby).
3. At least one entry midway is a `__dt__<class>Fv` symbol (the
   class's destructor).
4. If all three hold, the symbol name to emit is
   `__vt__<mangled-class>` where `<mangled-class>` matches the
   destructor's class portion.

**Verification note for scaffolder:** You can't run `ninja`
(toolchain-free). For the tests + linter you can run Python locally.
For "does the detector produce the right name on real data," brain
can run it against the cycle-20 inputs and confirm in the PR review.
