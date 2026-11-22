#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check real macro routing and refresh/rejection for the native-indirect workaround."""
from pathlib import Path
import re, subprocess, sys, tempfile
root=Path(__file__).resolve().parents[1]
engine=Path(sys.argv[1])
with tempfile.TemporaryDirectory() as scratch:
    p=Path(scratch)
    subprocess.run(['cmake','-DMACRO_INPUT='+str(engine/'src/video_core/macro.cpp'),
        '-DMACRO_OUTPUT='+str(p/'macro.cpp'),'-DEDEN_PORT_DIR='+str(root/'headless'),
        '-P',str(root/'headless/macro_recovery.cmake')],check=True)
    derived=(p/'macro.cpp').read_text()
    original=(engine/'src/video_core/macro.cpp').read_text()
    guard=re.search(r'bool IsDrawImplausible\(.*?\n}',derived,re.S).group()
    fixture=r"""
#include "indirect_draw_policy.h"
#include <algorithm>
#include <array>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <span>
using u32=std::uint32_t;using u64=std::uint64_t;
namespace Core {struct System {u64 id;u64 GetApplicationProcessProgramID(){return id;}};}
namespace VideoCommon::Dirty {constexpr int IndexBuffer=0;}
namespace Eden::IndirectDrawLog {
struct DrawScope {template<class... T> DrawScope(T&&...){} void Retried(std::span<const u32>){} };
}
struct Trace {void Refreshed(std::span<const u32>){} void Retried(std::span<const u32>){};};
int accepted=0,dropped=0,native=0;u32 last_instances=0;
void ReportDroppedDraw(const char*,u32,u32){++dropped;}
struct Maxwell3D {
 struct Regs {enum class PrimitiveTopology{Triangles=4};u32 vertex_id_base{};} regs{};
 enum class EngineHint{None,OnHLEMacro};EngineHint engine_state{};
 enum class HLEReplacementAttributeType {BaseVertex,BaseInstance};
 struct {std::array<bool,1> flags{};} dirty{};
 struct Manager {
  template<class... T> void DrawIndex(Maxwell3D&,Regs::PrimitiveTopology,u32,u32 count,u32,u32,u32 instances,T...){
   if(count && instances){++accepted;last_instances=instances;}
  }
 } draw_manager{};
 std::span<u32> words;bool repair=false;int refreshes=0,retries=0;
 u32 GetRegisterValue(u32){return 0xffffffffu;}
 void RefreshParameters(){++refreshes;}
 void ForceRefreshParameters(){++retries;if(repair) for(std::size_t i=0;i<words.size();++i) if(words[i]==2147484943u) words[i]=2;}
 void SetHLEReplacementAttributeType(int,int,HLEReplacementAttributeType){}
 void CallMethod(Core::System&,int,u32,bool){}
};
"""
    code=fixture+guard+'\n'
    for kind in ('DrawArraysIndirect','DrawIndexedIndirect','MultiDrawIndexedIndirectCount'):
        entry='void HLE_'+kind+'::Execute('
        start=derived.index(entry)
        a=derived.index('    if (::Eden::NeedsValidatedIndirectDraws(',start)
        # Capture the actual routing block, including its logging and return.
        brace=derived.index('{',a);depth=1;b=brace+1
        while depth:
            depth+=(derived[b]=='{')-(derived[b]=='}');b+=1
        routing=derived[a:b]
        old_start=original.index(entry);old_end=original.index('\n}',old_start)
        new_end=derived.index('\n}',start)
        # Removing the new entry block must leave the native implementation byte-for-byte intact.
        assert derived[start:new_end].replace(routing+'\n','',1)==original[old_start:old_end]
        begin=derived.index('void HLE_'+kind+'::Fallback(')
        finish=derived.index('\n}',begin)
        body=derived[begin:finish]
        a=body.index('    maxwell3d.RefreshParameters();')
        if kind=='MultiDrawIndexedIndirectCount':
            fallback=body[a:]
        else:
            b=body.index('    const u32 instance_count =',a)
            fallback=body[a:b]+'\n    if (parameters[1] && parameters[2]) { ++accepted;last_instances=parameters[2]; }\n'
        code+='struct HLE_'+kind+' { void Fallback(Core::System& system, Maxwell3D& maxwell3d, std::span<const u32> parameters) {\n'
        if kind!='MultiDrawIndexedIndirectCount':code+='(void)system; Trace eden_args;\n'
        code+=fallback+'\n}\nvoid Execute(Core::System& system, Maxwell3D& maxwell3d, std::span<const u32> parameters) {\n'+routing+'\n++native;\n}\n};\n'
    code+=r"""
void Reset(){accepted=dropped=native=0;last_instances=0;}
template<class Macro> void Single() {
 Core::System ff{0x0100B8A026F14000ULL};Macro m;
 u32 args[]{4,192,2147484943u,0,0,0};Maxwell3D gpu{.words=args};
 Reset();m.Execute(ff,gpu,args);
 assert(native==0&&accepted==0&&dropped==1&&gpu.refreshes==1&&gpu.retries==1);
 Reset();gpu.repair=true;gpu.refreshes=gpu.retries=0;m.Execute(ff,gpu,args);
 assert(native==0&&accepted==1&&dropped==0&&last_instances==2&&gpu.retries==1);
 Reset();gpu.refreshes=gpu.retries=0;m.Execute(ff,gpu,args);
 assert(accepted==1&&gpu.refreshes==1&&gpu.retries==0);
 Core::System other{0x010038B015560000ULL};Reset();gpu.refreshes=0;m.Execute(other,gpu,args);
 assert(native==1&&accepted==0&&dropped==0&&gpu.refreshes==0);
}
int main(){
#ifdef PS5_NATIVE
 assert(Eden::NeedsValidatedIndirectDraws(0x0100B8A026F14000ULL));
 assert(!Eden::NeedsValidatedIndirectDraws(0));
 Single<HLE_DrawArraysIndirect>();Single<HLE_DrawIndexedIndirect>();
 HLE_MultiDrawIndexedIndirectCount multi;Core::System ff{0x0100B8A026F14000ULL};
 u32 words[]{0,3,4,0,3, 192,2,0,0,0, 192,2147484943u,0,0,0, 0,0xffffffffu,0,0,0};
 Maxwell3D gpu{.words=words};Reset();multi.Execute(ff,gpu,words);
 assert(native==0&&accepted==1&&dropped==1&&gpu.refreshes==1&&gpu.retries==1);
 gpu.repair=true;Reset();multi.Execute(ff,gpu,words);
 assert(native==0&&accepted==2&&dropped==0&&last_instances==2);
 Core::System other{0x010038B015560000ULL};Reset();gpu.refreshes=0;multi.Execute(other,gpu,words);
 assert(native==1&&gpu.refreshes==0);
#else
 assert(!Eden::NeedsValidatedIndirectDraws(0x0100B8A026F14000ULL));
#endif
}
"""
    cpp=p/'test.cpp';cpp.write_text(code)
    for flags in (['-DPS5_NATIVE'],[]):
        exe=p/('test-ps5' if flags else 'test-other')
        subprocess.run(['c++','-std=c++20','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
            '-I'+str(root/'headless'),*flags,str(cpp),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)
print('Native indirect guard PASS: all three native routes intercepted, actual refresh/retry/rejection, recorded 2,147,484,943 instances refused, repaired and zero draws preserved, other games/hosts unchanged')
