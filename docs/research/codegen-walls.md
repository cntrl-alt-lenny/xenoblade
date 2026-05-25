# mwcc PowerPC Wii — codegen walls

A catalogue of recurring mwcc Wii/1.1 (and family) divergence patterns
the agents have hit while matching. Each entry has a **name**, the
**symptom** in objdiff terms, the **recipe** to write source that
emits matching code, and a **"use when"** hint.

This file is gitignored locally per the forked-project framework
convention (cycle-2 `efb9572`). Brain maintains it; decomper +
scaffolder read it when iterating on near-matches. Models its format
on spirit-caller's `docs/research/codegen-walls.md` (DS / mwcc ARM
analogue at 27+ walls); shares the entry shape so cross-references
work both ways.

Adapted from cycle-9's research subagent finding: **no existing
public taxonomy of mwcc PowerPC codegen quirks exists** across
prime / pikmin2 / tww / tp / melee / spm / mkw / brawl / ogws /
open_rvl. TWW's [`docs/regalloc.md`](https://github.com/zeldaret/tww/blob/main/docs/regalloc.md)
is the closest — recipes for fixing reg-swaps organised by
mechanical workaround, but not a named-pattern taxonomy with use-
hints. Starting this doc as our reference now; expect to grow it
across the next 20-30 cycles as decomper hits new patterns.

> **Convention.** Wall names use the `PPC-N` prefix. Spirit-caller's
> ARM walls use `C-N`. Where a PPC wall has a direct ARM analogue,
> cross-reference. Where a wall is PowerPC-specific (region branches,
> vtable + anon-ns, etc.), note "no ARM analog".

## Walls

### PPC-1 — String-length cascade (CBattery)

**Symptom in objdiff:** a chain of `addi r?, r30, imm` instructions
referencing strings in `.rodata` are off by a constant byte count
(typically 2-4 bytes, the difference between two string-literal
lengths). The first divergent `addi` sets the cascade; every
subsequent string-load from that base register propagates the offset
delta.

**Root cause:** a source string literal has a different length from
the baserom's string. mwcc concatenates string literals into a single
`.rodata` block in source-declaration order, so a 2-byte length
change shifts every later string's offset.

**Recipe (when length differs by region):**

```cpp
// JP has "/menu/Battery.arc" (18 bytes), US/EU has "menu/jp/Battery.arc" (20 bytes).
mFileHandle = CDeviceFile::readFile(CWorkThreadSystem::getWorkMem(),
#if defined(VERSION_JP)
    "/menu/Battery.arc",
#else // EU/US: assets live under menu/jp/ (mirrors the pattern in main.cpp)
    "menu/jp/Battery.arc",
#endif
    this, 0, 0);
```

**Recipe (when same literal differs between source and disasm):**

If the literal length is wrong project-wide (not a region thing),
just match it to the disasm. Look for clues:
- File path conventions in sibling matched TUs.
- Quote literals in upstream parent projects (open_rvl, mkw, brawl).

**Use when:** objdiff shows a chain of off-by-constant `addi` from
the same base register, all referencing `.rodata` symbols. The
first divergent instruction is your starter; every following one is
collateral.

**ARM analog:** spirit-caller C-2 (string-literal layout drift).

**First hit:** cycle 7, `src/kyoshin/CBattery.cpp` (decomper PR #13).

### PPC-1 sub-pattern: "Cascade from missing functions" (added cycle 12)

**Symptom:** same as PPC-1 (off-by-N-bytes `addi`-from-rodata chain
in a near-match function).

**Root cause distinction:** *not* a region-conditional literal.
The source defines *fewer functions* than the baserom in the same
TU. Missing functions' string literals are absent from the
source's `@stringBase0`, shifting all later string offsets upward
by exactly the missing-literal byte count. mwcc pools every TU's
string literals in one `@stringBase0` in source-declaration order,
so missing siblings = missing strings = downstream cascade.

**Diagnostic check:** look at `report.json` for the function's
parent TU. If the TU has many `fuzzy=None` functions (no source
defined yet), AND the near-match function's cascade-delta in
bytes roughly equals the total expected string-literal weight of
the missing functions, this is the sub-pattern. Decoded the
baserom's `lbl_eu_<addr>` for the TU's `@stringBase0` byte-by-byte
and compare to your build's `@stringBase0` — strings that appear
only in the baserom belong to the missing functions.

**Recipe (real fix):** decompile enough of the missing sibling
functions to populate `@stringBase0` to structural parity. Slow
per-win but unblocks all downstream near-matches in the TU at
once.

**Recipe (workaround, when waiting for siblings to land):** skip
per-function 100% match attempts on near-miss functions in
NonMatching TUs with many `fuzzy=None` siblings. The cascade is
structural, not iteratively-fixable from the one function's
source. Document the structural blocker in the PR body and move
on to another near-match.

**Use when:** a near-match function in a NonMatching TU has off-
by-N-bytes `addi` diffs AND the TU has many `fuzzy=None` functions
listed in `report.json`. The cascade is downstream of the
siblings' absence, not a region literal.

**Brain-lane follow-up candidate:** a "dummy literal injection"
mechanism — define a `__sinit_`-only string array in the source
that compiles into `stringBase0` to take the place of the missing
functions' literals. Hacky but unblocks per-function matches in
NonMatching TUs without waiting for full sibling decomp. Worth
scoping as a future scaffolder brief if the per-function-in-
NonMatching-TU pattern shows up multiple times.

**First hit:** cycle 12, `src/kyoshin/cf/CfBdat.cpp`'s
`OnFileEvent` (decomper PR #22). 13 `fuzzy=None` siblings in
CfBdat.cpp; their ~105 bytes of missing strings (incl.
`"posX"`/`"posY"`/`"posZ"`, ~15 bytes of Shift-JIS Japanese text,
`"common/jp/bdat_eve.bin"`) cause the +0x69 byte shift in
OnFileEvent's `@stringBase0` references.

---

### PPC-2 — Region-conditional code branch (pluginWait PAL detection)

**Symptom in objdiff:** an entire BB-shape divergence — the matched
function has extra `bl ...` calls, extra `cmpwi` + `bne` /  `beq`
branches, and different magic constants (the project's NTSC vs PAL
frame-time being the canonical example).

**Root cause:** the US/EU build genuinely has more code than JP
because the source legitimately differs per region. The most common
case: PAL detection via `CDeviceVI::isTvFormatPal()` calling +
dual-decrement values (`0x1333` for PAL ≈ 50 Hz frame, `0x1000` for
NTSC ≈ 60 Hz). JP omits the call because NTSC-J is the only target.

**Recipe:**

```cpp
#if defined(VERSION_JP)
    int decrement = 0x1000;
#else
    int decrement = CDeviceVI::isTvFormatPal() ? 0x1333 : 0x1000;
#endif
*temp_r3 -= decrement;
if ((s32)*temp_r3 > 0) vmWaitModeSet(pThread);
```

Same `#if defined(VERSION_*)` wrap pattern as PPC-1, but the wrapped
content is a code branch, not a literal. The wrapped variable
captures the per-region behaviour; the call site downstream stays
region-agnostic.

**Use when:** objdiff shows extra basic blocks in US/EU vs JP (or
vice versa), and reading the asm reveals region-specific runtime
detection (PAL/NTSC, language code, region-specific allocator paths).

**Caveat about convention:** the `#if defined(VERSION_*)` pattern is
**sparingly used** in this codebase — pre-fork there were ~2 such
files (`src/kyoshin/main.cpp` is the canonical example with
`sLanguageFolderPaths`, `sPkhFilenames`). Use it only for genuine
source-level divergence (PAL detection, language tables); region-
specific *data layout* should go through `splits.txt` carves
(scaffolder's `carve_splits.py`) instead.

**No ARM analog** — region branches are Wii-specific (DS only ships
one region per cartridge; mwcc ARM Wii didn't ship a separate PAL
build).

**First hit:** cycle 8, `src/kyoshin/plugin/pluginWait.cpp`
(decomper PR #15 deferred; queued for cycle 9 brief 016).

---

### PPC-3 — `extern "C"` mangling wall

**Symptom at link time:** `undefined: 'func_<addr>__Fi'` or similar
mangled-name link error when the binary stores `func_<addr>`
unmangled. Symbol exists, but the C++ caller mangled the name with
Itanium-style arg encoding and the linker can't resolve.

**Root cause:** `include/functions.hpp` (and equivalent header
buckets) declare `func_<addr>` placeholders without an
`extern "C"` wrap, so any C++ TU referencing them mangles the
symbol. Per-TU local forward-declarations inside `extern "C" {}`
work around it, but accumulate workaround debt.

**Recipe (header-side, preferred):**

Wrap the placeholder declarations in `extern "C" { ... }` with
`#ifdef __cplusplus` guards (same convention as
`libs/monolib/include/monolib/vm/yvm2.h`):

```cpp
#ifdef __cplusplus
extern "C" {
#endif

UNKWORD func_8009CF8C(int);
UNKWORD func_8009D018(void);
// ... etc

#ifdef __cplusplus
}
#endif
```

This **was applied** to `include/functions.hpp` in cycle 5 (scaffolder
brief 010, commit `a10ebbc`). All NEW placeholder declarations should
go inside the extern-C block.

**Recipe (local fallback if header fix isn't possible):**

Inside the affected `.cpp`:

```cpp
extern "C" {
    void vmBuiltinOCRegist(OCData* pOC);  // forward-declare; matches name verbatim
}
```

**Use when:** link error mentions a mangled-name symbol that the
binary stores unmangled. Almost always a placeholder symbol via
`functions.hpp` or a library header lacking `extern "C"`.

**ARM analog:** spirit-caller C-22 family (linkage-mismatch walls).

**First hit:** cycle 2, `src/kyoshin/plugin/ocBuiltin.cpp` (decomper
local extern; ditto pluginHelp.cpp cycle 4). Header fix landed cycle
5 in scaffolder PR #10.

---

### PPC-4 — Signed-cast for "u32 used as signed sentinel" comparisons

**Symptom in objdiff:** the matched function has `cntlzw r0, r3;
srwi r0, r0, 5;` (sign-bit extraction idiom) where our compiled
output has a hard-coded constant or different shifts. Specifically
when comparing the return of a function that returns `u32` but uses
`-1` (i.e. `0xFFFFFFFF`) as a "not found" sentinel.

**Root cause:** mwcc folds `u32 >= 0` to always-true (and emits no
sign-check). The baserom expects you to treat the return as `s32`,
hence the `cntlzw` sign-bit extraction.

**Recipe:**

```cpp
// vmPropertySearch returns u32 but uses -1 as the not-found sentinel.
// Without the (s32) cast, mwcc folds (u32 >= 0) to always-true and skips
// the sign-bit / cntlzw idiom the baserom uses.
BOOL found = (s32)vmPropertySearch(pOC, ...) >= 0;
```

The explicit cast at the load site (BEFORE the comparison) forces
mwcc to emit the signed compare against zero, which lowers to the
`cntlzw` idiom.

**Use when:** a function that returns `u32` is used with a `>= 0` /
`< 0` / `== -1` comparison, AND objdiff shows the matched code uses
`cntlzw` / `srwi 5` / similar sign-extraction patterns. Adding the
`(s32)` cast at the load site fixes the comparison's codegen.

**ARM analog:** spirit-caller C-13 family (predicated-if-X-order).

**First hit:** cycle 2, `src/kyoshin/plugin/ocBuiltin.cpp`'s
`isExistProperty` + `isExistSelector` (decomper PR #4).

---

### PPC-6 — Region-specific struct size / new fields (CGame)

**Symptom in objdiff:** `li r3, 0xNNN` allocator-call size constants
differ by a small power-of-two offset (typically 4-16 bytes), AND
field-access offsets within methods reference offsets that don't
exist in the JP build. Often manifests as low overall fuzzy %
across MULTIPLE functions in the same TU (not just one), because
every method that touches the class layout is affected.

**Root cause:** the class itself has extra fields in US/EU vs JP (or
vice versa) — `sizeof(C)` legitimately differs. The added fields
are usually region-specific feature flags, counters, language-
dependent state. mwcc emits `li r3, sizeof(C)` at construction
sites and `lhz/lwz r0, FIELD_OFFSET(r4)` at field accesses, and
both bake the per-region offsets into the codegen.

**Recipe (when the field is genuinely region-specific):**

```cpp
// CGame.hpp
class CGame {
public:
    // ... pre-0x230 fields ...

#if !defined(VERSION_JP)
    u16 mUnkRegionField230;  // US/EU only, used as a counter in func_800395F4
    u16 mUnkRegionField232;  // US/EU only, used alongside the first
#endif

    // ... post-0x234 fields would shift in JP -- check the layout ...
};
```

If the added fields are AT THE END of the class, the recipe is
simple (just add them under `#if !defined(VERSION_JP)`). If they're
in the MIDDLE, every subsequent field shifts per-region and the
layout needs region-conditional reordering or two layout structs.

**Use when:** allocator-size `li r3, 0xNNN` constants differ across
regions for the same class, AND/OR field-access offsets within
methods reference different absolute offsets per region. The
allocator-size diff is the cleanest signal; field-access mismatches
without an allocator-size diff might be PPC-1 (string cascade)
instead.

**Caveat:** a single PR matching a region-divergent class touches
multiple files (the .hpp for the layout, multiple .cpp methods
that access the new fields). Plan brief scope accordingly — these
are NOT sweep-shaped.

**No ARM analog noted yet** — spirit-caller's DS decomp is single-
region; region-specific struct fields are a multi-region-decomp
problem.

**First hit:** cycle 9, `src/kyoshin/CGame.cpp` (decomper PR #17
deferred; cycle 10 PR #19 closed at 100% — class is 8 bytes
bigger in US/EU at offset 0x230. Confirmed layout: `mLetterboxMargin`
(u16) + `unk232` (u16 padding) + `unk234` (u32 padding) to bring
`sizeof(CGame)` to 0x238).

**Sub-recipe A — unused-field padding is load-bearing for `sizeof`.**
When `sizeof` grows by N bytes but only M < N bytes are read by any
function in the TU, the unread bytes still need declaration as
placeholder fields to keep `sizeof` right. The instinct is to
declare only the read fields; the refinement is "placeholder
`u16` / `u32` fields with `// alignment` or `// padding` comments
for any read-but-named gap". First-pass on CGame declared only
`mLetterboxMargin` and `sizeof` came out at `0x234`, 4 bytes
short — the constructor's allocator-size constant then mismatched
the baserom.

**Sub-recipe B — unused side-effect call pattern.** A region-
specific function call whose return value is *discarded* next to
a field init (e.g. `CDeviceVI::isTvFormatPal(); mLetterboxMargin =
0x39;`) is a recognizable PPC-6 sibling. mwcc keeps the call
because it can't prove the function is side-effect-free, so the
asm has a `bl <function>` next to the field init even though no
register state from the call is used downstream. When you see a
`bl` in the matched asm with no apparent consumer, suspect this
pattern — the C source has the call as a discarded statement.

---

### PPC-9 — Port coercion: enum return-type vs integer typedef

**Symptom at compile time:** mwcc errors with
`(10563) identifier <X> redeclared as @enum$N (...)` when
compiling a freshly-ported file from `kiwi515/open_rvl` /
`doldecomp/mkw` / `doldecomp/brawl` / similar.

**Root cause:** upstream pools (open_rvl, mkw, brawl) use named
enum types (`NANDResult`, `DVDResult`, `SCResult`, etc.) as
function return values. Xenoblade's vendored headers declare
those same functions returning the underlying integer type (`s32`,
`int`). mwcc treats enum vs integer typedef as a redeclaration
conflict even though the underlying representation is identical.

**Recipe (fast):** `sed` the enum name to the integer type in the
ported source. The enum's underlying type IS the integer, so this
is a typedef-equivalence rename — zero semantic change.

```sh
# Example from cycle 13 nand.c port: 19 NANDResult occurrences:
sed -i '' 's/\bNANDResult\b/s32/g' \
  libs/RVL_SDK/src/revolution/nand/nand.c
```

**Recipe (invasive but tidier):** adopt the enum in the header
too — `typedef enum { ... } NANDResult;` in
`libs/RVL_SDK/include/revolution/NAND.h` matching the upstream
definition. Requires touching every caller. Use only if multiple
ports converge on the same enum and the integer type is locally
inconsistent.

**Use when:** a fresh `port_external_source.py --apply` output
fails compilation with the `@enum$N` redeclaration message. Almost
always after porting from a pool with newer / different SDK
headers than Xenoblade's vendored copy.

**ARM analog:** likely some equivalent in spirit-caller's
`port_external_source.py` flow but not yet documented in their
codegen-walls. Cross-reference when sync'ing the two docs.

**First hit:** cycle 13, `libs/RVL_SDK/src/revolution/nand/nand.c`
(decomper PR #25). `NANDResult` → `s32`, 19 occurrences.

---

### PPC-12 — Missing class-static / vtable link error solved by symbols.txt placeholder rename, not stub TU

> **Status:** CONFIRMED cycle 18. Three observations total:
> cycle-15 `sUnkFlags__Q22cf13CfGameManager` (static u32),
> cycle-18 `__vt__Q34nw4r3g3d15AnmObjMatClrRes` (vtable),
> cycle-18 `__vt__Q34nw4r3g3d12AnmObjMatClr` (vtable).
>
> **HIGH-leverage** — cycle-9's PR #15 documented ~67
> link-error failures on landlord-TU dependencies; many follow
> this pattern. Rename sweeps queued.

**Symptom at link time:** a `.cpp` references a C++ class static
(e.g. `Klass::sVar` or `Klass::TYPE_NAME`) and the linker errors
with `undefined: 'Klass::sVar'` / `'sVar__N+ClassName'`.

**Root cause:** the storage exists in the binary at a known
address, but is named by an address-based placeholder
(`lbl_eu_<addr>`, `lbl_<region>_<addr>`) in
`config/<region>/symbols.txt` rather than the C++-mangled name
that the calling `.cpp` produces. The linker matches symbols by
name, not by address.

**Recipe:** find the placeholder in `config/<region>/symbols.txt`
at the right address. Read the target asm's `@sda21` reference
(or `@l`/`@ha` for non-sda symbols) from the calling function in
`build/<region>/asm/<TU>.s` to identify the address. Then rename
the placeholder to the mangled C++ name. **NO source change
needed, NO stub TU needed.**

```diff
# Example from cycle 15 PR #29:
-lbl_eu_80663E28 = .sbss:0x80663E28; // type:object size:0x4 data:4byte
+sUnkFlags__Q22cf13CfGameManager = .sbss:0x80663E28; // type:object size:0x4 data:4byte
```

**Use when:** linker reports `undefined` for a class static
reference whose storage type/size matches an existing
`lbl_<region>_<addr>` in symbols.txt at the right address.

**Sweep methodology (when this lands as a confirmed wall):**
combine `tools/data_worklist.py` output (ranked placeholder
candidates) with the link-error symbol from the failed `ninja`
attempt — high-reader-count placeholders are the most leverage
to rename first because they unblock the most call sites at
once.

**Distinct from PPC-5** (anonymous-namespace / vtable + RTTI
landlord TU): PPC-5 is about MISSING landlord TUs (the storage
needs to be defined somewhere). PPC-12 is about MISNAMED
existing storage (the storage exists, just under the wrong name).
Check PPC-12 first — if the placeholder exists at the right
address, the fix is cheap. If no placeholder exists at the
address, fall back to PPC-5's landlord-TU diagnosis.

**No ARM analog noted yet** — spirit-caller's DS decomp may have
a different placeholder-naming convention. Cross-reference once
sync'ing the two docs.

**Variants observed:**
- **Static u32** (cycle 15, `sUnkFlags`): address-context trust
  required to verify the rename.
- **Vtable** (cycle 18, `__vt__Q34nw4r3g3d12AnmObjMatClr` and
  `__vt__Q34nw4r3g3d15AnmObjMatClrRes`): STRONGER verification
  signal — the vtable's `.data` content includes function pointer
  names already mangled with class scope, so the parent vtable's
  owning class is unambiguously identifiable from its content
  (read `build/<region>/asm/<lib>_data.s` for the address).

**Stronger verification recipe for vtable variant:** read the
`.data` dump at the placeholder's address. If the bytes resolve
to function-pointer relocations naming `*__Q+N+ClassName*`
methods (mwcc-mangled), the parent vtable's name is
`__vt__Q+N+ClassName`. Paste-ready rename.

**First observed:** cycle 15, `sUnkFlags__Q22cf13CfGameManager`
in `src/kyoshin/plugin/pluginPad.cpp` (decomper PR #29).
Confirmed cycle 18 with two vtable renames in
`config/us/symbols.txt` (decomper PR #34) — those resolved part
of g3d_anmclr's link errors though the TU still awaits
`AnmObj::TYPE_NAME` / `G3dObj::TYPE_NAME` placeholders to be
located (likely in unsorted `nw4r_data.s` storage).

---

### PPC-11 (candidate — single observation) — Undefined macro in ported source silently becomes `bl <MACRO_NAME>` external

> **Status:** candidate wall, single observation. Promote to a
> confirmed PPC-11 entry after a second independent hit.

**Symptom in objdiff:** a ported file from `kiwi515/open_rvl` /
`doldecomp/mkw` / `doldecomp/brawl` / similar has MULTIPLE
sub-100% functions, all showing the same pattern: the target asm
has an inline byte-clearing or memory-copying sequence (17 `stw`
zeroes, etc.) where your `.o` has a `bl <SOMETHING>` to an
identifier NOT in `config/<region>/symbols.txt`.

**Root cause:** upstream pools include macros in their own
`include/*.h` (e.g. `CLEAR_PATH(x) → __memclr(x, sizeof(x))` in
`tools/_vendor/open_rvl/include/revolution/macros.h`). These
macro definitions are NOT on Xenoblade's compile path —
`tools/_vendor/` is gitignored and not in include search dirs.
mwcc treats the undefined identifier as a function call instead
of erroring, emitting `bl <MACRO_NAME>` as an unresolved external.

The build SUCCEEDS even with the unresolved external because the
TU is NonMatching status (so dtk's pre-extracted `.o` is linked,
not the compiled one). objdiff compares your broken `.o` to the
extracted one — the report flags the diffs but the SHA-1 gate
doesn't fire.

**Recipe (per-port, decomper lane):** grep ported source for
macros NOT defined in `libs/<lib>/include/` but present in
`tools/_vendor/<repo>/include/`. Inline the macro expansion at
call sites. Single batch fix often resolves multiple sub-100%
functions at once.

**Recipe (project-wide, scaffolder lane):** add commonly-used
macros to `include/macros.h` so future ports get them
automatically. Risk: macro semantics may differ between upstream
pools, so blanket adoption needs per-macro review.

**Use when:** a freshly-ported TU has MULTIPLE sub-100% functions
all showing inline `stw/stb/lwz/etc.` sequences in the target
where your `.o` has `bl <IDENTIFIER>` calls AND the identifier
isn't in `config/<region>/symbols.txt`. The mwcc-silently-accepts-
undefined-identifier-as-function behavior is the smoking gun.

**First observed:** cycle 14, `libs/RVL_SDK/src/revolution/nand/
nand.c`'s 8 sub-100% functions (decomper PR #26). Single
`CLEAR_PATH → __memclr` inline at 7 call sites brought ALL 8
functions to 100% fuzzy in one batch. Awaits second-hit citation
before promoting from candidate to confirmed.

---

### PPC-10 (candidate — single observation) — mwcc `-inline auto` doesn't cross `.c`/`.h` boundary

> **Status:** candidate wall, single observation. Promote to a
> confirmed PPC-10 entry after a second independent hit.

**Symptom in objdiff:** a near-miss caller function's asm shows
the inlined body of a small helper function rather than a `bl`
call to it. Your source has the helper as a regular non-static
function declared in a header and defined in a `.c`.

**Root cause (hypothesized):** mwcc's `-inline auto` requires the
function body to be visible at the call site OR for the function
to be `static` (file-local). A plain non-static `inline`
declaration in a header with the body in a separate `.c` doesn't
allow cross-TU inlining; `-inline auto` falls back to a `bl` call.

**Recipe (hypothesized):** move the body to the header with
`static inline`. Forces inlining at every call site.

**Use when:** the caller's asm has the inlined helper's
instructions inline, your `.o` has a `bl helperFunc` call, and
the helper is small enough to inline (a few BBs).

**First observed:** cycle 13, `OSShutdownSystem` calling
`__OSGetDiscState`. Investigation deferred; brain pending
confirmation on a second case before promoting from candidate to
confirmed wall.

---

### PPC-8 — Virtual function name mismatch prevents override

**Symptom in objdiff:** a near-match (typically 99.9%+ fuzzy) on a
derived-class constructor / sinit / method that calls a virtual.
The only diff is the `lwz r12, 0xN(r12)` vtable-slot offset — the
matched code resolves the call to one slot, your `.o` resolves it
to a higher slot (typically appended at the end of the vtable
rather than overriding an inherited slot).

**Root cause:** mwcc treats virtual methods with different names
as NEW vtable slots, not overrides of inherited ones. If the base
class declares `virtual void Foo()` and the derived class declares
`virtual void DerivedFoo()` (different name) intending to override,
mwcc emits `DerivedFoo` as a fresh slot appended after all of
`Base`'s virtuals — leaving `Foo` still inherited at its original
slot. Polymorphic calls then hit different slots in the baserom
vs the rebuild.

**Recipe:**

```cpp
// Before — derived virtuals named with class prefix, mwcc treats as
// new slots:
class CAttackParam {
    virtual void CAttackParam_UnkVirtualFunc1();  // slot 2
    virtual u8   CAttackParam_UnkVirtualFunc2();  // slot 3
    // ...
};
class CArtsParam : public CAttackParam {
    virtual void CArtsParam_UnkVirtualFunc1();    // slot 6 — WRONG! appended
    virtual u8   CArtsParam_UnkVirtualFunc2();    // slot 7 — also appended
};

// After — same names in both, mwcc emits as overrides:
class CAttackParam {
    virtual void UnkVirtualFunc1();   // slot 2
    virtual u8   UnkVirtualFunc2();   // slot 3
};
class CArtsParam : public CAttackParam {
    virtual void UnkVirtualFunc1();   // overrides slot 2
    virtual u8   UnkVirtualFunc2();   // overrides slot 3
};
```

**Symbol renames in `config/<region>/symbols.txt`:** both base and
derived class methods need their mangled names normalized to the
shared identifier — e.g.,
`CAttackParam_UnkVirtualFunc1__Q22cf12CAttackParamFv` becomes
`UnkVirtualFunc1__Q22cf12CAttackParamFv`. mwcc's name mangling
preserves class qualification (`__Q22cf12CAttackParam`), so there's
no collision between same-named virtuals across different classes.

**Use when:** a polymorphic call resolves to a higher vtable slot
in your `.o` than in the baserom, AND the function is declared
with a different name in the derived class than in the base. The
slot-offset delta is the smoking gun.

**Distinct from PPC-6 (region-specific struct size):** PPC-8 is
NOT a region issue — it's a layout bug from naming. PPC-6 changes
class size; PPC-8 changes vtable layout. They can co-occur if a
class has both region-specific fields AND mis-named virtuals, but
fixing them is independent.

**No ARM analog noted yet** — spirit-caller hasn't surfaced this
pattern; mwcc ARM may handle it differently or it may not have
appeared in their decomp yet.

**First hit:** cycle 11, `src/kyoshin/cf/CArtsParam.cpp` (decomper
PR #21). Cascade renames in `CArtsParam.cpp` (method definitions +
caller calls) and `CArtsSet.cpp:12`'s `mArtsParams[i].UnkVirtualFunc1()`.
Two function-level wins (CArtsParam `__ct__` + `__sinit_` both
99.96% → 100%) but no TU-level promotion because the rest of
CArtsParam.cpp has functions still NonMatching.

---

### PPC-7 — mwcc if/else branch-ordering matters

**Symptom in objdiff:** a near-match (99%+ fuzzy) where the only
divergence is the **basic-block order** — your compiled `.o` has
`if (X) { A; } else { B; }` emitted with the A-body falling
through and `beq` to the B-label; the baserom has `bne` to the
B-label with the B-body falling through (or vice versa). Same
instructions, different topology.

**Root cause:** mwcc's source-form-to-branch-shape lowering picks
the fallthrough body based on the SOURCE-LEVEL conditional, not
the SEMANTIC condition. `if (X)` puts the X-true body in
fallthrough; `if (!X)` puts the X-false body in fallthrough.
When the baserom was compiled from `if (!X)` and you write
`if (X)`, your branch shape is inverted relative to the baserom
— the produced instructions match, but their layout doesn't.

**Recipe:** invert the conditional to match the baserom's
fallthrough body. Example from pluginWait PAL detection (cycle 9):

```cpp
// FIRST ATTEMPT — natural-order, 99.88 percent fuzzy:
if (CDeviceVI::isTvFormatPal()) {
    *temp_r3 -= 0x1333;  // PAL body in fallthrough
} else {
    *temp_r3 -= 0x1000;  // NTSC body via beq
}

// FIX — inverted, 100 percent match:
if (!CDeviceVI::isTvFormatPal()) {
    *temp_r3 -= 0x1000;  // NTSC body in fallthrough (matches baserom's bne)
} else {
    *temp_r3 -= 0x1333;
}
```

**Use when:** a near-match at 99%+ fuzzy where objdiff shows the
SAME instructions but in different basic-block order, and the only
diff is a `beq` ↔ `bne` flip plus the swap of which body is
fallthrough. Invert the source conditional.

**Tip:** read the baserom's branch first. If it's `bne label`, the
baserom's source was `if (X) { fallthrough } else { label }` — so
your source needs the same fallthrough body. If it's `beq label`,
the baserom's source was `if (!X) { fallthrough } else { label }`
— write yours the same.

**ARM analog:** spirit-caller likely has an equivalent in their
C-N family — mwcc ARM has the same branch-lowering behaviour. To
be cross-referenced once we sync with their `codegen-walls.md`.

**First hit:** cycle 9, `wait_frame__FP10_sVMThread` PAL fix
(decomper PR #17 — `if (isTvFormatPal()) { PAL } else { NTSC }`
went 99.88% → 100% by inverting to `if (!isTvFormatPal()) { NTSC }
else { PAL }` matching the baserom's `bne PAL_label` schedule).

---

### PPC-5 — Anonymous-namespace / vtable + RTTI landlord TU

**Symptom at link time:** `undefined: 'nw4r::g3d::G3dObj::TYPE_NAME'`,
`nw4r::g3d::ScnLeaf::TYPE_NAME`, similar vtable / RTTI metadata
symbols. Common when promoting a `MatchingFor("jp")` to plain
`Matching` (so the gate fires for US too) — the symbol exists in
the JP build's `.o` graph but not US's.

**Root cause:** vtable + RTTI metadata for a C++ class (anonymous-
namespace `const char* TYPE_NAME` etc.) is defined only in the
originating TU. When dtk extracts the class's parent `.o` as
NonMatching (i.e. doesn't fully decompile the class), the symbol's
*definition site* gets lost from the build graph. Any TU that uses
the class then fails to link in US because the JP-only matched
copy isn't present.

**Recipe (long-term):**

There's no source-side workaround. The landlord TU (the one that
defines the vtable + RTTI) must be matched so its `.o` surfaces the
TYPE_NAME / vtable symbols correctly. Track which TUs are landlords
for which dependents; match landlords first to cascade-unlock the
dependents.

**Useful tool: `tools/dep_graph.py --chain`** — surfaces high-impact
landlords (cycle-5 example: `CCharVoiceMan.cpp` unlocks 17
dependents, `CfGameManager.cpp` unlocks 15).

**Future tool (queued brief 018-B):** `tools/find_external_source.py`
for Wii — mine `kiwi515/open_rvl` + `doldecomp/mkw` + `doldecomp/brawl`
for matched landlord source. The `nw4r::g3d::*::TYPE_NAME` family
likely has matched copies in one of those projects (mkw and brawl
are heavy nw4r/g3d/snd consumers).

**Use when:** a `MatchingFor("jp")` candidate fails the flip with a
link error mentioning `TYPE_NAME`, `__vt__`, `__RTTI__`, or any
anonymous-namespace-shaped name. The candidate isn't broken; it's
waiting for its landlord.

**No ARM analog** — C++ vtable + anon-ns metadata is mwcc-PPC-
specific (mwcc ARM uses different vtable layout).

**First hit:** cycle 6, `monolib/src/math/FloatUtils.cpp` (decomper
PR #11 documented `ml::huge` / `ml::hugeminus` landlord; same
shape across the cycle-8 67-failure breakdown in PR #15).

---

## Splits.txt sub-recipe — middle-of-split1.s carve cycle (cycle 13)

> Tactical splits.txt recipe (not a codegen wall per se, but lives
> here for reference until a separate splits-asymmetry doc exists).

**Symptom:** running `python3 tools/carve_splits.py --apply` for
a TU that sits in the MIDDLE of `split1.s`'s catch-all range
triggers `Cyclic dependency encountered while resolving link
order` from dtk during the next `python3 configure.py --version
<r>` step.

**Root cause:** dtk treats `split1.s` as a single TU node in its
link-order graph. The carve fragments split1.s into ≥ 2 sub-
ranges per affected section, forcing split1.s to come both
BEFORE and AFTER the carved TU (because some of its sub-ranges
precede the carved TU's address and others follow). dtk refuses.

**Recipe:** add `--promote-multi-pseudo-unit` to the
`carve_splits.py` invocation. The tool promotes `split1.s` →
`split1a.s` + `split1b.s` + ... — one pseudo-unit per contiguous
sub-range. Each pseudo-unit ends up with ≤ 1 range per section,
so dtk treats them as independent TU nodes. dtk auto-discovers
the new pseudo-units from `splits.txt` — **no `configure.py`
edits required** (verified cycle 13 via `tools/project.py:437`
autogeneration path).

```sh
python3 tools/carve_splits.py --region us --promote-multi-pseudo-unit --apply \
    kyoshin/plugin/pluginGame.cpp \
    kyoshin/plugin/pluginMath.cpp \
    kyoshin/plugin/pluginPad.cpp
```

**Use when:** carve_splits.py refuses with the fragmentation gate
error message (`split1.s .data: 2 sub-ranges (must be ≤ 1 to
avoid dtk link-order cycle)`). The flag adds pseudo-unit naming
on top of the carve; downstream impact is zero (pseudo-units have
no Matching status to track, byte coverage is preserved exactly).

**First hit:** cycle 13, brief 025 (scaffolder PR #24). Resolved
the cycle-6 deferral of pluginGame / pluginMath / pluginPad —
all three carve cleanly post-flag. Decomper can flip them in
cycle 14 without source changes.

## How to add a wall

When decomper or scaffolder hits a new recurring divergence pattern:

1. **Confirm it's recurrent.** A wall earns its name after at least 2
   confirmed cases (one is "interesting", two is a "pattern").
2. **Pick the next `PPC-N` number** (this file has the latest).
3. **Document in the format above:** name, symptom, root cause,
   recipe (with worked code), use-when hint, ARM analog if any,
   first-hit citation.
4. **Brain merges it.** Decomper / scaffolder don't directly edit
   this file (per AGENTS.md scope rules — `docs/` is brain's lane).
   They send the wall write-up in their PR body; brain folds it
   here.

## Future tool integration

Spirit-caller's `tools/suggest_coercion.py` reads `objdiff` JSON diff
output and surfaces matching `codegen-walls.md` entries with their
recipes. Queued as cycle 10+ scaffolder brief once we have enough
walls to make the surface useful (~10-15). For now, decomper reads
this file directly when iterating on near-matches.

## Cross-references

- [`spirit-caller/docs/research/codegen-walls.md`](https://github.com/cntrl-alt-lenny/gx-spirit-caller/blob/main/docs/research/codegen-walls.md)
  — sister DS / mwcc ARM catalogue with 27+ walls.
- [`zeldaret/tww/docs/regalloc.md`](https://github.com/zeldaret/tww/blob/main/docs/regalloc.md)
  — closest existing mwcc PowerPC reference; reg-swap fixes
  organised by workaround, no named-pattern taxonomy.
- [`encounter/decomp-toolkit/assets/signatures/`](https://github.com/encounter/decomp-toolkit/tree/main/assets/signatures)
  — YAML signature registry; opportunistic landlord-naming via
  `tools/signature_lookup.py` (queued cycle 10 brief 018-A).
