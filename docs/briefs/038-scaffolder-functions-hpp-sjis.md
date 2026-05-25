# 038 — Investigate `include/functions.hpp` Shift-JIS warning

### scaffolder/include

**Goal:** Determine whether the `sjiswrap: ... contains Shift JIS encoding
errors` warning emitted on `include/functions.hpp` during a US build is a
real encoding bug or a false-positive from `sjiswrap`. If real, fix it.

**Context:** Every US build emits this on stderr:

```
sjiswrap: File C:\Users\leona\Dev\xenoblade\brain\include\functions.hpp contains Shift JIS encoding errors
```

The file is 24 lines / 871 bytes of placeholder C++ declarations wrapped in
`extern "C"` (see commit `a10ebbc`, brief 010). No obvious Shift-JIS string
literals or comments. The warning may be a real encoding artefact, or
`sjiswrap` may be misidentifying line endings / BOM / something benign.

**Scope:** `include/functions.hpp` (read + edit). Read-only across `tools/`,
`libs/`, `src/`, `config/`.

**Non-scope:** Don't refactor unrelated headers. Don't rename any of the
`func_<addr>` placeholder symbols — those move out as decomper renames them
(brief 010's lineage), not here.

**Success:** Brain runs `python configure.py --version us && ninja`. The
`sjiswrap` warning no longer fires on `include/functions.hpp`. Built
`build/us/main.dol` still SHA1s to
`214b15173fa3bad23a067476d58d3933ad7037b7`. PR diff is one file, small.

**Branch:** `scaffolder/fix-functions-hpp-sjis-warning`, based off
`origin/main` (this is a framework-side fix, not an upstream-bound change).

**Investigation hints:**
1. Dump the file's raw bytes (PowerShell: `Format-Hex
   .\include\functions.hpp`). Look for bytes in 0x81-0x9F or 0xE0-0xEF that
   aren't followed by a valid Shift-JIS trail byte (0x40-0x7E or 0x80-0xFC).
2. If the file is genuinely pure ASCII, check for a UTF-8 BOM (`EF BB BF`
   at offset 0) — `sjiswrap` may not strip that.
3. Check line endings: build is on Windows, file may have been touched on a
   Unix machine (LF) or vice versa.
4. If the warning turns out to be a `sjiswrap` quirk that can't be fixed
   from the header side, document the finding in the PR description — that's
   a legitimate outcome and the brain will close the brief as "investigated,
   no fix needed."

**Verification note for scaffolder:** You can't run the build (toolchain-free
role). After committing, push and open a PR. Brain will run the build, check
the warning, verify the hash, and merge or request changes.
