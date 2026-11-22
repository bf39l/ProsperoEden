#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise real synchronous download/iteration code across separate GPU allocations."""
from pathlib import Path
import subprocess,sys,tempfile
engine=Path(sys.argv[1])
s=(engine/'src/video_core/buffer_cache/buffer_cache.h').read_text()
base=(engine/'src/video_core/buffer_cache/buffer_cache_base.h').read_text()
def function(text,signature):
 a=text.index(signature);b=text.index('{',a)+1;depth=1
 while depth:
  depth+=(text[b]=='{')-(text[b]=='}');b+=1
 return text[a:b]
download=function(s,'void BufferCache<P>::DownloadBufferMemory(Buffer& buffer, DAddr device_addr, u64 size)')
flush=function(s,'void BufferCache<P>::DownloadMemory(DAddr device_addr, u64 size)')
iterate=function(base,'void ForEachBufferInRange(DAddr device_addr, u64 size, Func&& func)')
a=download.index('    // A CPU flush may span several independent cache allocations.')
b=download.index('    boost::container::small_vector<BufferCopy, 1> copies;',a)
old=download[:a]+download[b:]
fixture=r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cstring>
#include <optional>
#include <set>
#include <span>
#include <vector>
#include <boost/container/small_vector.hpp>
#include "common/range_sets.inc"
#include "common/div_ceil.h"
using DAddr=u64;using BufferId=unsigned;
struct BufferCopy{u64 src_offset,dst_offset,size;};
struct Buffer {
 DAddr base{};std::vector<u8> bytes;
 DAddr CpuAddr()const{return base;} u64 SizeBytes()const{return bytes.size();}
 void MarkUsage(u64,u64){}
};
struct Tracker {
 std::set<u64> dirty_pages;unsigned queries=0;
 template<class F> void ForEachDownloadRangeAndClear(u64 at,u64 size,F fn){
  ++queries;assert(size>0);
  for(u64 page=at/4096;page<(at+size+4095)/4096;++page)
   if(dirty_pages.erase(page))fn(page*4096,4096);
 }
};
struct Memory {
 std::vector<u8> bytes=std::vector<u8>(0x50000,0x77);
 void WriteBlockUnsafe(DAddr at,const u8* data,u64 size){
  assert(at<=bytes.size()&&size<=bytes.size()-at);std::copy_n(data,size,bytes.begin()+at);
 }
};
struct Runtime {
 Buffer staging;bool invalid=false;unsigned copies=0,waits=0;
 struct Stage {Buffer& buffer;std::span<u8> mapped_span;u64 offset;};
 Stage DownloadStagingBuffer(u64 size){staging.bytes.resize(size+64);return {staging,std::span<u8>(staging.bytes).subspan(64),64};}
 void CopyBuffer(Buffer& dst,Buffer& src,std::span<const BufferCopy> jobs,bool){
  for(auto c:jobs){
   if(c.src_offset>src.bytes.size()||c.size>src.bytes.size()-c.src_offset||
      c.dst_offset>dst.bytes.size()||c.size>dst.bytes.size()-c.dst_offset){invalid=true;continue;}
   std::copy_n(src.bytes.begin()+c.src_offset,c.size,dst.bytes.begin()+c.dst_offset);++copies;
  }
 }
 void Finish(){++waits;}
};
struct Policy{using Buffer=::Buffer;};
template<class P> struct BufferCache {
 using Buffer=typename P::Buffer;
 static constexpr unsigned CACHING_PAGEBITS=16;
 static constexpr u64 CACHING_PAGESIZE=1ull<<CACHING_PAGEBITS;
 static constexpr bool USE_MEMORY_MAPS=true;
 std::array<unsigned,5> page_table{0,1,0,2,0};
 std::array<Buffer,3> slot_buffers;
 Tracker memory_tracker;Common::RangeSet<DAddr> gpu_modified_ranges;
 Runtime runtime;Memory device_memory;
 std::vector<std::pair<DAddr,u64>> cleared;
 void ClearDownload(DAddr at,u64 size){cleared.emplace_back(at,size);}
 std::span<u8> ImmediateBuffer(u64){return {};}
 void DownloadBufferMemory(Buffer&,DAddr,u64);
 void DownloadMemory(DAddr,u64);
 template<class Func>
'''
fixture+=iterate+r'''
 BufferCache(){
  slot_buffers[1].base=0x10000;slot_buffers[1].bytes.assign(0x10000,0xa1);
  slot_buffers[2].base=0x30000;slot_buffers[2].bytes.assign(0x10000,0xb2);
 }
 void Dirty(u64 at,u64 size){gpu_modified_ranges.Add(at,size);for(u64 page=at/4096;page<(at+size+4095)/4096;++page)memory_tracker.dirty_pages.insert(page);}
};
'''
tests=r'''
int main(){
 // Real page-table iterator encounters two allocations with an unmapped gap.
 {
  BufferCache<Policy> c;c.Dirty(0x1fff0,16);c.Dirty(0x30000,16);
  c.DownloadMemory(0x1fff0,0x10020);
  if(c.runtime.invalid)return 10; // unpatched engine forms a copy beyond buffer 1
  assert(c.runtime.copies==2&&c.runtime.waits==2&&c.memory_tracker.queries==2);
  for(unsigned i=0;i<16;++i){assert(c.device_memory.bytes[0x1fff0+i]==0xa1);assert(c.device_memory.bytes[0x30000+i]==0xb2);}
  assert(c.device_memory.bytes[0x20000]==0x77&&c.gpu_modified_ranges.Empty());
 }
 // No intersection or empty input must not consume someone else's tracker bits.
 {
  BufferCache<Policy> c;c.Dirty(0x30000,16);
  c.DownloadBufferMemory(c.slot_buffers[1],0x30000,16);
  c.DownloadBufferMemory(c.slot_buffers[1],0,0x10000);
  c.DownloadBufferMemory(c.slot_buffers[1],0x18000,0);
  assert(c.memory_tracker.queries==0&&c.memory_tracker.dirty_pages.contains(0x30));
 }
 // Prefix/suffix clipping must precede tracker iteration. A huge requested size
 // cannot overflow an end-address computation or escape the actual allocation.
 {
  BufferCache<Policy> c;c.Dirty(0x10000,8);c.Dirty(0x1fff8,8);c.Dirty(0x30000,8);
  c.DownloadBufferMemory(c.slot_buffers[1],0,~u64{0});
  assert(!c.runtime.invalid&&c.runtime.copies==2&&c.memory_tracker.dirty_pages.contains(0x30));
  assert(c.device_memory.bytes[0x10000]==0xa1&&c.device_memory.bytes[0x1ffff]==0xa1);
  assert(c.device_memory.bytes[0x30000]==0x77);
 }
 // Direct downloads into the later allocation must not subtract an earlier
 // dirty address from its base or consume the earlier allocation's tracking.
 {
  BufferCache<Policy> c;c.Dirty(0x1fff0,16);c.Dirty(0x30000,16);
  c.DownloadBufferMemory(c.slot_buffers[2],0x1fff0,0x10020);
  assert(!c.runtime.invalid&&c.runtime.copies==1);
  assert(c.memory_tracker.dirty_pages.contains(0x1f));
  assert(c.device_memory.bytes[0x1fff0]==0x77&&c.device_memory.bytes[0x30000]==0xb2);
 }
 // Ordinary single-buffer partial reads keep the existing page-granular behavior.
 {
  BufferCache<Policy> c;c.Dirty(0x18010,8);c.DownloadBufferMemory(c.slot_buffers[1],0x18011,1);
  assert(!c.runtime.invalid&&c.runtime.copies==1&&c.device_memory.bytes[0x18010]==0xa1);
 }
}
'''
boost=sorted((engine/'.cache/cpm/boost').glob('*/libs/*/include'))
with tempfile.TemporaryDirectory() as scratch:
 p=Path(scratch)
 for label,body,expected in [('fixed',download,0),('old-unbounded',old,10)]:
  cpp=p/(label+'.cpp');exe=p/label
  cpp.write_text(fixture+'\ntemplate<class P>\n'+flush+'\ntemplate<class P>\n'+body+tests)
  subprocess.run(['c++','-std=c++20','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
   '-I'+str(engine/'src'),*['-I'+str(b) for b in boost],str(cpp),'-o',str(exe)],check=True)
  result=subprocess.run([str(exe)]);assert result.returncode==expected,(label,result.returncode)
  print(label+' PASS',flush=True)
print('Download bounds PASS: production download and cache iterator, multiple allocations/gap, tracker preservation, empty/disjoint/huge requests, page-granular reads and old-code out-of-bounds reproduction (ASan/UBSan)')
