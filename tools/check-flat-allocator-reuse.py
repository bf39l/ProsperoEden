#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise the production flat allocator against an occupancy oracle."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
engine=Path(sys.argv[1])
code=r'''
#include <algorithm>
#include <array>
#include <cstdio>
#include <cassert>
#include <cstdint>
#include <iterator>
#include <limits>
#include <random>
#include <utility>
#include <vector>
#include "common/address_space.h"
#include "common/address_space.inc"
struct Alloc: Common::FlatAllocator<std::uint64_t,0,16>{
 using Base=Common::FlatAllocator<std::uint64_t,0,16>;using Base::Base;
 void Dump(){for(auto b:this->blocks)std::fprintf(stderr," block %llu mapped=%d\n",(unsigned long long)b.virt,b.Mapped());}
};
struct Mapping:Common::FlatAddressSpaceMap<std::uint64_t,0,std::uint64_t,0,true,16>{
    using Base=Common::FlatAddressSpaceMap<std::uint64_t,0,std::uint64_t,0,true,16>;using Base::Base;
    std::uint64_t Read(std::uint64_t address){
        auto it=std::upper_bound(this->blocks.begin(),this->blocks.end(),address,
            [](auto p,const auto& b){return p<b.virt;});assert(it!=this->blocks.begin());--it;
        return it->Mapped()?it->phys+address-it->virt:0;
    }
};
int main(int argc,char** argv){
    if(argc>1){
        if(argv[1][0]=='t'){
            Alloc a(16,256);a.Allocate(160);a.Allocate(64);a.Free(176,64);
            return a.Allocate(80)==176?0:10;
        }
        if(argv[1][0]=='f'){
            Alloc a(16,256);a.Allocate(16);a.AllocateFixed(48,80);a.AllocateFixed(144,16);
            return a.Allocate(64)==160?0:11;
        }
        Mapping m(256);m.Map(16,0x100,20);m.Map(36,0x200,20);m.Unmap(16,20);
        return m.Read(16)==0 && m.Read(36)==0x200?0:12;
    }
    {
        unsigned notifications=0;
        Mapping m(256,[&](auto,auto){++notifications;});
        m.Map(16,0x100,20);m.Map(36,0x200,20);m.Unmap(16,20);
        assert(m.Read(16)==0 && m.Read(35)==0 && m.Read(36)==0x200);
        assert(notifications==3);
        Mapping split(256);split.Map(16,0x100,40);split.Unmap(24,8);
        assert(split.Read(16)==0x100 && split.Read(23)==0x107);
        assert(split.Read(24)==0 && split.Read(31)==0);
        assert(split.Read(32)==0x110 && split.Read(55)==0x127);
    }
    {
        Alloc a(16,256);
        assert(a.Allocate(160)==16);assert(a.Allocate(64)==176);
        a.Free(176,64);
        if(a.Allocate(80)!=176)return 10; // Old search ignores free tail.
        assert(a.Allocate(1)==0);
    }
    {
        Alloc a(16,256);assert(a.Allocate(16)==16);
        a.AllocateFixed(48,80);a.AllocateFixed(144,16);
        auto p=a.Allocate(64);
        if(p!=160)return 11; // Old skip logic chooses occupied address48.
    }
    {
        Alloc a(16,256);assert(a.Allocate(0)==0);assert(a.Allocate(241)==0);
        for(int i=0;i<2000;++i){assert(a.Allocate(240)==16);assert(a.Allocate(1)==0);a.Free(16,240);}
    }
    {
        std::array<bool,256> occupied{};
        std::fill_n(occupied.begin(),16,true);
        std::vector<std::pair<unsigned,unsigned>> live;
        Alloc a(16,256);std::mt19937 random(0x48ff);
        for(unsigned i=0;i<20000;++i){
            if(!live.empty() && random()%3==0){
                auto index=random()%live.size();auto [p,n]=live[index];a.Free(p,n);
                std::fill_n(occupied.begin()+p,n,false);live.erase(live.begin()+index);continue;
            }
            unsigned n=random()%48+1;bool fits=false;
            for(unsigned p=16;p+n<=256;++p){
                if(std::none_of(occupied.begin()+p,occupied.begin()+p+n,[](bool b){return b;})){fits=true;break;}
            }
            auto p=a.Allocate(n);
            if(bool(p)!=fits){std::fprintf(stderr,"iteration=%u size=%u addr=%llu fits=%d\n",i,n,(unsigned long long)p,fits);a.Dump();for(auto [at,len]:live)std::fprintf(stderr," live %u+%u\n",at,len);}
            assert(bool(p)==fits);
            if(p){
                assert(p>=16 && p+n<=256);
                assert(std::none_of(occupied.begin()+p,occupied.begin()+p+n,[](bool b){return b;}));
                std::fill_n(occupied.begin()+p,n,true);live.emplace_back(p,n);
            }
        }
    }
    {
        // Actual SMMU width and the failed request size; no physical memory allocated.
        using Smmu=Common::FlatAllocator<std::uint64_t,0,34>;
        constexpr std::uint64_t limit=(1ull<<34)-1, mib=1ull<<20;
        Smmu a(4096,limit);const auto front=limit-4096-48*mib;
        assert(a.Allocate(front)==4096);
        const auto tail=a.Allocate(32*mib);assert(tail==4096+front);
        a.Free(tail,32*mib);assert(a.Allocate(32*mib)==tail);
    }
    {
        using Wide=Common::FlatAllocator<std::uint64_t,0,64>;
        constexpr auto max=std::numeric_limits<std::uint64_t>::max();
        Wide a(max-127,max-1);assert(a.Allocate(64)==max-127);
        assert(a.Allocate(64)==0);a.Free(max-127,64);assert(a.Allocate(126)==max-127);
    }
}
'''
with tempfile.TemporaryDirectory() as tmp:
    tmp=Path(tmp);common=tmp/'common';common.mkdir()
    for name in ['address_space.h','address_space.inc']:shutil.copyfile(engine/'src/common'/name,common/name)
    (common/'common_types.h').write_text('#pragma once\n#include <cstdint>\n')
    (common/'assert.h').write_text('#pragma once\n#include <cassert>\n#define ASSERT_MSG(condition, ...) assert(condition)\n')
    cpp=tmp/'test.cpp';cpp.write_text(code)
    def run(name):
        exe=tmp/name
        subprocess.run(['c++','-std=c++20','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-g','-I'+str(tmp),str(cpp),'-o',str(exe)],check=True)
        return subprocess.run([str(exe),*(['tail'] if name=='original' else [])],check=False).returncode
    assert run('fixed')==0
    patch=Path(__file__).resolve().parent/'eden-patches/48-flat-allocator-free-range-search.diff'
    (tmp/'src').mkdir();(tmp/'src/common').mkdir();shutil.copyfile(common/'address_space.inc',tmp/'src/common/address_space.inc')
    subprocess.run(['patch','--quiet','-R','-p1','-i',str(patch)],cwd=tmp,check=True)
    shutil.copyfile(tmp/'src/common/address_space.inc',common/'address_space.inc')
    assert run('original')==10
    # Reuse the compiled original for independent controls so each defect is proven.
    assert subprocess.run([str(tmp/'original'),'fixed'],check=False).returncode==11
    assert subprocess.run([str(tmp/'original'),'unmap'],check=False).returncode==12
print('Flat allocator reuse PASS: tail-only free space, fixed regions, 2000 full-space reuse cycles, 20000 occupancy checks, address overflow; generic unmap/contiguous-PA preservation and three original-defect controls reproduced (ASan/UBSan)')
