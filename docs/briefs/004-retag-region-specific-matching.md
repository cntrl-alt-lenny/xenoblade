### decomper/retag-region-specific-matching

**Goal:** Fix three `configure.py` Object entries that are tagged
`Matching` but actually only ship in a subset of regions, so their
status reflects reality and matches the
[CLAUDE.md](../../CLAUDE.md#project-conventions) convention.

> Drafted by scaffolder while implementing brief 003 (region-aware
> match stats; delivered via brain coordination message rather than a
> markdown file). Flag for brain review before decomper picks up. The
> drift root cause is documented in that PR's body.

## Background

`configure.py`'s `Object(Matching, ...)` is supposed to mean "matches in
every region we build" (the canonical CLAUDE.md says: *only three values
— `Matching`, `NonMatching`, or `MatchingFor("<region>")`*). The
build's *actual* region scope, however, lives in
`config/<region>/splits.txt` — a TU is included in region X's build if
and only if it has a header in `config/X/splits.txt`.

Today three entries are tagged `Matching` but their splits-membership
contradicts that:

| Path                                                       | Current status | Ships in | Reality          | Tag bug |
|------------------------------------------------------------|----------------|----------|------------------|---------|
| `PowerPC_EABI_Support/src/MSL_C/MSL_Common/assert.c`       | `Matching`     | `jp`     | JP-only TU       | should be `MatchingFor("jp")` |
| `RVL_SDK/src/revolution/enc/encjapanese.c`                  | `Matching`     | `jp`     | JP-only TU       | should be `MatchingFor("jp")` |
| `RVL_SDK/src/revolution/enc/encunicode.c`                   | `Matching`     | `eu`, `us` | EU/US-only TU  | should be `MatchingFor("eu", "us")` |

The build links these correctly today because splits.txt excludes them
from the wrong-region builds, but human readers (and tools that read
status without cross-referencing splits.txt) get a misleading picture.
`tools/match_stats.py --region` already handles this — but the
in-source comments `#JP only` / `#EU/US only` are doing the job that
the status arg ought to be doing.

`Matching` semantically means "matches in every region this TU links
into" — so `Matching` *with* a region-specific splits scope is not
strictly wrong, just redundant and confusing. `MatchingFor("jp")` is
the project-canonical way to say it.

## Scope

Three single-line edits to [`configure.py`](../../configure.py):

```diff
-            Object(Matching, "PowerPC_EABI_Support/src/MSL_C/MSL_Common/assert.c"), #JP only
+            Object(MatchingFor("jp"), "PowerPC_EABI_Support/src/MSL_C/MSL_Common/assert.c"),

-            Object(Matching, "RVL_SDK/src/revolution/enc/encunicode.c"), #EU/US only
+            Object(MatchingFor("eu", "us"), "RVL_SDK/src/revolution/enc/encunicode.c"),

-            Object(Matching, "RVL_SDK/src/revolution/enc/encjapanese.c", shift_jis = False, extra_cflags=["-enc UTF8"]), #JP only
+            Object(MatchingFor("jp"), "RVL_SDK/src/revolution/enc/encjapanese.c", shift_jis = False, extra_cflags=["-enc UTF8"]),
```

(The trailing `#JP only` / `#EU/US only` comments can stay or go — the
new status arg makes them redundant. Suggest dropping them.)

## Non-scope

- **Do not** retag any `NonMatching` entries — those have correct
  semantics already (an unmatched TU in a region it doesn't ship in is
  still "not matched"). Cosmetic comment cleanup on entries like
  `CriWare/src/adx/adxt/adx_dcd3.c` (JP-only, no comment) is fine as
  drive-by but not required.
- **Do not** touch `splits.txt` for any region — those are the build
  ground truth and reflect the real region scope correctly.
- **Do not** add a new `MatchingFor("eu", "us")`-style multi-region
  scope handler to the Object class — `MatchingFor(*versions)` in
  `configure.py:415` already accepts varargs, so the multi-region
  call in `encunicode.c` works out of the box.

## Success criteria

- [ ] Three `Object(Matching, ...)` entries flipped to the
      appropriate `MatchingFor(...)` form.
- [ ] `ninja --version jp` still passes the SHA-1 gate.
- [ ] `ninja --version eu` still passes the SHA-1 gate.
- [ ] `ninja --version us` still passes the SHA-1 gate (the
      `encunicode.c` change is the load-bearing one — it has to remain
      matched for EU/US, not silently switch to NonMatching).
- [ ] `python3 tools/match_stats.py --cross-check
      build/jp/report.json` PASSes on `complete_units`.
- [ ] Same for `build/us/report.json` and `build/eu/report.json` once
      built.

## What this fixes downstream

After the retag, `python3 tools/match_stats.py` (without `--region`)
will count:
- `Matching` drops from 218 → 215.
- `MatchingFor(jp)` rises from 115 → 117.
- `MatchingFor(eu)` rises from 0 → 1.
- `MatchingFor(us)` rises from 0 → 1.

The `Total matched any` is unchanged (218 + 115 = 333 → 215 + 117 + 1 + 1
= 334; the `encunicode.c` was double-counted before because `Matching`
implied "every region" but it doesn't ship in JP — net +1).

And `match_stats.py --region <r>` will give identical answers
to today's splits-intersection logic, since the splits-based scope is
the ground truth either way.

## PR

- **Branch:** `decomper/retag-region-specific-matching`
- **Push to:** `fork` remote, PR base = `main` (this is a real
  matching-status change, upstreamable).
- **PR body must include:**
  - Per-region `ninja` SHA-1 confirmation (all three regions).
  - `match_stats.py --cross-check` output before and after the change
    (must remain PASS).
  - Mention the cosmetic comment drop on any of the three lines.

## Notes

- The third entry (`encjapanese.c`) carries two extra kwargs
  (`shift_jis = False, extra_cflags=["-enc UTF8"]`); preserve those
  verbatim — they're load-bearing for the JP build.
- `MatchingFor("eu", "us")` is the project's existing multi-region
  spelling; `MatchingFor(*("eu", "us"))` also works but is less
  readable.
