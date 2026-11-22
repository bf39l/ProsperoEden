#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Actual sparse Remap/FreeSpace plus interval lifetime and exhaustion regressions."""
from pathlib import Path
import subprocess,sys,tempfile
root=Path(sys.argv[1]);s=(root/'src/core/hle/service/nvdrv/devices/nvhost_as_gpu.cpp').read_text();h=(root/'src/core/hle/service/nvdrv/devices/nvhost_as_gpu.h').read_text()
def extract(start,end):return s[s.index(start):s.index(end,s.index(start))].replace('nvhost_as_gpu::','Cache::')
methods=extract('bool nvhost_as_gpu::FreeMappingLocked','NvResult nvhost_as_gpu::MapBufferEx')
a=h.index('    struct SparsePin {');b=h.index('    // Declared before gmmu',a);pin=h[a:b]
fixture=r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <random>
#include <set>
#include <span>
#include <stdexcept>
#include <vector>
#include "common/scope_exit.h"
#include "core/hle/service/nvdrv/core/sparse_mapping_ownership.h"
#define LOG_DEBUG(...) ((void)0)
#define LOG_WARNING(...) ((void)0)
#define LOG_ERROR(...) ((void)0)
using DAddr=u64;using GPUVAddr=u64;
enum class NvResult{Success,BadValue,InsufficientMemory};
namespace Tegra{enum class PTEKind{Zero};}
namespace Common{u64 AlignUp(u64 n,u64 p){return (n+p-1)/p*p;}}
namespace NvCore{
using Service::Nvidia::NvCore::SparseMappingOwnership;
struct NvMap{
 ~NvMap(){assert(Total()==0);}
 struct Handle{using Id=unsigned;u64 orig_size=8*65536,aligned_size=8*65536;};
 std::map<unsigned,int>pins;unsigned limit=2;bool fail=false;
 std::shared_ptr<Handle>GetHandle(unsigned id){return id?std::make_shared<Handle>():nullptr;}
 DAddr PinHandle(unsigned id,bool){unsigned active=0;for(auto [h,n]:pins)active+=n!=0;if(fail||(!pins[id]&&active>=limit))return 0;++pins[id];return u64{id}*0x100000;}
 void UnpinHandle(unsigned id){assert(pins[id]>0);--pins[id];}
 int Total()const{int n=0;for(auto [h,p]:pins)n+=p;return n;}
};
}
struct Entry{u16 flags=0,kind=0;unsigned handle=0;u32 handle_offset_big_pages=0,as_offset_big_pages=0,big_pages=0;};
using IoctlRemapEntry=Entry;
struct IoctlFreeSpace{u64 offset;u32 pages,page_size;};
struct Cache{
 struct VM{static constexpr unsigned YUZU_PAGESIZE=4096,PAGE_SIZE_BITS=12;bool initialised=true;unsigned big_page_size_bits=16,big_page_size=65536;struct A{void Free(u32,u32){}}a;A*small_page_allocator=&a;A*big_page_allocator=&a;}vm;
 struct Mapping{unsigned handle;u64 offset,size;bool fixed,big_page,sparse_alloc;};
 struct Allocation{std::vector<u64>mappings;u64 size;u32 page_size;bool sparse,big_pages;};
 NvCore::NvMap nvmap;
 std::map<u64,Mapping>mapping_map;std::map<u64,Allocation>allocation_map;std::set<u64>map_buffer_offsets;std::mutex mutex;
'''+pin+r'''
 NvCore::SparseMappingOwnership sparse_mapping_pins;
 struct GPU{bool throws=false;unsigned changes=0;void Map(u64,u64,u64,Tegra::PTEKind,bool){if(throws)throw std::runtime_error("mock GPU failure");++changes;}void MapSparse(u64,u64,bool){if(throws)throw std::runtime_error("mock GPU failure");++changes;}void Unmap(u64,u64){if(throws)throw std::runtime_error("mock GPU failure");++changes;}} gpu;
 GPU*gmmu=&gpu;
 bool FreeMappingLocked(u64);NvResult FreeSpace(IoctlFreeSpace&);NvResult Remap(std::span<Entry>);
 Cache(){allocation_map.emplace(4*65536,Allocation{{},8*65536,65536,true,true});}
 NvResult Map(unsigned handle,unsigned start,unsigned count){Entry e{0,0,handle,0,start,count};return Remap({&e,1});}
};
'''
tests=r'''
int main(){
 {
 Cache c;assert(c.Map(1,4,4)==NvResult::Success&&c.nvmap.pins[1]==1);
 assert(c.Map(2,5,2)==NvResult::Success&&c.nvmap.pins[1]==1&&c.nvmap.pins[2]==1);
 assert(c.Map(0,4,1)==NvResult::Success&&c.nvmap.pins[1]==1); // right fragment still lives
 if(c.Map(0,7,1)!=NvResult::Success||c.nvmap.pins[1]!=0)return 10;
 // Previously each call added another unreleasable pin.
 for(unsigned i=0;i<1000;++i){assert(c.Map(2+i%5,5,2)==NvResult::Success);assert(c.nvmap.Total()==1);}
 auto before=c.nvmap.Total();c.gpu.throws=true;bool caught=false;
 try{c.Map(99,5,2);}catch(const std::runtime_error&){caught=true;}
 assert(caught&&c.nvmap.Total()==before&&c.nvmap.pins[99]==0);c.gpu.throws=false;
 c.nvmap.fail=true;assert(c.Map(98,5,2)==NvResult::InsufficientMemory&&c.nvmap.Total()==before);c.nvmap.fail=false;
 assert(c.Map(88,5,0)==NvResult::Success&&c.nvmap.Total()==before); // zero-size must not pin
 assert(c.Map(7,4,1)==NvResult::Success&&c.Map(7,8,1)==NvResult::Success&&c.nvmap.pins[7]==2);
 assert(c.Map(0,4,1)==NvResult::Success&&c.nvmap.pins[7]==1);
 assert(c.Map(0,8,1)==NvResult::Success&&c.nvmap.pins[7]==0);
 IoctlFreeSpace free{4*65536,8,65536};assert(c.FreeSpace(free)==NvResult::Success&&c.nvmap.Total()==0);
 }
 {Cache closing;assert(closing.Map(1,4,2)==NvResult::Success);}
 // Independent randomized page model: pin lives while any fragment refers to it.
 std::vector<int>live(1500);std::array<int,32>expected;expected.fill(-1);
 struct Owner{int&count;explicit Owner(int&c):count(c){++count;}~Owner(){--count;}};
 {
 NvCore::SparseMappingOwnership ranges;std::mt19937 rng(12345);
 for(int i=0;i<1500;++i){
  unsigned start=rng()%32,n=1+rng()%(32-start);bool clear=rng()%4==0;
  std::shared_ptr<void>owner=clear?nullptr:std::make_shared<Owner>(live[i]);
  ranges.Replace(start*65536,u64{n}*65536,std::move(owner),[]{});
  for(unsigned p=start;p<start+n;++p)expected[p]=clear?-1:i;
  std::set<int>active(expected.begin(),expected.end());
  for(int j=0;j<=i;++j)assert(live[j]==int(active.contains(j)));
 }
 }
 for(int n:live)assert(n==0); // address-space teardown releases remaining owners
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d);cpp=p/'test.cpp';exe=p/'test';cpp.write_text(fixture+methods+tests)
 subprocess.run(['c++','-std=c++20','-D_GLIBCXX_DEBUG','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I'+str(root/'src'),str(cpp),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
 old=p/'old'
 for name in ['src/core/hle/service/nvdrv/core/sparse_mapping_ownership.h','src/core/hle/service/nvdrv/devices/nvhost_as_gpu.h','src/core/hle/service/nvdrv/devices/nvhost_as_gpu.cpp']:
  dest=old/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text((root/name).read_text())
 patch=Path(__file__).resolve().parent/'eden-patches/41-sparse-remap-pin-ownership.diff'
 subprocess.run(['patch','-s','-R','-p1','-d',str(old),'-i',str(patch)],check=True)
 old_source=(old/'src/core/hle/service/nvdrv/devices/nvhost_as_gpu.cpp').read_text()
 start=old_source.index('NvResult nvhost_as_gpu::Remap(');end=old_source.index('NvResult nvhost_as_gpu::MapBufferEx',start)
 old_remap=old_source[start:end].replace('nvhost_as_gpu::','Cache::')
 new_remap=extract('NvResult nvhost_as_gpu::Remap','NvResult nvhost_as_gpu::MapBufferEx')
 control=fixture.replace('~NvMap(){assert(Total()==0);}','~NvMap()=default;')+methods.replace(new_remap,old_remap)+tests
 cpp.write_text(control)
 subprocess.run(['c++','-std=c++20','-D_GLIBCXX_DEBUG','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I'+str(root/'src'),str(cpp),'-o',str(exe)],check=True)
 assert subprocess.run([str(exe)]).returncode==10

print('Sparse pin ownership PASS: actual Remap/FreeSpace, partial survivors, 1000 replacements under a two-handle budget, rollback/failure, zero-size, 1500 randomized interval lifetimes and teardown (ASan/UBSan)')
