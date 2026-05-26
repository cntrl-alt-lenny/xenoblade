# 046 — scaffolder/hoist-playpolicytable

**Goal:** Move the `policyTable[ANM_POLICY_MAX]` static array out of the inline `GetAnmPlayPolicy` function in `libs/nw4r/include/nw4r/g3d/g3d_anmobj.h` so non-`g3d_anmobj` TUs stop emitting their own 8-byte `.sdata` copy. Unblocks the `g3d_anmclr.cpp` flip (brief 045 retry will become brief 048).

## Context

Brief 045 (PR #46, closed) found that flipping `g3d_anmclr.cpp` to Matching shifts the DOL SHA-1 by +8 bytes downstream of `.sdata`. The TU itself reports 100% match across every section — the problem is purely linker-layout cascade.

Root cause (confirmed by decomper via `dtk elf info`):

```cpp
// libs/nw4r/include/nw4r/g3d/g3d_anmobj.h:69-72
inline PlayPolicyFunc GetAnmPlayPolicy(AnmPolicy policy) {
    static PlayPolicyFunc policyTable[ANM_POLICY_MAX] = {
        PlayPolicy_Onetime, PlayPolicy_Loop
    };
    return policyTable[policy];
}
```

Because the function is `inline` with a function-scope `static`, every TU that includes the header and references the function emits its own private copy of `policyTable` (8 bytes in `.sdata`) under `@LOCAL@GetAnmPlayPolicy__Q24nw4r3g3dFQ34nw4r3g3d9AnmPolicy@policyTable`.

In the original binary, the table appears only once (it's the `lbl_eu_80663458` from brief 042 = two `PlayPolicy_*` function pointers in `nw4r::g3d` namespace). So the original `g3d_anmobj.cpp` defined a single shared copy, not an inline-with-function-static.

## Scope

- `libs/nw4r/include/nw4r/g3d/g3d_anmobj.h` — change `GetAnmPlayPolicy` to a non-inline declaration. Drop the function body.
- `libs/nw4r/src/g3d/g3d_anmobj.cpp` — add the definition: a single file-scope `static PlayPolicyFunc policyTable[ANM_POLICY_MAX] = { PlayPolicy_Onetime, PlayPolicy_Loop };` and the function body that indexes it.

## Non-scope

- Don't touch `config/` (no splits/symbols changes needed — the symbol identity is the same, just relocated).
- Don't touch `g3d_anmclr.cpp` — the decomper retries the flip in a separate brief (048).
- Don't expose `policyTable` as a public extern. Match the original's apparent file-scope-static layout.
- Don't widen scope to other inline+function-static patterns in `nw4r` headers, even if you spot them. One issue at a time.

## Suggested edit shape

Header (`g3d_anmobj.h`):

```cpp
// before
inline PlayPolicyFunc GetAnmPlayPolicy(AnmPolicy policy) {
    static PlayPolicyFunc policyTable[ANM_POLICY_MAX] = {
        PlayPolicy_Onetime, PlayPolicy_Loop
    };
    return policyTable[policy];
}

// after
PlayPolicyFunc GetAnmPlayPolicy(AnmPolicy policy);
```

Source (`g3d_anmobj.cpp`) — add somewhere in the `nw4r::g3d` namespace:

```cpp
namespace nw4r { namespace g3d {

static PlayPolicyFunc policyTable[ANM_POLICY_MAX] = {
    PlayPolicy_Onetime, PlayPolicy_Loop
};

PlayPolicyFunc GetAnmPlayPolicy(AnmPolicy policy) {
    return policyTable[policy];
}

}}
```

(Exact namespace nesting / placement should match `g3d_anmobj.cpp`'s existing style.)

## Success

- `python configure.py --version us && ninja` builds clean.
- `build/us/main.dol` SHA-1 stays `214b15173fa3bad23a067476d58d3933ad7037b7`.
- `g3d_anmobj.o`'s `.sdata` gains 8 bytes for the `policyTable`.
- Any other TU that previously emitted `@LOCAL@…@policyTable` stops doing so (verifiable with `dtk elf info` on a few sample .o files like `g3d_anmclr.o`, `g3d_anmscn.o`).
- Doesn't move the build hash today; the win is unblocking brief 048's flip.

## Test plan

- [ ] Edit header + source
- [ ] Build clean
- [ ] SHA-1 verified
- [ ] (Optional) confirm via `dtk elf info build/us/.../g3d_anmclr.o` that `.sdata` no longer contains the `@LOCAL@…policyTable` entry

## If it doesn't work

If the build breaks (e.g., `g3d_anmobj.cpp` isn't yet a real TU and you can't add to it cleanly, or the linker objects to the new layout), bail and report — like the decomper did in PRs #41 / #46. Don't try to fix downstream effects in this brief.

## Branch

`scaffolder/hoist-playpolicytable`

## After this lands

Brief 048 will retry the `g3d_anmclr.cpp` flip a third time. If the cascade theory is right, the flip should produce SHA-1 green this time.
