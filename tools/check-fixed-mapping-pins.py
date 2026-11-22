#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise actual fixed-map ownership transfer and its old-code pin-leak control."""
from pathlib import Path
import subprocess,sys,tempfile
engine=Path(sys.argv[1]);s=(engine/'src/core/hle/service/nvdrv/devices/nvhost_as_gpu.cpp').read_text()
a=s.index('        // A fixed map can replace the record at the same GPU address.')
b=s.index('\n    } else {',a);block=s[a:b]
end=block.index('        mapping_map.insert_or_assign(')
old='        alloc->second.mappings.push_back(params.offset);\n'+block[end:]
fixture=r'''
#include <cassert>
#include <cstdint>
#include <map>
#include <vector>
using u32=std::uint32_t;using u64=std::uint64_t;
struct Mapping{
 unsigned handle;u64 ptr,offset,size;bool fixed,big_page,sparse_alloc;
 Mapping(unsigned h,u64 p,u64 o,u64 n,bool f,bool b,bool sp):handle(h),ptr(p),offset(o),size(n),fixed(f),big_page(b),sparse_alloc(sp){}
};
struct Allocation{std::vector<u64> mappings;bool sparse=false;};
struct Pins{
 std::map<unsigned,int> refs;
 void UnpinHandle(unsigned h){assert(refs[h]>0);--refs[h];}
};
struct Params{unsigned handle;u64 offset;};
struct Cache {
 std::map<u64,Mapping> mapping_map;std::map<u64,Allocation> allocation_map{{0x40000,{}}};Pins nvmap;
 void Replace(unsigned handle,u64 offset=0x40000){
  // The production path has successfully pinned and GMMU-mapped the replacement
  // before the ownership bookkeeping below. Failed pins never reach this point.
  ++nvmap.refs[handle];auto alloc=allocation_map.begin();Params params{handle,offset};
  u64 device_address=0x100000+u64(handle)*0x10000,size=65536;bool use_big_pages=true;
'''
tests=r'''
 }
};
int main(){
 Cache c;
 for(unsigned n=0;n<1000;++n)c.Replace(1+n%5);
 if(c.nvmap.refs[1]!=0||c.nvmap.refs[5]!=1)return 10;
 for(unsigned h=1;h<5;++h)assert(c.nvmap.refs[h]==0);
 assert(c.mapping_map.size()==1&&c.allocation_map.begin()->second.mappings.size()==1);
 // Replacing the same handle consumes a new pin and retires exactly the old one.
 c.Replace(5);assert(c.nvmap.refs[5]==1);
 // Another GPU mapping of that handle owns an independent pin.
 c.Replace(5,0x50000);assert(c.nvmap.refs[5]==2&&c.mapping_map.size()==2);
 assert(c.allocation_map.begin()->second.mappings.size()==2);
 // The ordinary FreeSpace loop must encounter each owned mapping once.
 for(auto offset:c.allocation_map.begin()->second.mappings){
  auto it=c.mapping_map.find(offset);assert(it!=c.mapping_map.end());
  c.nvmap.UnpinHandle(it->second.handle);c.mapping_map.erase(it);
 }
 assert(c.mapping_map.empty()&&c.nvmap.refs[5]==0);
}
'''
with tempfile.TemporaryDirectory() as scratch:
 p=Path(scratch)
 for label,body,expected in [('fixed',block,0),('old-pin-leak',old,10)]:
  cpp=p/(label+'.cpp');exe=p/label;cpp.write_text(fixture+body+tests)
  subprocess.run(['c++','-std=c++20','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(cpp),'-o',str(exe)],check=True)
  v=subprocess.run([str(exe)]);assert v.returncode==expected,(label,v.returncode)
  print(label+' PASS',flush=True)
print('Fixed mapping pins PASS: actual ownership block, 1000 replacements, same/different handle, independent mappings, unique FreeSpace entries and old-code pin leak (ASan/UBSan)')
