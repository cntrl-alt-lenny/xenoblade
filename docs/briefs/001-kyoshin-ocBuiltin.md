### decomper/kyoshin-ocBuiltin

**Goal:** Match `kyoshin/plugin/ocBuiltin.cpp` byte-for-byte against the
US baserom so its entry in [`configure.py`](../../configure.py) can be
flipped from `Object(NonMatching, …)` to `Object(MatchingFor("us"), …)`.

This is the project's smallest unmatched TU in `kyoshin/plugin/`: 4
functions, 356 bytes of `.text` total. Chosen as the **first decomper
brief** for this repo because the surrounding plugin/ siblings are
already matched (drafting templates available right next door).

## Scope

- **Create** `src/kyoshin/plugin/ocBuiltin.cpp` (does not exist yet).
- **Create** `src/kyoshin/plugin/ocBuiltin.hpp` if a header is needed
  to expose `ocBuiltinRegist()` to `pluginMain.cpp` (which already
  calls it — see *Drafting templates* below).
- **Edit** `configure.py`: flip the existing
  `Object(NonMatching, "kyoshin/plugin/ocBuiltin.cpp")` entry to
  `Object(MatchingFor("us"), "kyoshin/plugin/ocBuiltin.cpp")` **only
  after** `ninja` passes the SHA-1 gate with the new source in place.
- `config/us/symbols.txt`: only touch if you derive better names for
  any of the four placeholder symbols (`isExistProperty`,
  `isExistSelector`, `getOCName`, `ocBuiltinRegist` — see below).
  These names already look correct; renames likely unnecessary.

## Non-scope

- Anything in `tools/`, `libs/`, `include/`, or `configure.py`'s
  top-level structure — that's cloud's territory.
- Sibling unmatched plugin TUs (`ocThread.cpp`, `ocMsg.cpp`,
  `ocBdat.cpp`, `ocUnit.cpp`, `ocCfp.cpp`, etc.) — follow-up briefs.
- JP / EU regions — match US only. Brain will scope the multi-region
  follow-up after the US match is in.
- `AGENTS.md`, `CLAUDE.md`, `docs/state.md` — brain's territory.

## Target functions

All in `.text` between `0x8003A58C` and `0x8003A6F0` (US build):

| Symbol            | Address      | Size       | Scope  |
|-------------------|--------------|------------|--------|
| `isExistProperty` | `0x8003A58C` | 0x7C (124) | global |
| `isExistSelector` | `0x8003A608` | 0x7C (124) | global |
| `getOCName`       | `0x8003A684` | 0x60  (96) | global |
| `ocBuiltinRegist` | `0x8003A6E4` | 0x0C  (12) | global |

`isExistProperty` and `isExistSelector` are exactly the same size —
probably the same shape over different lookup tables. Match one,
the other should fall out by templating.

`ocBuiltinRegist` at 12 bytes is one BL + epilogue or similar — trivial
glue, but confirm it doesn't inline before flipping the Object.

## Drafting templates

All in `src/kyoshin/plugin/`, all already matched:

- [`pluginMain.cpp`](../../src/kyoshin/plugin/pluginMain.cpp) — calls
  `ocBuiltinRegist()` directly on line 21, alongside `pluginGameRegist()`
  / `pluginDebRegist()` / `ocBdatRegist()` / etc. Shows the surrounding
  registry shape and the include pattern (`#include
  "kyoshin/plugin/plugins.hpp"` + per-module header).
- [`pluginPad.cpp`](../../src/kyoshin/plugin/pluginPad.cpp),
  [`pluginMath.cpp`](../../src/kyoshin/plugin/pluginMath.cpp),
  [`pluginDeb.cpp`](../../src/kyoshin/plugin/pluginDeb.cpp),
  [`pluginWait.cpp`](../../src/kyoshin/plugin/pluginWait.cpp) — small
  "plugin" TUs, same registry-glue shape as the target.

The "oc" prefix appears across the engine (`ocBdatRegist`,
`ocThreadRegist`, …) — likely "object class" in Monolithsoft's SB
scripting-VM convention.

## Naming hypotheses

(For reference — `config/us/symbols.txt` already names these
plausibly, so don't rename unless objdiff or surrounding code
suggests a clearer fit.)

- `isExistProperty(name)` → bool, checks if a property name is
  registered in some property table.
- `isExistSelector(name)` → bool, same shape over a selector table.
- `getOCName(handle)` → returns a string name for an "OC" handle
  (small enough to be a simple table lookup or two-line accessor).
- `ocBuiltinRegist()` → 12-byte registration entry, called from
  `pluginRegist()` in `pluginMain.cpp`.

## Success criteria

- [ ] `src/kyoshin/plugin/ocBuiltin.cpp` (and `.hpp` if needed) exists,
      compiles cleanly under default mwcc Wii/1.1 flags.
- [ ] `python configure.py --version us && ninja` passes the SHA-1 gate
      (`build/us/main.dol: OK`).
- [ ] objdiff against `build/us/obj/kyoshin/plugin/ocBuiltin.o` shows
      0% diff on all four functions.
- [ ] `configure.py` updated: `NonMatching → MatchingFor("us")`.
- [ ] Project-wide match counter moves up by 1 TU + 4 functions
      (`python configure.py progress`).

## PR

- **Branch:** `decomper/kyoshin-ocBuiltin`
- **PR title:** "Match kyoshin/plugin/ocBuiltin.cpp (US)" or similar.
- **PR body must include:**
  - The 4 symbols flipped, old size → new size (should all match).
  - Confirmation that `ninja` SHA-1 gate is green for the US build.
  - Note that JP/EU matching is intentionally not in scope for this
    PR — separate follow-up.

## Notes for the decomper session

- The TU has no `extra_cflags=` on its `Object(...)` entry, so default
  mwcc Wii/1.1 codegen applies. Don't add cflags unless objdiff says so.
- If `ocBuiltinRegist` inlines into `pluginRegist` instead of staying
  separate, the symbol will disappear from the link map — you'll need
  to keep it `extern` or mark with the project's "do not inline" macro
  (check `include/macros.h` for an existing one).
- The matched plugin/ siblings show that this codebase uses raw
  function definitions (not classes) for the plugin registry layer.
  Don't wrap these in a class.
- Before flipping the Object entry, double-check that the SHA-1 gate
  still passes when you run `ninja` cleanly from a `make clean`-ish
  state (`rm -rf build && python configure.py && ninja`). A flipped
  TU that quietly relies on stale `.o` is the classic regression
  vector.
