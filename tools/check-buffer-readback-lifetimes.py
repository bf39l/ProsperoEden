#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run production readback retirement/cancellation with the real engine interval sets.

No GPU required: staging bytes and guest memory are controlled. Old-path negative
controls prove the two regressions rather than asserting the patch's spelling.
"""
from pathlib import Path
import subprocess,sys,tempfile
root=Path(__file__).resolve().parents[1]
engine=Path(sys.argv[1])
source=(engine/'src/video_core/buffer_cache/buffer_cache.h').read_text()
def function(signature):
    a=source.index(signature);b=source.index('{',a)+1;depth=1
    while depth:
        depth+=(source[b]=='{')-(source[b]=='}');b+=1
    return source[a:b]
clear=function('void BufferCache<P>::ClearDownload(')
pop=function('void BufferCache<P>::PopAsyncBuffers()')
# Reconstruct only the old behaviors as controls; execute the same tests against them.
old_clear='''void BufferCache<P>::ClearDownload(DAddr device_addr,u64 size) {
 async_downloads.DeleteAll(device_addr,size);
 uncommitted_gpu_modified_ranges.Subtract(device_addr,size);
 for(auto& ranges:committed_gpu_modified_ranges) ranges.Subtract(device_addr,size);
}'''
old_pop=pop
start=old_pop.index('            for (const auto& pending : committed_gpu_modified_ranges) {')
end=old_pop.index('            settled.ForEach(',start)
old_pop=old_pop[:start]+old_pop[end:]
fixture=r"""
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <optional>
#include <span>
#include <vector>
#include "common/range_sets.inc"
using DAddr=std::uint64_t;
struct BufferCopy {u64 src_offset,dst_offset,size;};
struct Async_Buffer {std::span<u8> mapped_span;u64 offset;};
struct Memory {
 std::array<u8,256> bytes{};unsigned writes=0;
 void WriteBlockUnsafe(DAddr at,const u8* data,u64 size){
  assert(at<=bytes.size()&&size<=bytes.size()-at);
  std::copy_n(data,size,bytes.begin()+at);++writes;
 }
};
template<class P> struct BufferCache {
 Common::OverlapRangeSet<DAddr> async_downloads;
 Common::RangeSet<DAddr> gpu_modified_ranges,uncommitted_gpu_modified_ranges;
 std::deque<Common::RangeSet<DAddr>> committed_gpu_modified_ranges;
 std::deque<std::vector<BufferCopy>> pending_downloads;
 std::deque<std::optional<Async_Buffer>> async_buffers;
 std::deque<Async_Buffer> async_buffers_death_ring;
 std::deque<std::array<u8,256>> storage;
 Memory device_memory;
 void ClearDownload(DAddr,u64);
 void PopAsyncBuffers();
 void Queue(DAddr at,u64 size,u8 value,u64 staging_offset=16){
  assert(staging_offset+size<=256);storage.emplace_back();auto& data=storage.back();
  std::fill_n(data.begin(),size,value);
  pending_downloads.push_back({{at,staging_offset,size}});
  async_buffers.push_back(Async_Buffer{std::span<u8>(data),staging_offset});
  async_downloads.Add(at,size);gpu_modified_ranges.Add(at,size);
 }
 bool Dirty(DAddr at,u64 size){bool yes=false;gpu_modified_ranges.ForEachInRange(at,size,[&](auto,auto){yes=true;});return yes;}
 int Pending(DAddr at){int n=0;async_downloads.ForEachInRange(at,1,[&](auto,auto,int count){n=count;});return n;}
};
"""
tests=r"""
int main(){
 // Full cancellation must remove A's copy even when B reuses exactly its address.
 {
  BufferCache<int> c;c.Queue(32,16,0xa1);c.ClearDownload(32,16);c.Queue(32,16,0xb2,48);
  c.device_memory.bytes.fill(0x77);c.PopAsyncBuffers();
  if(c.device_memory.writes!=0||c.Pending(32)!=1||!c.Dirty(32,16))return 10;
  c.PopAsyncBuffers();assert(c.device_memory.bytes[32]==0xb2&&!c.Dirty(32,16));
 }
 // Partial cancellation splits a copy, preserving offsets into the original staging allocation.
 {
  BufferCache<int> c;c.Queue(32,16,0xa1,24);c.ClearDownload(36,4);c.Queue(36,4,0xb2,40);
  for(unsigned i=0;i<16;++i)c.storage.front()[i]=0xa0+i;
  c.device_memory.bytes.fill(0x77);c.PopAsyncBuffers();
  assert(c.device_memory.bytes[32]==0xa0&&c.device_memory.bytes[35]==0xa3);
  assert(c.device_memory.bytes[36]==0x77&&c.device_memory.bytes[39]==0x77);
  assert(c.device_memory.bytes[40]==0xa8&&c.device_memory.bytes[47]==0xaf);
  assert(c.Pending(36)==1&&c.Dirty(36,4));c.PopAsyncBuffers();assert(c.device_memory.bytes[36]==0xb2);
 }
 // Old A completes while B is committed but has not yet obtained its own staging copy.
 {
  BufferCache<int> c;c.Queue(64,16,0xa1);c.committed_gpu_modified_ranges.emplace_back();
  c.committed_gpu_modified_ranges.back().Add(68,4);c.PopAsyncBuffers();
  if(!c.Dirty(68,4))return 20;
  assert(!c.Dirty(64,4)&&!c.Dirty(72,8));
  c.committed_gpu_modified_ranges.clear();c.Queue(68,4,0xb2);c.PopAsyncBuffers();assert(!c.Dirty(68,4));
 }
 // Uncommitted rewrites remain dirty too; no overlap settles normally.
 {
  BufferCache<int> c;c.Queue(80,8,0xa1);c.uncommitted_gpu_modified_ranges.Add(82,2);
  c.PopAsyncBuffers();assert(c.Dirty(82,2)&&!c.Dirty(80,2)&&!c.Dirty(84,4));
 }
 // Two active downloads: retiring the older one must not retire the newer one.
 {
  BufferCache<int> c;c.Queue(96,8,0xa1);c.Queue(96,8,0xb2);
  c.PopAsyncBuffers();assert(c.Pending(96)==1&&c.Dirty(96,8));
  c.PopAsyncBuffers();assert(!c.Dirty(96,8)&&c.device_memory.bytes[96]==0xb2);
 }
 // Cancel across multiple queued copies, including edge overlaps and empty completions.
 {
  BufferCache<int> c;c.async_buffers.emplace_back(std::nullopt);c.Queue(16,16,0xa1);c.Queue(32,16,0xb2);
  c.ClearDownload(24,16);c.device_memory.bytes.fill(0x77);c.PopAsyncBuffers();
  c.PopAsyncBuffers();c.PopAsyncBuffers();assert(c.device_memory.bytes[16]==0xa1);
  for(int i=24;i<40;++i)assert(c.device_memory.bytes[i]==0x77);
  assert(c.device_memory.bytes[40]==0xb2&&c.async_downloads.Empty());
  c.ClearDownload(0,0);c.ClearDownload(200,1);c.PopAsyncBuffers();
 }
}
"""
# Use cached Boost modules; do not download dependencies in the regression test.
boost=sorted((engine/'.cache/cpm/boost').glob('*/libs/*/include'))
include=['-I'+str(engine/'src'),*['-I'+str(p) for p in boost]]
with tempfile.TemporaryDirectory() as scratch:
    p=Path(scratch)
    for label,clear_fn,pop_fn,expected in (
        ('fixed',clear,pop,0),('old-cancellation',old_clear,pop,10),('old-retirement',clear,old_pop,20)):
        cpp=p/(label+'.cpp');exe=p/label
        cpp.write_text(fixture+'\ntemplate<class P>\n'+clear_fn+'\ntemplate<class P>\n'+pop_fn+tests)
        subprocess.run(['c++','-std=c++20','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
            *include,str(cpp),'-o',str(exe)],check=True)
        result=subprocess.run([str(exe)])
        assert result.returncode==expected,(label,result.returncode,expected)
        print(label+' PASS',flush=True)
print('Readback lifetimes PASS: real interval containers, cancel/requeue, partial splits, multiple staging batches, committed/uncommitted rewrites, zero/null cases and old-code negative controls (ASan/UBSan)')
