#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Test production sparse backing/heap guards and allocation lookup boundaries."""
from pathlib import Path
import subprocess,sys,tempfile
root=Path(sys.argv[1]);s=(root/'src/core/hle/service/nvdrv/devices/nvhost_as_gpu.cpp').read_text()
a=s.index('            const u64 backing_offset');b=s.index('            DAddr base',a);backing=s[a:b]
a=s.index('        auto alloc{allocation_map.upper_bound(virtual_address)};');b=s.index('        if (!alloc->second.sparse)',a);lookup=s[a:b]
h=(root/'src/core/hle/service/nvdrv/core/heap_mapper.h').read_text();a=h.index('    bool IsInBounds');b=h.index('\n    DAddr Map',a);heap=h[a:b]
fixture=r'''
#include <cassert>
#define LOG_ERROR(...) ((void)0)
#include <cstdint>
#include <limits>
#include <map>
using u64=uint64_t;using VAddr=u64;
enum class NvResult{Success,BadValue};
#define LOG_WARNING(...) ((void)0)
struct Entry{unsigned handle_offset_big_pages;};struct Handle{u64 orig_size;u64 aligned_size;};
NvResult Backing(Entry entry,Handle*handle,u64 size){struct{unsigned big_page_size_bits=16;}vm;
'''+backing+r'''
return NvResult::Success;
}
struct Heap{VAddr m_vaddress;u64 m_size;
'''+heap+r'''
};
struct Alloc{u64 size;};
NvResult Lookup(std::map<u64,Alloc>& allocation_map,u64 virtual_address,u64 size){
'''+lookup+r'''
return NvResult::Success;
}
int main(){
Handle h{0x3f001,0x40000};if(Backing({1},&h,0x30000)!=NvResult::Success)return 10;
assert(Backing({3},&h,0x10000)==NvResult::Success);
assert(Backing({2},&h,0x30000)==NvResult::BadValue);
assert(Backing({5},&h,0)==NvResult::BadValue);
assert(Backing({1},&h,std::numeric_limits<u64>::max())==NvResult::BadValue);
std::map<u64,Alloc> a;assert(Lookup(a,0,1)==NvResult::BadValue);
a[0x10000]={0x40000};assert(Lookup(a,0,1)==NvResult::BadValue);
assert(Lookup(a,0x20000,0x30000)==NvResult::Success);
assert(Lookup(a,0x20000,0x30001)==NvResult::BadValue);
assert(Lookup(a,0x20000,std::numeric_limits<u64>::max())==NvResult::BadValue);
Heap heap{0x10000,0x40000};assert(heap.IsInBounds(0x20000,0x30000));
assert(!heap.IsInBounds(0x20000,std::numeric_limits<u64>::max()));
assert(!heap.IsInBounds(0xffff,1));assert(!heap.IsInBounds(0x50001,0));
}
'''
with tempfile.TemporaryDirectory() as d:
    p=Path(d);(p/'test.cpp').write_text(fixture)
    subprocess.run(['c++','-std=c++20','-D_GLIBCXX_DEBUG','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(p/'test.cpp'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True)
    (p/'test.cpp').write_text(fixture.replace('handle->aligned_size','handle->orig_size'))
    subprocess.run(['c++','-std=c++20','-D_GLIBCXX_DEBUG','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(p/'test.cpp'),'-o',str(p/'test')],check=True)
    assert subprocess.run([str(p/'test')]).returncode==10

print('Sparse remap bounds PASS: production source/heap guards, empty and lower-bound allocation lookups, exact-end ranges and overflowing lengths (debug iterators, ASan/UBSan)')
