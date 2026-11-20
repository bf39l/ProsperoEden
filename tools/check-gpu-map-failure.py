#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Execute production pin checks, scope rollback and NVDEC batch failure handling."""
from pathlib import Path
import subprocess,sys,tempfile
engine=Path(sys.argv[1]);base=engine/'src/core/hle/service/nvdrv/devices'
s=(base/'nvhost_as_gpu.cpp').read_text();v=(base/'nvhost_nvdec_common.cpp').read_text()
a=s.index('    auto handle{nvmap.GetHandle(params.handle)};',s.index('NvResult nvhost_as_gpu::MapBufferEx'))
b=s.index('    bool big_page',a);prologue=s[a:b]
a=s.index('            DAddr base = nvmap.PinHandle(entry.handle, false);');b=s.index('\n        }',s.index('            gmmu->Map(virtual_address',a));remap=s[a:b]
a=v.index('NvResult nvhost_nvdec_common::MapBuffer(');b=v.index('\n}\n',a)+2;video=v[a:b]
code=r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <memory>
#include <span>
#include <stdexcept>
#include <vector>
#include "common/scope_exit.h"
using u32=std::uint32_t;using u64=std::uint64_t;using DAddr=u64;using DeviceFD=unsigned;
enum class NvResult{Success,BadValue,InsufficientMemory};
namespace Tegra {enum class PTEKind{Zero};}
struct Entry{u32 handle=1,handle_offset_big_pages=2,kind=0;};
struct Params{u32 handle=1;u64 buffer_offset=0x200,mapping_size=0;};
struct Handle{u64 orig_size=4096;};
struct Pins{
 bool valid=true;unsigned cursor=0;std::vector<DAddr> addresses;std::vector<unsigned> unpinned;
 std::shared_ptr<Handle> GetHandle(unsigned){return valid?std::make_shared<Handle>():nullptr;}
 DAddr PinHandle(unsigned,bool){assert(cursor<addresses.size());return addresses[cursor++];}
 void UnpinHandle(unsigned id){unpinned.push_back(id);}
};
struct Gmmu{unsigned maps=0;DAddr last=0;void Map(u64,DAddr at,u64,Tegra::PTEKind,bool){++maps;last=at;}};
NvResult MapOne(Pins& nvmap,Params params,Gmmu& gpu,bool fail_after_pin=false,bool throws=false){
'''+prologue+r'''
 if(fail_after_pin)return NvResult::BadValue;
 if(throws)throw std::runtime_error("mock");
 gpu.Map(0x40000,device_address,size,Tegra::PTEKind::Zero,false);
 keep_pin=true;return NvResult::Success;
}
NvResult RemapOne(Pins& nvmap,const Entry& entry,Gmmu* gmmu){
 struct{unsigned big_page_size_bits=16;} vm;
 u64 virtual_address=0x40000,size=65536;bool use_big_pages=true;
'''+remap+r'''
 return NvResult::Success;
}
struct IoctlMapBuffer{u32 num_entries;};
struct MapBufferEntry{u32 map_handle,map_address;};
struct nvhost_nvdec_common{Pins& nvmap;NvResult MapBuffer(IoctlMapBuffer&,std::span<MapBufferEntry>,DeviceFD);};
'''+video+r'''
int main(){
 {Pins p;p.addresses={0};Gmmu g;assert(MapOne(p,{},g)==NvResult::InsufficientMemory);assert(!g.maps&&p.unpinned.empty());}
 {Pins p;p.addresses={0x100000};Gmmu g;assert(MapOne(p,{},g,true)==NvResult::BadValue);assert(!g.maps&&p.unpinned==std::vector<unsigned>{1});}
 {Pins p;p.addresses={0x100000};Gmmu g;assert(MapOne(p,{},g)==NvResult::Success);assert(g.last==0x100200&&p.unpinned.empty());}
 {Pins p;p.addresses={0x100000};Gmmu g;try{MapOne(p,{},g,false,true);assert(false);}catch(const std::runtime_error&){}assert(p.unpinned==std::vector<unsigned>{1});}
 {Pins p;p.valid=false;Gmmu g;assert(MapOne(p,{},g)==NvResult::BadValue&&p.cursor==0);}
 {Pins p;p.addresses={0};Gmmu g;assert(RemapOne(p,{},&g)==NvResult::InsufficientMemory&&!g.maps);}
 {Pins p;p.addresses={0x100000};Gmmu g;assert(RemapOne(p,{},&g)==NvResult::Success&&g.last==0x120000);}
 {Pins p;p.addresses={0x1000,0x2000,0};nvhost_nvdec_common c{p};IoctlMapBuffer params{3};MapBufferEntry e[]{{7,0},{8,0},{9,0}};
  assert(c.MapBuffer(params,e,0)==NvResult::InsufficientMemory);assert((p.unpinned==std::vector<unsigned>{7,8}));for(auto x:e)assert(x.map_address==0);}
 {Pins p;p.addresses={0x1000,0x2000};nvhost_nvdec_common c{p};IoctlMapBuffer params{9};MapBufferEntry e[]{{7,0},{8,0}};
  assert(c.MapBuffer(params,e,0)==NvResult::Success&&e[0].map_address==0x1000&&e[1].map_address==0x2000&&p.unpinned.empty());}
}
'''
assert s.count('keep_pin = true;')==1
with tempfile.TemporaryDirectory() as scratch:
 p=Path(scratch);cpp=p/'test.cpp';exe=p/'test';cpp.write_text(code)
 subprocess.run(['c++','-std=c++20','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-fsanitize=address,undefined','-I'+str(engine/'src'),str(cpp),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
print('GPU map failure PASS: no zero/offset mappings, ordinary/error/exception pin ownership, remap checks, partial video-batch rollback and successful batches (ASan/UBSan)')
