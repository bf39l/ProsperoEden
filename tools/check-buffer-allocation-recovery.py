#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise the production OOM retry with the real slot container and retirement ring."""
from pathlib import Path
import subprocess,sys,tempfile
root=Path(sys.argv[1]);s=(root/'src/video_core/buffer_cache/buffer_cache.h').read_text()
a=s.index('    const BufferId new_buffer_id = [&] {');b=s.index('    auto& new_buffer',a);allocate=s[a:b]
h=(root/'src/video_core/renderer_vulkan/vk_buffer_cache.h').read_text();a=h.index('    bool IsOutOfDeviceMemory');b=h.index('\n#endif',a);classifier=h[a:b]
fixture=r'''
#include <cassert>
#include <exception>
#include <stdexcept>
#include <vector>
#include "common/slot_vector.h"
#include "video_core/delayed_destruction_ring.h"
#define LOG_WARNING(...) ((void)0)
constexpr int VK_ERROR_OUT_OF_DEVICE_MEMORY=-2;
namespace vk{struct Exception:std::exception{int result;explicit Exception(int r):result(r){}int GetResult()const{return result;}};}
using BufferId=Common::SlotId;
struct Runtime{
 int attempts=0,failures=0,result=-2,finished=0,released=0;bool finish_fails=false;
 void Finish(){if(finish_fails)throw vk::Exception(-4);++finished;}
'''+classifier+r'''
};
struct Buffer{
 Runtime*runtime;bool retired=false;int payload=42;
 Buffer(Runtime&r,unsigned,unsigned,bool):runtime(&r){++r.attempts;if(r.attempts<=r.failures)throw vk::Exception(r.result);}
 Buffer(Runtime&r):runtime(&r),retired(true){}
 Buffer& operator=(Buffer&&other)noexcept{runtime=other.runtime;retired=other.retired;payload=other.payload;other.runtime=nullptr;return *this;}
 Buffer(Buffer&&other)noexcept:runtime(other.runtime),retired(other.retired),payload(other.payload){other.runtime=nullptr;}
 ~Buffer(){if(runtime&&retired){assert(runtime->finished);++runtime->released;}}
};
struct Cache{
 Runtime runtime;Common::SlotVector<Buffer>slot_buffers;VideoCommon::DelayedDestructionRing<Buffer,6>delayed_destruction_ring;
 BufferId live;
 Cache(){live=slot_buffers.insert(runtime,0,4,false);runtime.attempts=0;}
 ~Cache(){runtime.finished=1;}
 void Retire(){delayed_destruction_ring.Push(Buffer(runtime));}
 BufferId Allocate(){unsigned wanted_size=296,size=296;bool sparse_compatible=false;struct{unsigned begin=10;std::vector<unsigned>ids{1};}overlap;
'''+allocate+r'''
return new_buffer_id;
 }
};
int main(){
 {Cache c;c.Retire();c.Retire();c.runtime.failures=1;auto id=c.Allocate();assert(id&&c.runtime.attempts==2&&c.runtime.finished==1&&c.runtime.released==2);assert(c.slot_buffers[c.live].payload==42&&c.slot_buffers.size()==2);}
 {Cache c;c.Retire();auto id=c.Allocate();assert(id&&c.runtime.attempts==1&&!c.runtime.finished&&!c.runtime.released);}
 {Cache c;c.Retire();c.runtime.failures=2;bool caught=false;try{c.Allocate();}catch(vk::Exception&e){caught=e.result==-2;}assert(caught&&c.runtime.attempts==2&&c.runtime.released==1&&c.slot_buffers.size()==1&&c.slot_buffers[c.live].payload==42);}
 {Cache c;c.Retire();c.runtime.failures=1;c.runtime.result=-4;bool caught=false;try{c.Allocate();}catch(vk::Exception&e){caught=e.result==-4;}assert(caught&&!c.runtime.finished&&!c.runtime.released&&c.runtime.attempts==1);}
 {Cache c;c.runtime.failures=1;bool caught=false;try{c.Allocate();}catch(vk::Exception&e){caught=e.result==-2;}assert(caught&&c.runtime.attempts==1&&c.runtime.finished==1);}
 {Cache c;c.Retire();c.runtime.failures=1;c.runtime.finish_fails=true;bool caught=false;try{c.Allocate();}catch(vk::Exception&e){caught=e.result==-4;}assert(caught&&!c.runtime.released&&c.runtime.attempts==1);}
 Runtime r;std::runtime_error ordinary("not Vulkan");assert(!r.IsOutOfDeviceMemory(std::make_exception_ptr(ordinary)));
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d);cpp=p/'test.cpp';exe=p/'test';cpp.write_text(fixture)
 (p/'common').mkdir();(p/'common/assert.h').write_text('#pragma once\n#include <cassert>\n#define DEBUG_ASSERT(x) assert(x)\n')
 # The PS5 override restores the free slot when a Vulkan constructor throws.
 recovery=root.parent/'native-local/headless/recovery'
 assert (recovery/'common/slot_vector.h').exists()
 subprocess.run(['c++','-std=c++20','-fno-rtti','-DPS5_NATIVE','-Wall','-Wextra','-Werror','-Wno-unused-variable','-Wno-unused-but-set-variable','-fsanitize=address,undefined','-I'+str(p),'-I'+str(recovery),'-I'+str(root/'src'),str(cpp),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
print('Buffer OOM recovery PASS: production retry/classifier, real slot/ring, live data preserved, synchronized retired frees, bounded retries, non-OOM and failed-wait refusal (ASan/UBSan)')
