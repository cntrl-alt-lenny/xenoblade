#pragma once

#include <types.h>

// Placeholder declarations for address-named symbols decomper hasn't
// renamed yet. Wrapped in `extern "C"` so .cpp call sites don't have to
// re-declare each one locally to avoid mwcc's C++ name-mangling — the
// definitions in src/ are mwcc-built without mangling, and we want
// matching linkage here. As symbols get real names (and proper homes
// in libs/<lib>/include/), they move out of this catch-all.

#ifdef __cplusplus
extern "C" {
#endif

//Vec4 constructor? Defined before CTaskGame::Term
struct func_800407C8_tmp {
    f32 unk00[4];
};
func_800407C8_tmp* func_800407C8(func_800407C8_tmp*, f32, f32, f32, f32);

void func_8004302C(int, int);
bool func_8009CF8C(int);
void func_8009D018(int, int);
int* func_8009ECB0();
void func_8009E574(int*, int, int, int);

#ifdef __cplusplus
}
#endif
