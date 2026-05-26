# 043 — decomper/vtable-rename-wave-2

**Goal:** Use the newly-landed vtable-shape detector (PR #42, `tools/suggest_symbol_name.py` vtable signal) to find and rename a second wave of vtable placeholders in `config/us/symbols.txt`. Target 10–25 renames, all at Tier-1 (confidence 1.00).

## Context

PR #42 added a vtable-shape signal to `suggest_symbol_name.py` that emits `__vt__<class>` at confidence 1.00 when a `.data` block matches MWCC's vtable layout (typeinfo ptr + `__dt__<class>Fv` destructor + member function pointers). The destructor entry gives the canonical class mangling directly — no reader-side voting needed.

PR #38 renamed 22 vtables manually (decomper inspected `.data` shapes by hand). The new tool should automate that for any remaining unnamed vtables.

There are still many `lbl_eu_*` placeholders in `.data` sections that are likely vtables but weren't part of PR #38's batch. Find them, run the tool, validate the suggestions look right, commit the symbols.txt edits.

Independent of brief 042 — that's a splits.txt fix in a different file.

## Scope

- `config/us/symbols.txt` (placeholder renames only).
- Use `tools/suggest_symbol_name.py --region us <lbl>` on each candidate.

## Non-scope

- Don't touch `src/`, `libs/`, `include/`.
- Don't touch `config/jp/` or `config/eu/` (no baseroms).
- Don't try to flip owning TUs to Matching — that's a different cycle.
- Don't rename non-vtable placeholders this round (other signal types — adjacency, directory-vote — are out of scope; PR #38 already handled them where they had high confidence).
- Don't reorder lines in `symbols.txt` — pure name substitutions only.

## Suggested workflow

1. Find unnamed `.data` placeholders with size in the `[0x14, 0xA0]` range that are typical vtable sizes. Quick filter:

   ```sh
   grep -E '^lbl_eu_[0-9A-F]+ = \.data:.*size:0x[0-9A-F]+' config/us/symbols.txt \
       | grep -vE 'size:0x([0-9A-Fa-f]{3,})' \
       | head -100
   ```

   (or use whatever batch-listing helper feels natural — the above is just a starting point.)

2. Pipe each candidate through `tools/suggest_symbol_name.py --region us <lbl>`. Top-1 vtable-signal hits at confidence 1.00 are paste-ready.

3. Skip:
   - Suggestions with confidence < 1.00 (non-vtable fallthrough — out of scope this round).
   - Suggestions where the suggested name already exists in `symbols.txt` (collision — flag for brain to investigate).

4. Apply each accepted rename to `config/us/symbols.txt` (replace the `lbl_eu_*` form with the `__vt__<class>` form, leave the rest of the line alone).

## Success

- 10–25 vtable renames merged into `config/us/symbols.txt`.
- `build/us/main.dol` SHA-1 stays `214b15173fa3bad23a067476d58d3933ad7037b7`.
- Each rename has the `__vt__` prefix and a class mangling that follows MWCC's encoding (`Q22cf<name>`, `<n>CTTask<...>`, etc.).
- PR description lists every rename in a table with the address, the new name, and the destructor entry that confirmed the class mangling.

## Test plan

- [ ] Build clean
- [ ] SHA-1 verified
- [ ] At least 10 renames; if fewer than 10 candidates exist, list what was tried and what got rejected (helps brain decide if a follow-up rename brief is even worthwhile).

## Branch

`decomper/vtable-rename-wave-2`

## Notes for the decomper

- The first rename wave (PR #38) hand-inspected `.data` shapes for 22 entries. With the detector, you should be able to do an equivalent batch in a fraction of the time.
- If you find a vtable the detector misses (e.g., it has a `__dt__` entry but the destructor name doesn't match the detector's regex), note it in the PR — that's a tool-quality signal for the scaffolder.
- If you find more than 25 high-confidence candidates, cap at 25 and queue the rest for a future cycle — keeping PR diffs reviewable matters more than maxing out renames per cycle.
