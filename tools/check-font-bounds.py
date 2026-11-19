#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the generated font-copy admission guard at malformed/overflow boundaries."""
from pathlib import Path
import subprocess,tempfile,shutil
root=Path(__file__).resolve().parents[1]
scratch=Path((root/'.local/headless-cache').read_text().strip())
s=(scratch/'native-local/headless/platform_service_manager.cpp').read_text()
a=s.index('        const auto font_bytes = font_fp->GetSize();')
b=s.index('        std::vector<u32> font_data_u32(font_bytes / sizeof(u32));',a)
guard=s[a:b]
code=r'''
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <vector>
using u32=std::uint32_t;
constexpr std::size_t SHARED_FONT_MEM_SIZE=64;
constexpr int EMPTY_REGION=0;
#define LOG_ERROR(...)
struct File {std::size_t size;std::size_t GetSize(){return size;}};
struct Impl{std::vector<int> shared_font_regions;};
bool accepted(std::size_t size,std::size_t offset){
 File f{size};auto* font_fp=&f;Impl obj;auto* impl=&obj;
 for(int once=0;once<1;++once){
 GUARD
 return true;
 }
 assert(obj.shared_font_regions==std::vector<int>{EMPTY_REGION});return false;
}
int main(){
 assert(accepted(8,0));assert(accepted(64,0));assert(accepted(8,56));
 for(auto size:{std::size_t{0},1ul,4ul,7ul,9ul,65ul,68ul,std::numeric_limits<std::size_t>::max()})assert(!accepted(size,0));
 assert(!accepted(8,60));assert(!accepted(8,64));assert(!accepted(8,65));
 assert(!accepted(8,std::numeric_limits<std::size_t>::max()));
}
'''
with tempfile.TemporaryDirectory() as t:
 p=Path(t);(p/'check.cpp').write_text(code.replace('GUARD',guard))
 subprocess.run([shutil.which('clang++-21') or 'c++','-std=c++20','-fsanitize=address,undefined',str(p/'check.cpp'),'-o',str(p/'check')],check=True)
 subprocess.run([str(p/'check')],check=True)
print('Shared fonts PASS: empty, short, unaligned, oversized and overflowing ranges rejected before reading/copying; valid exact-fit retained')
