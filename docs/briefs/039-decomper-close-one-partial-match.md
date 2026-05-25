# 039 — Close one near-complete partial-match TU to 100%

### decomper/src

**Goal:** Pick ONE partial-match translation unit currently at ≥ 87% matched
and push it to 100.00% matched in the US build. One TU per brief — don't
spread changes across multiple.

**Top candidates** (from `build/us/report.json`, 2026-05-25 build):

| #  | Unit                                                | % matched |
|----|-----------------------------------------------------|-----------|
| 1  | `main/monolib/src/core/CPadManager`                 | 99.5%     |
| 2  | `main/nw4r/src/snd/snd_TaskManager`                 | 98.3%     |
| 3  | `main/monolib/src/device/CDeviceFileJob`            | 96.2%     |
| 4  | `main/nw4r/src/snd/snd_AxVoiceManager`              | 92.3%     |
| 5  | `main/monolib/src/device/CDeviceSC`                 | 90.3%     |
| 6  | `main/nw4r/src/snd/snd_Util`                        | 88.5%     |
| 7  | `main/RVL_SDK/src/revolution/os/OSThread`           | 88.4%     |
| 8  | `main/nw4r/src/g3d/res/g3d_resmat`                  | 87.1%     |
| 9  | `main/nw4r/src/g3d/res/g3d_resanmchr`               | 87.0%     |
| 10 | `main/RVL_SDK/src/revolution/hbm/HBMGUIManager`     | 84.7%     |

**Suggested order of attack:** Start with `#1 CPadManager` (99.5% — almost
certainly one function or one instruction away from done). If it turns out
to be stuck on something gnarly (compiler quirk, scheduling weirdness),
bail and try `#2 snd_TaskManager` (98.3%) instead. Note the bail in your PR
description so brain understands the choice.

**Scope:** `src/` (the chosen TU's `.cpp`/`.c` file only). Read-only across
`config/`, `include/`, `libs/`.

**Non-scope:** Don't touch `config/us/symbols.txt`, `splits.txt`, or
`build.sha1` — symbol renames are a separate brief lineage. Don't expand
to a second TU; if the chosen one is unfixable, report and stop.

**Success:** `ninja` reports the chosen TU at 100.00% matched in the
progress summary. `build/us/main.dol` SHA1 still
`214b15173fa3bad23a067476d58d3933ad7037b7`. PR diff is one source file,
typically one or two functions changed.

**Branch:** `decomper/<unit-slug>-100`, based off `origin/main`. Example:
`decomper/cpadmanager-100` for unit #1.

**Setup needed before starting:**

Decomper's clone needs `orig/us/` populated. The brain has already created
directory junctions for you:

- `decomper\orig\us\sys` → `brain\orig\us\sys`
- `decomper\orig\us\files` → `brain\orig\us\files`

If the junctions are missing for any reason, recreate them (no admin
needed):

```powershell
cd C:\Users\leona\Dev\xenoblade\decomper\orig\us
New-Item -ItemType Junction -Path sys -Target ..\..\..\brain\orig\us\sys
New-Item -ItemType Junction -Path files -Target ..\..\..\brain\orig\us\files
```

Then `python configure.py --version us && ninja` from `decomper\` should
build and produce `build/us/report.json` for your own iteration cycle.

**Workflow loop:**

1. Open the chosen `.cpp` in your editor and the corresponding
   `build/us/<obj>.o` in objdiff (load `objdiff.json` as the project).
2. Iterate: edit C, rebuild (single-object ninja target works), eyeball
   diff. Repeat until diff is empty.
3. Verify the full DOL hash is unchanged after your change:
   `python -c "import hashlib;
   print(hashlib.sha1(open('build/us/main.dol','rb').read()).hexdigest())"`
   — should match `214b15173fa3bad23a067476d58d3933ad7037b7`.
4. Commit, push, open PR cntrl-alt-lenny:`decomper/<unit-slug>-100` →
   cntrl-alt-lenny:`main` (NOT to upstream — this is internal coordination).

Brain reviews, builds, and merges.
