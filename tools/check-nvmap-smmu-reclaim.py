#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run real NvMap pin/unmap code against a bounded SMMU and real mutex/list fixtures."""
from pathlib import Path
import subprocess,sys,tempfile
engine=Path(sys.argv[1])
s=(engine/'src/core/hle/service/nvdrv/core/nvmap.cpp').read_text()
def function(signature):
 a=s.index(signature);b=s.index('{',a)+1;depth=1
 while depth:
  depth+=(s[b]=='{')-(s[b]=='}');b+=1
 return s[a:b]
pin=function('DAddr NvMap::PinHandle(');unmap=function('void NvMap::UnmapHandle(')
a=pin.index('                // Choose under the queue lock,')
b=pin.index('\n            }',a)
old=pin[:a]+'''                std::scoped_lock queueLock(unmap_queue_lock);
                if (auto freeHandleDesc{unmap_queue.front()}) {
                    std::scoped_lock freeLock(freeHandleDesc->mutex);
                    if (handle_description->d_address)
                        UnmapHandle(*freeHandleDesc);
                } else { LOG_CRITICAL(Service_NVDRV,"Ran out of SMMU address space!"); }
'''+pin[b:]
fixture=r'''
#include <atomic>
#include <cassert>
#include <chrono>
#include <cstdint>
#include <functional>
#include <list>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <thread>
using u32=std::uint32_t;using u64=std::uint64_t;using DAddr=u64;using VAddr=u64;using GPUVAddr=u64;
constexpr std::size_t BIG_PAGE_SIZE=65536;
namespace Common{std::size_t AlignUp(std::size_t n,std::size_t align){return (n+align-1)&~(align-1);}}
std::atomic<unsigned> errors{};
#define LOG_ERROR(...) ++errors
#define LOG_CRITICAL(...) ++errors
struct RetryLimit{};
struct QueueMutex {
 std::mutex mutex;std::atomic<unsigned> acquired{};
 void lock(){mutex.lock();++acquired;}void unlock(){mutex.unlock();}
 bool try_lock(){if(!mutex.try_lock())return false;++acquired;return true;}
};
struct Smmu {
 std::mutex mutex;u64 available=0,next=0x200000;
 std::atomic<unsigned> attempts{},frees{},maps{};
 DAddr Allocate(u64 bytes){std::lock_guard lock(mutex);if(++attempts>64)throw RetryLimit{};
  if(bytes>available){return 0;}
  available-=bytes;auto out=next;next+=bytes;return out;}
 void Free(DAddr at,u64 bytes){std::lock_guard lock(mutex);assert(at!=0);available+=bytes;++frees;}
 void Map(DAddr,VAddr,u64,unsigned,bool){++maps;}
 void Unmap(DAddr,u64){}
};
struct LowAllocator{u32 Allocate(u32){return 0x10000;}void Free(u64,u32){}};
struct Gmmu{void Map(GPUVAddr,DAddr,u64){}void Unmap(GPUVAddr,u64){}};
struct Host {
 Smmu smmu;LowAllocator low;Gmmu gmmu_manager;
 Smmu& MemoryManager(){return smmu;}LowAllocator& Allocator(){return low;}
};
struct Mapper{bool IsInBounds(VAddr,u64){return true;}DAddr Map(VAddr,u64){return 0x900000;}void Unmap(VAddr,u64){}};
struct Session{bool has_preallocated_area=false;Mapper actual;Mapper* mapper=&actual;unsigned asid=1;};
struct Core {Session session;Session* GetSession(unsigned){return &session;}};
struct NvMap {
 struct Handle {
  using Id=unsigned;
  std::mutex mutex;u64 aligned_size=BIG_PAGE_SIZE,address=0x800000;DAddr d_address=0,pin_virt_address=0;
  unsigned session_id=1;long pins=0;bool in_heap=false;
  std::optional<std::list<std::shared_ptr<Handle>>::iterator> unmap_queue_entry;
 };
 Host host1x;Core core;std::map<unsigned,std::shared_ptr<Handle>> handles;
 std::list<std::shared_ptr<Handle>> unmap_queue;QueueMutex unmap_queue_lock;
 std::shared_ptr<Handle> GetHandle(unsigned id){auto i=handles.find(id);return i==handles.end()?nullptr:i->second;}
 std::shared_ptr<Handle> Add(unsigned id){auto h=std::make_shared<Handle>();handles.emplace(id,h);return h;}
 std::shared_ptr<Handle> Reusable(unsigned id,DAddr address=0x100000){auto h=Add(id);h->d_address=address;
  unmap_queue.push_back(h);h->unmap_queue_entry=std::prev(unmap_queue.end());return h;}
 DAddr PinHandle(Handle::Id,bool low_area_pin=false);void UnmapHandle(Handle&);
};
'''
tests=r'''
int main(){
 // The new handle is unmapped. Reclaim must check the OLD candidate's address.
 {
  NvMap c;auto request=c.Add(1);auto victim=c.Reusable(2);
  DAddr result=0;try{result=c.PinHandle(1);}catch(const RetryLimit&){return 10;}
  assert(result!=0&&request->pins==1&&request->d_address==result);
  assert(victim->d_address==0&&!victim->unmap_queue_entry&&c.unmap_queue.empty());
  assert(c.host1x.smmu.frees==1&&c.host1x.smmu.attempts==2&&c.host1x.smmu.maps==1);
 }
 // True exhaustion returns failure without spinning, incrementing pins or mapping zero.
 {
  NvMap c;auto request=c.Add(1);auto before=errors.load();
  assert(c.PinHandle(1)==0&&request->pins==0&&request->d_address==0);
  assert(c.host1x.smmu.attempts==1&&c.host1x.smmu.maps==0&&errors==before+1);
 }
 // Empty stale mappings cannot obstruct reclamation of a usable later entry.
 {
  NvMap c;c.Add(1);auto stale=c.Reusable(2,0);auto victim=c.Reusable(3);
  assert(c.PinHandle(1)!=0&&!stale->unmap_queue_entry&&victim->d_address==0);
  assert(c.host1x.smmu.frees==1&&c.unmap_queue.empty());
 }
 // Existing queued mapping reuse and low-area pins keep their old fast path.
 {
  NvMap c;auto h=c.Reusable(1);assert(c.PinHandle(1,true)==0x10000);
  assert(h->pins==1&&!h->unmap_queue_entry&&c.host1x.smmu.attempts==0);
  assert(c.PinHandle(1)==0x100000&&h->pins==2&&c.host1x.smmu.attempts==0);
 }
 // Preallocated heap mapping and invalid IDs still use their original paths.
 {
  NvMap c;auto h=c.Add(1);c.core.session.has_preallocated_area=true;
  assert(c.PinHandle(1)==0x900000&&h->in_heap&&h->pins==1&&c.host1x.smmu.attempts==0);
  assert(c.PinHandle(77)==0);
 }
 // A candidate can be repinned while the allocator waits for its handle mutex.
 // The worker must release the queue mutex while waiting, then revalidate it.
 {
  NvMap c;c.Add(1);auto victim=c.Reusable(2);std::unique_lock held(victim->mutex);
  DAddr result=99;std::thread worker([&]{result=c.PinHandle(1);});
  auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(2);
  while(c.unmap_queue_lock.acquired<2&&std::chrono::steady_clock::now()<deadline)std::this_thread::yield();
  assert(c.unmap_queue_lock.acquired>=2);
  bool got_queue=false;
  while(!(got_queue=c.unmap_queue_lock.try_lock())&&std::chrono::steady_clock::now()<deadline)std::this_thread::yield();
  assert(got_queue);
  c.unmap_queue.erase(*victim->unmap_queue_entry);victim->unmap_queue_entry.reset();victim->pins=1;
  c.unmap_queue_lock.unlock();held.unlock();worker.join();
  assert(result==0&&victim->d_address==0x100000&&c.host1x.smmu.frees==0);
 }
}
'''
with tempfile.TemporaryDirectory() as scratch:
 p=Path(scratch)
 for label,body,expected in [('fixed',pin,0),('old-wrong-handle',old,10)]:
  cpp=p/(label+'.cpp');exe=p/label;cpp.write_text(fixture+unmap+body+tests)
  subprocess.run(['c++','-std=c++20','-Wall','-Wextra','-Werror','-pthread','-fsanitize=address,undefined',str(cpp),'-o',str(exe)],check=True)
  v=subprocess.run([str(exe)],timeout=10);assert v.returncode==expected,(label,v.returncode)
  print(label+' PASS',flush=True)
print('NvMap SMMU reclaim PASS: real PinHandle/UnmapHandle, reclaim/retry, bounded exhaustion, stale entries, low/heap fast paths, concurrent repin revalidation and old-code livelock control (ASan/UBSan)')
