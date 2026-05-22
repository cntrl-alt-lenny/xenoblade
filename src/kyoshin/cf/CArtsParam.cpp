#include "kyoshin/cf/CArtsSet.hpp"

namespace cf {
    CArtsParam lbl_80577580;

    CAttackParam::CAttackParam(){
        unk0 = 0;
        unk20 = 0;
        unk78 = 0;
        UnkVirtualFunc1();
    }

    CArtsParam::CArtsParam(){
        UnkVirtualFunc1();
    }

    void CArtsParam::UnkVirtualFunc1(){
        CAttackParam::UnkVirtualFunc1();
        unk88 = 0;
    }

    void CArtsParam::UnkVirtualFunc3(u8 r4){
        if(unk88 != nullptr){
            unk0 = r4;
        }
    }

    u8 CArtsParam::UnkVirtualFunc2(){
        if(unk88 != nullptr){
            return *(u8*)unk88;
        }
        return unk2A;
    }
}
