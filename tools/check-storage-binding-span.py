#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the actual storage binding method against translated-address fixtures."""
from pathlib import Path
import subprocess
import sys
import tempfile

engine = Path(sys.argv[1])
source = (engine / 'src/video_core/buffer_cache/buffer_cache.h').read_text()
def function(text, signature):
    start = text.index(signature)
    pos = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[pos] == '{') - (text[pos] == '}')
        pos += 1
    return text[start:pos]
method = function(source, 'Binding BufferCache<P>::StorageBufferBinding(')
preamble = r'''
#include <algorithm>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <optional>
using u32=std::uint32_t; using u64=std::uint64_t;
using GPUVAddr=u64; using DAddr=u64; using BufferId=u32;
constexpr u64 operator""_MiB(unsigned long long n){return n*1024*1024;}
namespace Core { constexpr u64 DEVICE_PAGESIZE=4096; }
namespace Common {
template<class T,class A> constexpr T AlignDown(T v,A a){return v & ~(T(a)-1);}
template<class T,class A> constexpr T AlignUp(T v,A a){return AlignDown(T(v+T(a)-1),a);}
}
#define LOG_DEBUG(...) ((void)0)
#define LOG_WARNING(...) ((void)0)
#define ASSERT_MSG(...) ((void)0)
struct Binding {DAddr device_addr=0; GPUVAddr gpu_addr=0; u32 size=0; BufferId buffer_id=0;};
constexpr Binding NULL_BINDING{};
struct Memory {
    u64 gpu=0x400000f00, aligned_gpu=0x400000000, payload=256, layout=0xffffffff;
    std::optional<DAddr> aligned_cpu=0x03000000, cpu=0x015bff00;
    template<class T> T Read(u64 at){return static_cast<T>(at==0x100?gpu:payload);}
    u64 GetMemoryLayoutSize(u64){return layout;}
    std::optional<DAddr> GpuToCpuAddress(u64 at){return at==aligned_gpu?aligned_cpu:cpu;}
};
struct Runtime {u32 alignment=4096; u32 GetStorageBufferAlignment()const{return alignment;}};
template<class P> struct BufferCache {
    Memory memory; Memory* gpu_memory=&memory; Runtime runtime;
    Binding StorageBufferBinding(GPUVAddr,u32,bool)const;
};
'''
logger = function(source, 'inline void LogLargeBufferBinding(')
tests = r'''
int main(){
    BufferCache<int> c;
    // Exact observed request reproduced by the old physical-address subtraction.
    const u32 old_size=static_cast<u32>(Common::AlignUp(*c.memory.cpu+c.memory.payload,4096)-*c.memory.aligned_cpu);
    assert(old_size==0xfe5c0000u);
    if(c.StorageBufferBinding(0x100,0,false).size!=4096) return 10;
    assert(c.StorageBufferBinding(0x100,0,true).size==4096);
    for(u32 alignment:{16u,64u,256u,4096u})
    for(u64 offset:{0ull,1ull,15ull,255ull,4095ull})
    for(u64 size:{1ull,16ull,257ull,8191ull}){
        c.runtime.alignment=alignment;
        c.memory.gpu=0x400000000+offset;
        c.memory.aligned_gpu=Common::AlignDown(c.memory.gpu,alignment);
        c.memory.cpu=0x10000000+offset;
        c.memory.aligned_cpu=Common::AlignDown(*c.memory.cpu,alignment);
        c.memory.payload=size;
        for(bool written:{false,true}){
            auto b=c.StorageBufferBinding(0x100,0,written);
            const u64 expected=written?c.memory.gpu-c.memory.aligned_gpu+size:
                Common::AlignUp(*c.memory.cpu+size,4096)-*c.memory.aligned_cpu;
            assert(b.size==expected && b.gpu_addr==c.memory.aligned_gpu);
        }
    }
    c.memory.cpu.reset();
    assert(c.StorageBufferBinding(0x100,0,false).device_addr==0);
    c.memory.aligned_cpu.reset();
    assert(c.StorageBufferBinding(0x100,0,false).device_addr==0);
    c.memory.cpu=0x10000; c.memory.aligned_cpu=0x10000;
    c.runtime.alignment=4096;
    c.memory.gpu=0x400000000; c.memory.aligned_gpu=c.memory.gpu;
    c.memory.payload=300_MiB;
    assert(c.StorageBufferBinding(0x100,0,false).size==300_MiB);
    c.memory.gpu+=4095; c.memory.payload=0xfffffff0;
    assert(c.StorageBufferBinding(0x100,0,true).device_addr==0);
    assert(c.StorageBufferBinding(0x100,0,false).device_addr==0);
    c.memory.gpu=0xfffffffffffffff0ull;
    c.memory.aligned_gpu=Common::AlignDown(c.memory.gpu,4096);
    c.memory.payload=256;
    assert(c.StorageBufferBinding(0x100,0,false).device_addr==0);
    c.memory.gpu=0x400000000; c.memory.aligned_gpu=c.memory.gpu;
    c.memory.payload=0; c.memory.layout=0;
    assert(c.StorageBufferBinding(0x100,0,false).device_addr==0);
}
'''
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    def run(body, name):
        cpp=tmp/(name+'.cpp'); exe=tmp/name
        cpp.write_text(preamble+logger+'\ntemplate<class P>\n'+body+tests)
        subprocess.run(['c++','-std=c++20','-Wall','-Wextra','-Werror',
            '-Wno-unused-parameter','-fsanitize=address,undefined','-g',str(cpp),'-o',str(exe)],check=True)
        return subprocess.run([str(exe)],check=False).returncode
    assert run(method,'fixed')==0
    original=tmp/'src/video_core/buffer_cache/buffer_cache.h'
    original.parent.mkdir(parents=True); original.write_text(source)
    patch=Path(__file__).resolve().parent/'eden-patches/45-storage-binding-virtual-span.diff'
    subprocess.run(['patch','--quiet','-R','-p1','-i',str(patch)],cwd=tmp,check=True)
    old=function(original.read_text(),'Binding BufferCache<P>::StorageBufferBinding(')
    assert run(old,'original')==10, 'Original must reproduce the 0xfe5c0000 span'
print('Storage binding: exact 0xfe5c0000 old-size control, virtual spans, valid large ranges, missing mappings and overflow PASS (ASan/UBSan)')
