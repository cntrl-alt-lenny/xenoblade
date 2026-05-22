#include "monolib/vm/yvm2.h"
#include <string.h>

extern "C" {

// Built-in OC table. Defined in the kyoshin/plugin .data section; declared
// extern here because ocBuiltinRegist passes its address to vmBuiltinOCRegist.
extern OCData lbl_eu_80524BF8;

// Not declared in yvm2.h yet — forward-declared locally to keep the libs/
// header untouched. See yvm2.c for the definition.
void vmBuiltinOCRegist(OCData* pOC);

int isExistProperty(VMThread* pThread, int /* unused */, OCData* pOC) {
    VMArg result;
    // The signed cast matters: vmPropertySearch returns u32 but uses -1 as the
    // not-found sentinel, so the original source treats the result as signed
    // for the "found" test. Without the cast mwcc folds (u32 >= 0) to true.
    BOOL found = (s32)vmPropertySearch(pOC, vmArgStringGet(2, vmArgPtrGet(pThread, 1))) >= 0;
    result.type = !found + VM_TYPE_TRUE;
    vmRetValSet(pThread, &result);
    return 1;
}

int isExistSelector(VMThread* pThread, int /* unused */, OCData* pOC) {
    VMArg result;
    BOOL found = (s32)vmSelectorSearch(pOC, vmArgStringGet(2, vmArgPtrGet(pThread, 1))) >= 0;
    result.type = !found + VM_TYPE_TRUE;
    vmRetValSet(pThread, &result);
    return 1;
}

int getOCName(VMThread* pThread, int /* unused */, OCData* pOC) {
    VMArg result;
    result.type = VM_TYPE_STRING;
    result.unk2 = strlen(pOC->name);
    result.value.pointerVal = (void*)pOC->name;
    vmRetValSet(pThread, &result);
    return 1;
}

void ocBuiltinRegist() {
    vmBuiltinOCRegist(&lbl_eu_80524BF8);
}

} // extern "C"
