#include "kyoshin/plugin/plugins.hpp"
#include "kyoshin/cf/CfGameManager.hpp"

// The "help" plugin name and its PluginFuncData[] table both live in
// split1.s; referenced as externs so the compiled .o only ships
// .text / extab / extabindex (matching the dtk-extracted .o layout).
// Same pattern as ocBuiltin and pluginTime.
//
// The func_<addr> placeholders are forward-declared locally as extern "C"
// because the binary stores them unmangled, but include/functions.hpp
// declares the two it knows about (func_8009CF8C, func_8009D018) without
// extern "C", which would mangle the references. Touching functions.hpp
// is scaffolder's lane; declaring locally keeps this PR in src/.
extern "C" {
    extern const char lbl_eu_8051347C[];      // "help"
    extern PluginFuncData lbl_eu_8053A498[];  // {"gameStart", ...}, {"itemVision", ...}, {"ptChange", ...}, {NULL, NULL}

    bool func_8009CF8C(int);
    void func_8009D018(int, int);
    void func_80134D18(int, int, int);
    int func_8029A658();
    void func_8013E8E0(int);
}

int help_gameStart(VMThread* pThread) {
    if (!func_8009CF8C(0x3340)) {
        func_80134D18(1, 0, 0);
        func_8009D018(0x3340, 1);
    }
    if (func_8029A658()) {
        vmWaitModeSet(pThread);
    }
    return 0;
}

int help_itemVision(VMThread* pThread) {
    if (!func_8009CF8C(0x337D)) {
        func_80134D18(0x3E, 0, 0);
        func_8009D018(0x337D, 1);
    }
    if (func_8029A658()) {
        vmWaitModeSet(pThread);
    }
    return 0;
}

int help_ptChange(VMThread* pThread) {
    if (func_8029A658()) {
        vmWaitModeSet(pThread);
        return 0;
    }
    cf::CfGameManager::enablePadFlags(-1, true);
    func_8013E8E0(0);
    return 0;
}

void pluginHelpRegist() {
    vmPluginRegist(lbl_eu_8051347C, lbl_eu_8053A498);
}
