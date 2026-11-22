#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run actual GC lookahead against real LRU order; skipped entries must not defeat batching."""
from pathlib import Path
import subprocess,sys,tempfile
repo=Path(__file__).resolve().parents[1];engine=Path(sys.argv[1]);s=(repo/'headless/vulkan_gc_downloads.inc').read_text();s=s[:s.index('    const auto UsePrefetched')]
fixture=r'''
#include <algorithm>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <set>
#include <stdexcept>
#include <type_traits>
#include <vector>
#include <boost/container/small_vector.hpp>
#include "common/lru_cache.h"
#include "common/scope_exit.h"
constexpr u64 operator""_MiB(unsigned long long n){return n<<20;}
using ImageId=unsigned;
namespace Eden::Performance{inline std::atomic<bool>gc_count_visits{false};inline bool keep=true;bool KeepDirtyTextures(){return keep;}enum{gc_batched_drain};struct Timer{Timer(int,size_t){}};}
namespace Vulkan{struct TextureCacheRuntime{
 struct Map{unsigned id;};unsigned next=0,waits=0;std::set<unsigned>held;std::vector<unsigned>copied;
 Map DownloadStagingBuffer(size_t,bool=false){held.insert(++next);return {next};}
 void FreeDeferredStagingBuffer(Map m){assert(held.erase(m.id)==1);}
 void Finish(){++waits;}
};}
enum class ImageFlagBits:unsigned{IsDecoding=1,BadOverlap=2,CostlyLoad=4};
unsigned operator&(unsigned a,ImageFlagBits b){return a&unsigned(b);}bool True(unsigned v){return v!=0;}bool False(unsigned v){return v==0;}
struct Image{unsigned id,flags=0;bool dirty=true;size_t unswizzled_size_bytes=1;u64 reclaimed=1;int info=0;Vulkan::TextureCacheRuntime*runtime;
 void DownloadMemory(Vulkan::TextureCacheRuntime::Map,int){runtime->copied.push_back(id);}
};
int FullDownloadCopies(int){return 0;}
struct Traits{using ObjectType=unsigned;using TickType=u64;};
struct Cache{
 using Runtime=Vulkan::TextureCacheRuntime;Runtime runtime;std::vector<Image>slot_images;Common::LeastRecentlyUsedCache<Traits>lru_cache;
 u64 total_used_memory=10000,critical_memory=5000,expected_memory=100,frame_tick=100,ticks_to_destroy=50;bool high_priority_mode=true,aggressive_mode=false;size_t num_iterations=20;static constexpr size_t max_scanned=8192;
 void Add(unsigned flags=0,bool dirty=true,u64 reclaimed=1,size_t bytes=1){unsigned id=slot_images.size();slot_images.push_back({id,flags,dirty,bytes,reclaimed,0,&runtime});(void)lru_cache.Insert(id,0);}
 bool IsDownloadable(const Image&i){return i.dirty;}
 u64 ReclaimedBytes(const Image&i){return i.reclaimed;}
 void Run(bool current=false){
'''
tests=r'''
 PrefetchDownloads(current);
 }
};
int main(){
 {Cache c;for(unsigned n=0;n<60;++n)c.Add(unsigned(n%2?ImageFlagBits::IsDecoding:ImageFlagBits::CostlyLoad));for(unsigned n=0;n<30;++n)c.Add();c.Run();
  if(c.runtime.copied.size()!=20)return 10;
  assert(c.runtime.waits==1&&c.runtime.held.empty()&&c.runtime.copied.front()==60);}
 {Cache c;for(unsigned n=0;n<8192;++n)c.Add(unsigned(ImageFlagBits::IsDecoding));c.Add();c.Run();assert(c.runtime.copied.empty()&&c.runtime.held.empty());}
 {Cache c;for(unsigned n=0;n<5;++n)c.Add(0,false);for(unsigned n=0;n<30;++n)c.Add();c.Run();assert(c.runtime.copied.size()==15&&c.runtime.waits==1);}
 {Cache c;c.total_used_memory=5003;c.Add(0,false,2);c.Add(0,false,2);c.Add();c.Run();assert(c.runtime.copied.empty()&&c.runtime.waits==0);}
 {Cache c;c.num_iterations=0;c.Add();c.Run(true);assert(c.runtime.copied.size()==1&&c.runtime.waits==1);}
 {Cache c;c.Add(0,true,1,40_MiB);c.Add(0,true,1,40_MiB);c.Run();assert(c.runtime.copied.size()==1&&c.runtime.waits==1);}
 {Eden::Performance::gc_count_visits=true;Cache c;for(unsigned n=0;n<30;++n)c.Add(unsigned(ImageFlagBits::IsDecoding));c.Add();c.Run();assert(c.runtime.copied.empty());Eden::Performance::gc_count_visits=false;}
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d);cpp=p/'test.cpp';exe=p/'test';flags=['c++','-std=c++20','-D_GLIBCXX_DEBUG','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I'+str(engine/'src')]
 flags += ['-I'+str(inc) for inc in sorted((engine/'.cache/cpm/boost').glob('*/libs/*/include'))]
 cpp.write_text(fixture+s+tests);subprocess.run(flags+[str(cpp),'-o',str(exe)],check=True);subprocess.run([str(exe)],check=True)
 old=s.replace('''                if (::Eden::Performance::gc_count_visits.load(std::memory_order_relaxed)) {
                    --remaining;
                }''','                --remaining;',1).replace('''                if (!::Eden::Performance::gc_count_visits.load(std::memory_order_relaxed)) {
                    --remaining;
                }''','',1)
 assert old!=s;cpp.write_text(fixture+old+tests);subprocess.run(flags+[str(cpp),'-o',str(exe)],check=True);assert subprocess.run([str(exe)]).returncode==10
print('GC prefetch budget PASS: real lookahead/LRU, skipped prefix batching, bounded scans, clean eviction accounting, refill, byte limits and upstream control; old starvation reproduced (ASan/UBSan)')
