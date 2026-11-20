#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise production mapping cleanup across explicit unmap and FreeSpace."""
from pathlib import Path
import subprocess, sys, tempfile
s=(Path(sys.argv[1])/'src/core/hle/service/nvdrv/devices/nvhost_as_gpu.cpp').read_text()
def extract(start,end):
    return s[s.index(start):s.index(end,s.index(start))].replace('nvhost_as_gpu::','Cache::')
methods=extract('bool nvhost_as_gpu::FreeMappingLocked','NvResult nvhost_as_gpu::Remap')+extract('NvResult nvhost_as_gpu::UnmapBuffer','NvResult nvhost_as_gpu::BindChannel')
fixture=r'''
#include <algorithm>
#include "core/hle/service/nvdrv/core/sparse_mapping_ownership.h"
#include <cassert>
#include <cstdint>
#include <map>
#include <set>
#include <vector>
#include <mutex>
using u64=uint64_t;using u32=uint32_t;
#define LOG_DEBUG(...) ((void)0)
enum class NvResult{Success,BadValue};
struct VM{static constexpr u32 YUZU_PAGESIZE=4096,PAGE_SIZE_BITS=12;bool initialised=true;u32 big_page_size=65536,big_page_size_bits=16;struct A{void Free(u32,u32){}} a;A* small_page_allocator=&a;A* big_page_allocator=&a;};
namespace Common{u64 AlignUp(u64 n,u64 p){return (n+p-1)/p*p;}}
struct Mapping{unsigned handle;u64 offset,size;bool fixed,big_page,sparse_alloc;};
struct Allocation{std::vector<u64> mappings;u64 size;u32 page_size;bool sparse;};
struct Params{u64 offset;u32 pages=16,page_size=4096;};
using IoctlFreeSpace=Params;using IoctlUnmapBuffer=Params;
struct Cache{
 Service::Nvidia::NvCore::SparseMappingOwnership sparse_mapping_pins;
 VM vm;std::mutex mutex;std::map<u64,Mapping> mapping_map;std::map<u64,Allocation> allocation_map;std::set<u64> map_buffer_offsets;
 struct Pins{int refs=0;void UnpinHandle(unsigned){assert(refs>0);--refs;}} nvmap;
 struct GPU{int unmaps=0;void MapSparse(u64,u64,bool){++unmaps;}void Unmap(u64,u64){++unmaps;}} gpu;GPU* gmmu=&gpu;
 bool FreeMappingLocked(u64);NvResult FreeSpace(Params&);NvResult UnmapBuffer(Params&);
 void Add(u64 p,bool fixed=true){mapping_map.emplace(p,Mapping{1,p,4096,fixed,false,true});map_buffer_offsets.insert(p);if(fixed)allocation_map.begin()->second.mappings.push_back(p);++nvmap.refs;}
};
'''
tests=r'''
int main(){
 Cache c;c.allocation_map.emplace(0x10000,Allocation{{},65536,4096,true});
 c.Add(0x10000);c.Add(0x11000);
 Params first{0x10000};assert(c.UnmapBuffer(first)==NvResult::Success);
 if(c.nvmap.refs!=1||c.allocation_map.begin()->second.mappings!=std::vector<u64>{0x11000})return 10;
 // Repeated explicit unmaps remain no-ops; replacements create one list entry.
 for(int i=0;i<1000;++i){c.Add(0x10000);assert(c.UnmapBuffer(first)==NvResult::Success);assert(c.UnmapBuffer(first)==NvResult::Success);}
 assert(c.nvmap.refs==1&&c.allocation_map.begin()->second.mappings.size()==1);
 assert(c.FreeSpace(first)==NvResult::Success);
 assert(c.nvmap.refs==0&&c.mapping_map.empty()&&c.map_buffer_offsets.empty());
 // FreeSpace followed by a redundant UnmapBuffer must never dereference end().
 Params second{0x11000};assert(c.UnmapBuffer(second)==NvResult::Success);
 c.Add(0x30000,false);Params dynamic{0x30000};assert(c.UnmapBuffer(dynamic)==NvResult::Success);assert(c.nvmap.refs==0);
}
'''
with tempfile.TemporaryDirectory() as d:
    cpp=Path(d)/'test.cpp';exe=Path(d)/'test';cpp.write_text(fixture+methods+tests)
    subprocess.run(['c++','-std=c++20','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I'+str(Path(sys.argv[1])/'src'),str(cpp),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
    # Refuse the old implementation: it leaves a freed address in the list.
    start=methods.index('        // Keep all ownership indexes')
    end=methods.index('        mapping_map.erase(offset);',start)
    old=methods[:start]+methods[end:]
    cpp.write_text(fixture+old+tests)
    subprocess.run(['c++','-std=c++20','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I'+str(Path(sys.argv[1])/'src'),str(cpp),'-o',str(exe)],check=True)
    assert subprocess.run([str(exe)]).returncode==10

print('GPU mapping cleanup PASS: production teardown, repeated unmap/remap, FreeSpace, redundant unmap and dynamic mapping (ASan/UBSan)')
