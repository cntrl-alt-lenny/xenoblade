#include "kyoshin/plugin/pluginWait.hpp"
#if !defined(VERSION_JP)
#include "monolib/device/CDeviceVI.hpp"
#endif

static PluginFuncData sPluginWaitFuncs[] = {
    {"frame", wait_frame},
    {NULL,NULL}
};

int wait_frame(VMThread* pThread) {
    int temp_r30 = vmArgIntGet(2, vmArgPtrGet(pThread, 1));
    int wkIdx = vmWkIdxGet(pThread);

    if (wkIdx == 0) {
        u32* temp_r3 = vmWkGet(pThread, 0);
        *temp_r3 = temp_r30 << 0xC;
        vmWkIdxSet(pThread, wkIdx + 1); //why not just set it to 1???
        vmWaitModeSet(pThread);
    } else {
        u32* temp_r3 = vmWkGet(pThread, 0);
#if defined(VERSION_JP)
        int temp_r0 = *temp_r3 - 0x1000;
        *temp_r3 = temp_r0;
        if (temp_r0 > 0) {
            vmWaitModeSet(pThread);
        }
#else
        // EU/US: PAL builds at 50 Hz need a larger decrement so one VM
        // "frame" still maps to one real frame. 0x1333 / 0x1000 ~= 60/50.
        // Conditional written as "!isPAL()" so mwcc emits the NTSC body
        // first (matches the baserom's bne PAL_label schedule).
        if (!CDeviceVI::isTvFormatPal()) {
            *temp_r3 -= 0x1000;
        } else {
            *temp_r3 -= 0x1333;
        }
        if ((s32)*temp_r3 > 0) {
            vmWaitModeSet(pThread);
        }
#endif
    }
    return 0;
}

void pluginWaitRegist(){
    vmPluginRegist("wait", sPluginWaitFuncs);
}
