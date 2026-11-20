#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run actual DMA method dispatch against unbound and bound channel fixtures."""
from pathlib import Path
import subprocess,sys,tempfile
engine=Path(sys.argv[1]);s=(engine/'src/video_core/dma_pusher.cpp').read_text()
def function(signature):
 a=s.index(signature);b=s.index('{',a)+1;depth=1
 while depth:depth+=(s[b]=='{')-(s[b]=='}');b+=1
 return s[a:b]
code=r'''
#include <array>
#include <bitset>
#include <cassert>
#include <cstdint>
#include <stdexcept>
#include <vector>
using u32=std::uint32_t;using u64=std::uint64_t;
unsigned logged=0;
#define LOG_ERROR(...) ++logged
namespace Core{struct System{};}
namespace Tegra {
namespace Engines {
struct Puller {
 struct MethodCall{u32 method,argument,subchannel,method_count;};unsigned calls=0;
 template<class D>void CallPullerMethod(D&,MethodCall){++calls;}
 template<class D>void CallMultiMethod(D&,u32,u32,const u32*,u32,u32){++calls;}
};
}
struct Engine {
 std::bitset<65535> execution_mask;std::vector<std::pair<u32,u32>> method_sink;
 u64 current_dma_segment=0;unsigned consumed=0,single=0,multi=0;
 void ConsumeSink(Core::System&){++consumed;}
 void CallMethod(Core::System&,u32,u32,bool){++single;}
 void CallMultiMethod(Core::System&,u32,const u32*,u32,u32){++multi;}
};
struct DmaPusher {
 static constexpr u32 non_puller_methods=0x40;
 struct{u32 method=0x73,subchannel=0,method_count=1;u64 dma_get=0x1000,dma_word_offset=4;bool is_last_call=true;}dma_state;
 std::array<Engine*,8> subchannels{};Engines::Puller puller;Core::System system;
 void CallMethod(u32);void CallMultiMethod(const u32*,u32);
};
'''+function('void DmaPusher::CallMethod(')+function('void DmaPusher::CallMultiMethod(')+r'''
}
int main(){
 Tegra::DmaPusher d;u32 args[]{12,13};
 for(unsigned channel=0;channel<8;++channel){d.dma_state.subchannel=channel;
  try{d.CallMethod(12);assert(false);}catch(const std::runtime_error&){}
  try{d.CallMultiMethod(args,2);assert(false);}catch(const std::runtime_error&){}
 }
 assert(logged==16);
 d.dma_state.subchannel=0;Tegra::Engine e;d.subchannels[0]=&e;
 d.CallMethod(12);assert(e.method_sink.size()==1&&e.single==0);
 e.execution_mask.set(0x73);d.CallMethod(12);d.CallMultiMethod(args,2);
 assert(e.single==1&&e.multi==1&&e.consumed==2&&e.current_dma_segment==0x1004&&logged==16);
 d.subchannels[0]=nullptr;d.dma_state.method=1;d.CallMethod(12);d.CallMultiMethod(args,2);
 assert(d.puller.calls==2&&logged==16);
}
'''
with tempfile.TemporaryDirectory() as scratch:
 p=Path(scratch);cpp=p/'test.cpp';exe=p/'test';cpp.write_text(code)
 subprocess.run(['c++','-std=c++20','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(cpp),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
print('DMA unbound channel PASS: real single/multi dispatch, all 8 channels rejected before dereference, valid sink/direct dispatch and puller path preserved (ASan/UBSan)')
