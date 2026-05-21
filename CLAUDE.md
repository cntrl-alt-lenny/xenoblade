# CLAUDE.md — Xenoblade Chronicles decomp

Matching decompilation of *Xenoblade Chronicles* for the Nintendo Wii.
Goal: a byte-identical executable (main.dol + .rel modules) rebuilt
from C/C++ source, verified via SHA-1.

## Regions

| Version | `--version` | main.dol SHA-1                           | Status |
|---------|-------------|------------------------------------------|--------|
| JP      | `jp`        | `a564033aee46988743d8f5e6fdc50a8c65791160` | primary build target |
| EU      | `eu`        | `10d34dbf901e5d6547718176303a6073ee80dda2` | secondary |
| US      | `us`        | `214b15173fa3bad23a067476d58d3933ad7037b7` | secondary |

`configure.py` defaults to `jp`. Pass `--version eu` or `--version us`
to build a different region. All three can coexist under `build/`.

The user must supply their own dump; `orig/<region>/` (gitignored)
holds the extracted files. Only `sys/main.dol` and `files/rels/*.rel`
are needed — the rest can be deleted to save space.

## Toolchain

| Tool          | Version       | Notes                                                                |
|---------------|---------------|----------------------------------------------------------------------|
| `mwcc`        | `Wii/1.1`     | Default. Set in `ProjectConfig.linker_version` in `configure.py`.    |
| `mwcc`        | `Wii/1.0a`    | Per-TU override for some `RVL_SDK` files (see `mw_version=` kwargs). |
| `mwcc`        | `GC/3.0a5.2`  | Per-TU override for older `RVL_SDK` files (e.g. `OSUtf.c`, `wenc.c`).|
| `mwld`        | `Wii/1.1`     | Linker, ships with mwcc.                                             |
| `dtk`         | latest        | https://github.com/encounter/decomp-toolkit — auto-downloaded.       |
| `objdiff-cli` | latest        | https://github.com/encounter/objdiff — auto-downloaded.              |
| Ninja         | any recent    | Build driver.                                                        |
| Python        | 3.11+         | Match-statement and PEP 604 unions used in tools.                    |
| `wibo`        | latest        | Linux only; runs the Win32 `.exe` compilers.                         |
| Wine          | GPTK on macOS | `brew install --cask Gcenx/wine/game-porting-toolkit` (Apple Silicon needs Rosetta 2). |

`tools/download_tool.py` fetches `dtk` and `objdiff-cli` automatically on
the first `ninja` run. Compilers must be in `compilers/<mw_version>/` —
either provided via `--compilers` to `configure.py` or auto-located.

## Quick start

```bash
# 1. Put a Dolphin-extracted dump at orig/<region>/, keeping at minimum
#    sys/main.dol and files/rels/*.rel. We never ship ROMs.

# 2. Generate build.ninja for your version
python configure.py            # defaults to --version jp

# 3. Build everything; ninja verifies the rebuilt main.dol against the
#    SHA-1 in config/<version>/build.sha1
ninja
```

If the rebuilt SHA-1 mismatches `config/<version>/build.sha1`, the
build fails loudly. No skip.

## Matching workflow

```
edit src/<module>/<file>.cpp
 │
 ▼
ninja                          # compile + link + verify
 │
 ▼
objdiff (GUI/TUI)              # open against objdiff.json at repo root
 │
 ▼
python configure.py progress   # aggregate match progress
```

A translation unit is "matching" when its `Object(...)` entry in
`configure.py` is changed from `NonMatching` to `Matching` (or
`MatchingFor("<region>")` if it only matches in one region). The
build fails the SHA-1 check if a `Matching` TU produces wrong bytes,
so flipping the flag is the commitment that the file is byte-identical
in the corresponding `.o`.

Practical loop:

1. Pick an unmatched TU from the `configure.py` Object table (currently
   332 matching / 833 non-matching for `jp` — see *Progress* below).
2. Write C++ in the existing `src/<module>/<file>.cpp` (Object entries
   already exist for every TU; non-matching ones have placeholder code
   that links but doesn't byte-match).
3. `ninja` — if the SHA-1 still passes, you're matching. If it fails
   on this TU, the diff is in `build/<version>/.../that.o`.
4. Open objdiff against `objdiff.json` to see the instruction-level diff.
5. Iterate until the diff is empty.
6. Edit `configure.py` to flip the Object's status to `Matching` (or
   `MatchingFor("jp")` if it only matches the JP build).
7. Re-run `python configure.py && ninja` — the SHA-1 gate is now armed
   against that TU. If it still passes, the match is locked in.

`ninja`'s final SHA-1 verification is the only test that matters at the
project level: if the rebuilt main.dol hashes equal to the baseline,
every `Matching` TU is byte-identical.

## Project conventions

- **Language**: C++ default (`.cpp`). C (`.c`) used in vendored libs
  (`RVL_SDK`, `PowerPC_EABI_Support`, `NdevExi2A`, parts of `CriWare`).
- **Source layout**:
  - `src/` — game code, organized by module (`src/kyoshin/`,
    subdirectories per subsystem like `src/kyoshin/cf/`,
    `src/kyoshin/plugin/`, `src/kyoshin/action/`).
  - `libs/` — vendored / SDK code, one directory per library:
    `RVL_SDK`, `nw4r`, `monolib`, `CriWare`, `NdevExi2A`,
    `PowerPC_EABI_Support`.
  - `include/` — project-wide headers (`types.h`, `macros.h`,
    `compat.h`, `decomp.h`, etc.).
- **Symbols**: rename in `config/<region>/symbols.txt`. Convention:
  `ClassName::methodName` (C++ mangling preserved) or `funcName` for C.
- **Object status**: only three values — `Matching`, `NonMatching`, or
  `MatchingFor("<region>")` for region-specific matches.
- **Per-TU compiler overrides**: `mw_version="Wii/1.0a"` (or similar)
  as a kwarg on `Object(...)` when a specific TU was built with an
  older mwcc. Don't change `ProjectConfig.linker_version` globally
  unless you mean to.
- **Extra cflags**: `extra_cflags=["-O4,s", "-func_align 4"]` etc. on
  specific Objects when the original TU used non-default flags.
- **Do not commit**: extracted ROM files (`orig/*/*` covered in
  `.gitignore`), `*.dol`, `*.rel`, `*.elf`, `*.o`, `*.map`, `build/`,
  downloaded tool binaries, `objdiff.json` (regenerated).

## Current progress

- **JP**: 332 matching / 833 non-matching TUs (~28%). Tracked live by
  the `Object(...)` table in `configure.py`. `python configure.py
  progress` aggregates.
- **EU / US**: TUs that match in JP usually need separate verification
  per region; `MatchingFor("jp")` marks ones that don't yet match
  EU / US.
- See `docs/state.md` (created by brain after the first review pass)
  for current in-flight work.

## Platform notes

- **macOS (Apple Silicon)**: install the
  [Game Porting Toolkit cask](https://github.com/Gcenx/homebrew-wine)
  for the Win32 runner —
  `brew install --cask Gcenx/wine/game-porting-toolkit` — and
  Rosetta 2. `configure.py` auto-detects `wine` from `PATH`.
- **Linux**: `wibo` is auto-downloaded and runs the Win32 compilers.
- **Windows**: `mwcc.exe` / `mwld.exe` run natively; no runner.

## Reference projects

- This repo follows the **decomp-toolkit** template
  ([encounter/decomp-toolkit](https://github.com/encounter/decomp-toolkit))
  — same `configure.py` shape, same `Object(Matching, ...)` /
  `Object(NonMatching, ...)` matching convention, same Ninja rules.
- Sibling projects using the same template are useful for cross-reference
  when an unfamiliar mwcc PPC pattern shows up.
