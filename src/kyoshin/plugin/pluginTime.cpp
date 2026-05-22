#include "kyoshin/plugin/plugins.hpp"
#include "kyoshin/cf/CfGameManager.hpp"

// The "time" plugin name and its PluginFuncData[] table both live in the
// kyoshin/plugin .data / .rodata sections that are currently emitted from
// split1.s. Until those bytes get split into pluginTime.cpp's TU, the source
// references them as externs so the compiled .o only contributes .text /
// extab / extabindex -- matching the dtk-extracted .o layout the linker
// expects.
extern "C" {
    extern const char lbl_eu_80503818[];     // "time"
    extern PluginFuncData lbl_eu_80532348[]; // {"range", time_range}, {"hour", time_hour}, {NULL, NULL}
}

int time_range(VMThread* pThread) {
    VMArg result;
    result.value.uintVal = cf::CfGameManager::func_80086DBC();
    result.type = VM_TYPE_INT;
    vmRetValSet(pThread, &result);
    return 1;
}

int time_hour(VMThread* pThread) {
    VMArg result;
    // Capturing the masked value in a local lets mwcc keep it in a separate
    // register (r5) while r3 gets re-used as the pThread argument for
    // vmRetValSet; that ordering matches the baserom.
    u16 hour = cf::CfGameManager::func_80086DA0();
    result.type = VM_TYPE_INT;
    result.value.uintVal = hour;
    vmRetValSet(pThread, &result);
    return 1;
}

void pluginTimeRegist() {
    vmPluginRegist(lbl_eu_80503818, lbl_eu_80532348);
}
