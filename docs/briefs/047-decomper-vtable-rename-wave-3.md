# 047 — decomper/vtable-rename-wave-3

**Goal:** Third wave of vtable renames in `config/us/symbols.txt` using PR #42's detector + PR #45's defensive warn. Target 25 renames from the ~264 remaining vtable-shape candidates.

## Context

Two waves landed already:
- **Wave 1 (PR #38)**: 21 vtables hand-inspected (pre-detector).
- **Wave 2 (PR #44)**: 25 vtables auto-detected at confidence 1.00 (first production use of brief 040's detector).

PR #44 reported ~264 candidates remain in the pool. Detector behavior was 25/25 perfect in wave 2 — no false positives.

You've been on `g3d_anmclr` work for cycles 19–23. Time for a different lane. Wave 3 gives you a clean, bounded, high-volume win that doesn't depend on brief 046 landing first (different files entirely).

## Scope

- `config/us/symbols.txt` (placeholder renames only).
- Use `tools/suggest_symbol_name.py --region us <lbl>` per candidate.
- Take the top-1 vtable-signal hits at confidence 1.00 only.

## Non-scope

- Don't touch `config/jp/`, `config/eu/`, `src/`, `libs/`, `include/`, `tools/`.
- Don't try to flip owning TUs to Matching.
- Don't rename non-vtable placeholders (other signal types are out of scope this round).
- Don't act on PR #45's stderr "multi-definition warn" if it fires — that's a stale-asm artifact, not a real collision. Run `rm -rf build/us/asm/ && ninja` first to clear leftovers, per AGENTS.md Troubleshooting.

## Suggested workflow

1. Sanity-check the asm tree is clean (after last cycle's churn, worth a precautionary clean):

   ```sh
   rm -rf build/us/asm/
   python configure.py --version us && ninja
   shasum -a 1 build/us/main.dol  # confirm baseline
   ```

2. Pick 25 vtable-shape candidates from the catch-all splits. PR #44 hinted that monolib's `CDevice*` / `CLib*` family is rich; nw4r and CriWare are also under-renamed.

3. Run the detector on each. Accept top-1 vtable-signal hits at confidence 1.00.

4. Skip:
   - Anything below confidence 1.00.
   - Collisions (suggested name already in `symbols.txt`).
   - Stale-asm warns (precautionary clean from step 1 should prevent these).

5. Apply renames to `config/us/symbols.txt`. Verify diff is exactly `+N / -N` for N renames.

## Success

- 10–25 vtable renames merged into `config/us/symbols.txt`.
- `build/us/main.dol` SHA-1 stays `214b15173fa3bad23a067476d58d3933ad7037b7`.
- Every rename has `__vt__` prefix + valid MWCC class mangling.
- PR description lists each rename in a table (address, new name, destructor entry that confirmed it). Same format as PR #44.
- Note in PR description how many candidates remain in the pool so brain can decide whether wave 4 is worth firing.

## Test plan

- [ ] Build clean
- [ ] SHA-1 verified
- [ ] No `__vt__*` name collisions in final `symbols.txt`
- [ ] Cap at 25; if fewer than 10 high-confidence candidates exist, list what was tried and what got rejected — that helps brain decide whether the rename signal is saturating.

## Branch

`decomper/vtable-rename-wave-3`

## Notes

- The brief 044 follow-up flagged a "layout-#2 vtable" at 0x80569648 with a literal-0x0 first entry instead of typeinfo pointer. The current detector correctly rejects layout-#2, so you won't accidentally rename those. If you spot more layout-#2 candidates while sampling, note them in the PR — that's signal for a future tooling brief.
