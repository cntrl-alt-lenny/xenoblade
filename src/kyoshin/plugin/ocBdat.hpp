#pragma once

#include <types.h>

//Utility class for handling bdat files.
class CBdat {
public:
    static void func_8003AA34();
    static void func_8003AA50();
    static void func_8003AA78(u32, void*);
    static void func_8003AA8C(u32 val);
    static const char* getBdatStringColumnValue(void* pData, const char* pColumnName, int index);
    static u16 func_8003B1EC(void* pData);
    static u16 func_8003B41C(void* pData);
};

// Free function (not a CBdat member): the baserom mangles this as
// `getFP__FPCc` (F = function, PCc = pointer-to-const-char), the free-
// function shape. Declaring it inside the class would give it the
// `__Q22cf6CBdat`-prefixed mangling and prevent matching.
void* getFP(const char* pName);
