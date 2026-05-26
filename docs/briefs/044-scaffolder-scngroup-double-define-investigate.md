# 044 — scaffolder/scngroup-double-define-investigate

**Goal:** Confirm whether the `__vt__Q34nw4r3g3d8ScnGroup` double-define in `build/us/asm/` (flagged by the decomper in PR #44's notes) is a stale-asm artifact from the pre-PR-#43 splits.txt state, or a real symbol-table issue. Then document the recovery so other agents don't trip on it.

## Context

While running wave 2 of vtable renames (PR #44), the decomper found `lbl_eu_80569648` mapped to `__vt__Q34nw4r3g3d8ScnGroup` — but that name already exists in `config/us/symbols.txt`. They skipped the collision. Investigating, they noticed the vtable's `.obj` block appears in **two different asm files** under `build/us/asm/`:

  - `nw4r_data.s` — the pre-PR-#39 catch-all file name
  - `nw4r_datab.s` — the post-PR-#39 carve target

Most likely cause: `dtk`'s asm-regeneration leaves stale `.s` files behind when split boundaries shift, and the build never cleans them up. The actual `config/us/symbols.txt` is consistent (each symbol defined once); the symbol table for the live build is correct. But the asm tree on disk has dead `.s` files that can mislead readers — including the decomper's vtable detector, which walks `build/us/asm/**/*.s` to find `.obj` blocks.

## Scope

- `build/us/asm/` — read-only inspection and (if confirmed stale) cleanup.
- `AGENTS.md` — add a "Stale build/<region>/asm/" troubleshooting note under a relevant section (or create one).
- `tools/suggest_symbol_name.py` — *optional* defensive update: have the detector warn or skip when it finds the same `.obj` block in multiple `.s` files (current behavior silently uses whichever it sees first, which can produce confusing suggestions).

## Non-scope

- Don't try to fix `dtk` itself (that's an upstream tool).
- Don't touch `config/`.
- Don't rebuild the asm tree as part of the brief — just document the recovery so the decomper / other agents can run it themselves.

## Suggested workflow

1. Inspect `build/us/asm/`:

   ```sh
   ls build/us/asm/ | grep -E 'nw4r_data'
   grep -rE '^\.obj.*ScnGroup' build/us/asm/ | head -5
   ```

   Confirm both `nw4r_data.s` (stale) and `nw4r_datab.s` (current) contain the `.obj` block.

2. Confirm the recovery works:

   ```sh
   rm -rf build/us/asm/
   python configure.py --version us && ninja
   shasum -a 1 build/us/main.dol
   ```

   - SHA-1 must stay `214b15173fa3bad23a067476d58d3933ad7037b7`.
   - After the rebuild, the stale `nw4r_data.s` should not return.
   - Re-grep to confirm `ScnGroup` is defined exactly once.

3. Document in `AGENTS.md` under whatever section covers
   troubleshooting / common pitfalls. Suggested content: a short
   "If you see a symbol defined twice in `build/<region>/asm/`,
   that's a stale-asm artifact from a previous splits.txt
   configuration; `rm -rf build/<region>/asm/ && ninja` restores
   sanity. SHA-1 is unaffected — the live build uses the
   current splits.txt." with a one-line pointer to this brief
   for context.

4. *Optional* (only if step 1 confirms the double-define): add a
   defensive check in `tools/suggest_symbol_name.py` that warns
   when `_find_definition_asm` finds the same `.obj` in multiple
   `.s` files. Print to stderr; don't error out. Same module as
   the brief 040 detector — small surgical addition.

## Success

- AGENTS.md has a troubleshooting note covering the stale-asm pattern.
- Either step 4 lands, OR a one-line explanation in the PR why it's not needed.
- SHA-1 stays `214b15173fa3bad23a067476d58d3933ad7037b7`.
- If the recovery doesn't work as expected (e.g., the double-define persists post-rebuild), bail and report — don't widen scope.

## Branch

`scaffolder/scngroup-double-define-investigate`
