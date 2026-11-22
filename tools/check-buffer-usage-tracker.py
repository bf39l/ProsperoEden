#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Test the real usage tracker and upload ordering with short and unaligned ranges."""
from pathlib import Path
import os,subprocess,sys,tempfile
root=Path(sys.argv[1]);repo=Path(__file__).resolve().parents[1]
s=(root/'src/video_core/renderer_vulkan/vk_buffer_cache.cpp').read_text()
a=s.index('bool BufferCacheRuntime::CanReorderUpload(');b=s.index('\nvoid BufferCacheRuntime::CopyBuffer',a);ordering=s[a:b]
code=r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <limits>
#include <random>
#include <span>
#include <vector>
#include "video_core/buffer_cache/usage_tracker.h"
namespace Settings{inline struct{bool disable_buffer_reorder=false;}values;}
namespace VideoCommon{struct BufferCopy{u64 src_offset,dst_offset,size;};}
struct Buffer{VideoCommon::UsageTracker tracker{16384};bool IsRegionUsed(u64 at,u64 n)const{return tracker.IsUsed(at,n);}};
struct BufferCacheRuntime{bool CanReorderUpload(const Buffer&,std::span<const VideoCommon::BufferCopy>);};
'''+ordering+r'''
int main(){
using VideoCommon::UsageTracker;
// Actual 12-byte indirect dispatch arguments must prevent overlapping uploads.
Buffer buffer;BufferCacheRuntime runtime;buffer.tracker.Track(64,12);
std::array<VideoCommon::BufferCopy,1> copies{{{0,64,12}}};
assert(!runtime.CanReorderUpload(buffer,copies));copies[0].dst_offset=128;assert(runtime.CanReorderUpload(buffer,copies));
// Every touched unit is tracked, even a two-byte straddle of a 64-byte boundary.
UsageTracker t(16384);t.Track(63,2);assert(t.IsUsed(0,1)&&t.IsUsed(64,1));assert(!t.IsUsed(128,1));
t.Reset();t.Track(4095,2);assert(t.IsUsed(4095,1)&&t.IsUsed(4096,1)&&!t.IsUsed(0,1));
t.Reset();t.Track(64,64);assert(!t.IsUsed(128,1));assert(!t.IsUsed(0,1));
t.Track(0,0);assert(!t.IsUsed(0,0));assert(t.IsUsed(std::numeric_limits<u64>::max()-2,10));
// Compare production masks with independent byte-to-unit coverage across pages.
std::mt19937 random(0xFF);std::array<bool,256> reference{};
for(unsigned batch=0;batch<1000;++batch){
 t.Reset();reference.fill(false);
 for(unsigned n=0;n<12;++n){
  u64 at=random()%16384,length=random()%(16385-at);t.Track(at,length);
  for(u64 pos=at;pos<at+length;++pos)reference[pos/64]=true;
 }
 for(unsigned n=0;n<64;++n){
  u64 at=random()%16384,length=random()%(16385-at);bool expected=false;
  for(u64 pos=at;pos<at+length;++pos)expected|=reference[pos/64];
  assert(t.IsUsed(at,length)==expected);
 }
}
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d);cpp=p/'test.cpp';exe=p/'test';cpp.write_text(code)
 flags=['c++','-std=c++20','-Wall','-Wextra','-Werror','-fsanitize=address,undefined']
 subprocess.run(flags+['-I'+str(root/'src'),str(cpp),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
 # Reconstruct the exact pre-patch header and demonstrate its undefined shift.
 old=p/'old/src/video_core/buffer_cache';old.mkdir(parents=True)
 (old/'usage_tracker.h').write_text((root/'src/video_core/buffer_cache/usage_tracker.h').read_text())
 for patch in reversed(sorted((repo/'tools/eden-patches').glob('*.diff'))):
  if patch.name < '39-': continue
  parts=patch.read_text().split('--- a/')
  relevant=''.join('--- a/'+part for part in parts[1:] if part.startswith('src/video_core/buffer_cache/usage_tracker.h\n'))
  if relevant:
   subprocess.run(['patch','-s','-R','-p1','-d',str(p/'old')],input=relevant,text=True,check=True)
 subprocess.run(flags+['-I'+str(p/'old/src'),'-I'+str(root/'src'),str(cpp),'-o',str(exe)],check=True)
 result=subprocess.run([str(exe)],env={**os.environ,'UBSAN_OPTIONS':'halt_on_error=1'},capture_output=True,text=True)
 assert result.returncode!=0 and 'shift exponent 64' in result.stderr,result.stderr
print('Buffer usage tracker PASS: real masks/upload ordering, 12-byte arguments, unit/page straddles, 64000 randomized queries; original header reproduces undefined shift (ASan/UBSan)')
