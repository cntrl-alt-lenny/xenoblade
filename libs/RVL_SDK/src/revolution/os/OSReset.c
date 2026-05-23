#include <revolution/DVD.h>
#include <revolution/OS.h>
#include <revolution/PAD.h>
#include <revolution/SC.h>
#include <revolution/VI.h>

#include <string.h>

static OSShutdownFunctionQueue ShutdownFunctionQueue;

static void KillThreads(void);

void OSRegisterShutdownFunction(OSShutdownFunctionInfo* info) {
    OSShutdownFunctionInfo* it;
    OSShutdownFunctionInfo* prev;
    OSShutdownFunctionInfo* tail;

    for (it = ShutdownFunctionQueue.head; it != NULL && it->prio <= info->prio;
         it = it->next) {
        ;
    }

    if (it == NULL) {

        tail = ShutdownFunctionQueue.tail;
        if (tail == NULL) {
            ShutdownFunctionQueue.head = info;
        } else {
            ShutdownFunctionQueue.tail->next = info;
        }

        info->prev = tail;
        info->next = NULL;

        it = ShutdownFunctionQueue.head;
        ShutdownFunctionQueue.tail = info;
    } else {
        info->next = it;

        prev = it->prev;
        it->prev = info;
        info->prev = prev;

        if (prev == NULL) {
            ShutdownFunctionQueue.head = info;
        } else {
            prev->next = info;
        }
    }
}

BOOL __OSCallShutdownFunctions(u32 pass, u32 event) {
    OSShutdownFunctionInfo* iter;
    BOOL failure;
    u32 prio;

    prio = 0;
    failure = FALSE;

    for (iter = ShutdownFunctionQueue.head; iter != NULL; iter = iter->next) {
        if (failure && prio != iter->prio) {
            break;
        }

        failure |= !iter->func(pass, event);
        prio = iter->prio;
    }

    failure |= !__OSSyncSram();

    return !failure;
}

void __OSShutdownDevices(u32 event) {
    BOOL padIntr;
    BOOL osIntr;
    BOOL keepEnable;

    // Note: OS_SD_EVENT_RESTART (4) is intentionally NOT in the FALSE
    // branch -- the baserom keeps pad recalibration enabled across a
    // system restart (per the cmplwi r0, 1 / subi 5 switch shape in
    // .text). open_rvl ships a newer SDK that includes case 4 in FALSE;
    // Xenoblade's SDK predates that change.
    switch (event) {
    case OS_SD_EVENT_FATAL:
    case OS_SD_EVENT_RETURN_TO_MENU:
    case OS_SD_EVENT_LAUNCH_APP:
        keepEnable = FALSE;
        break;
    case 1:
    case OS_SD_EVENT_SHUTDOWN:
    case 3:
    case OS_SD_EVENT_RESTART:
    default:
        keepEnable = TRUE;
        break;
    }

    __OSStopAudioSystem();

    if (!keepEnable) {
        padIntr = __PADDisableRecalibration(TRUE);
    }

    while (!__OSCallShutdownFunctions(FALSE, event)) {
        ;
    }

    while (!__OSSyncSram()) {
        ;
    }

    osIntr = OSDisableInterrupts();
    __OSCallShutdownFunctions(TRUE, event);
    LCDisable();

    if (!keepEnable) {
        __PADDisableRecalibration(padIntr);
    }

    KillThreads();
}

// TODO(kiwi) There must be a better way....
// NOTE: target asm inlines this into OSShutdownSystem AND keeps the
// standalone definition. Adding `inline` here doesn't trigger mwcc
// (probably needs the body in the header for `-inline auto` to fire
// on cross-call sites). Deferred -- OSShutdownSystem stays at 85.31%
// until the inlining mechanism is worked out (potential PPC-X wall
// candidate: "mwcc -inline auto doesn't cross .c/.h boundary").
void __OSGetDiscState(u8* out) {
    u32 flags;

    if (__DVDGetCoverStatus() != DVD_COVER_CLOSED) {
        *out = 3;
    } else if (*out == 1) {
        if (!__OSGetRTCFlags(&flags) || flags == 0) {
            goto status_1;
        }

    status_2:
        *out = 2;
    } else {
        goto status_2;

    status_1:
        *out = 1;
    }
}

static void KillThreads(void) {
    OSThread* iter;
    OSThread* next;

    for (iter = OS_THREAD_QUEUE.head; iter != NULL; iter = next) {
        next = iter->nextActive;

        switch (iter->state) {
        case OS_THREAD_STATE_SLEEPING:
        case OS_THREAD_STATE_READY:
            OSCancelThread(iter);
            break;
        }
    }
}

void OSShutdownSystem(void) {
    SCIdleModeInfo idleMode;
    OSStateFlags stateFlags;
    OSIOSRev iosRev;

    memset(&idleMode, 0, sizeof(SCIdleModeInfo));
    SCInit();
    while (SCCheckStatus() == SC_STATUS_BUSY) {
        ;
    }
    SCGetIdleMode(&idleMode);

    __OSStopPlayRecord();
    __OSUnRegisterStateEvent();
    __DVDPrepareReset();
    __OSReadStateFlags(&stateFlags);

    __OSGetDiscState(&stateFlags.discState);
    if (idleMode.wc24 == TRUE) {
        stateFlags.BYTE_0x5 = 5;
    } else {
        stateFlags.BYTE_0x5 = 1;
    }

    __OSClearRTCFlags();
    __OSWriteStateFlags(&stateFlags);
    __OSGetIOSRev(&iosRev);

    if (idleMode.wc24 == TRUE) {
        OSDisableScheduler();
        __OSShutdownDevices(OS_SD_EVENT_RETURN_TO_MENU);
        OSEnableScheduler();
        __OSLaunchMenu();
    } else {
        OSDisableScheduler();
        __OSShutdownDevices(OS_SD_EVENT_SHUTDOWN);
        __OSShutdownToSBY();
    }
}

void OSReturnToMenu(void) {
    OSStateFlags stateFlags;

    __OSStopPlayRecord();
    __OSUnRegisterStateEvent();
    __DVDPrepareReset();

    __OSReadStateFlags(&stateFlags);
    __OSGetDiscState(&stateFlags.discState);
    stateFlags.BYTE_0x5 = 3;
    __OSClearRTCFlags();
    __OSWriteStateFlags(&stateFlags);

    OSDisableScheduler();
    __OSShutdownDevices(OS_SD_EVENT_RETURN_TO_MENU);
    OSEnableScheduler();

    __OSLaunchMenu();
    OSDisableScheduler();
    __VISetRGBModeImm();
    __OSHotReset();

    // clang-format off
#line 843
    OS_ERROR("OSReturnToMenu(): Falied to boot system menu.\n");
    // clang-format on
}

u32 OSGetResetCode(void) {
    if (__OSRebootParams.WORD_0x0 != 0) {
        return __OSRebootParams.WORD_0x4 | 0x80000000;
    }

    return PI_HW_REGS[PI_RESET] >> 3;
}

void OSResetSystem(BOOL reset, u32 resetCode, BOOL forceMenu) {
#pragma unused(reset)
#pragma unused(resetCode)
#pragma unused(forceMenu)

    // clang-format off
#line 1020
    OS_ERROR("OSResetSystem() is obsoleted. It doesn't work any longer.\n");
    // clang-format on
}
