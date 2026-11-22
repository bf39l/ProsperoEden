#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Execute production shader environment reads with bounded mock GPU memory."""
from pathlib import Path
import subprocess,sys,tempfile
s=(Path(sys.argv[1])/'src/video_core/shader_environment.cpp').read_text()
def function(start):
    a=s.index(start);return s[a:s.index('\n}',a)+2]
methods='\n'.join(function(x) for x in ['Tegra::Texture::TICEntry GenericEnvironment::ReadTextureInfo(', 'u32 GraphicsEnvironment::ReadCbufValue(', 'u32 ComputeEnvironment::ReadCbufValue('])
fixture=r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <limits>
#include <map>
#include <stdexcept>
using u32=uint32_t;using u64=uint64_t;using GPUVAddr=u64;
#define ASSERT(x) assert(x)
#define LOG_ERROR(...) ((void)0)
namespace Shader{struct LogicError:std::runtime_error{template<class...T>LogicError(const char*s,T&&...):runtime_error(s){}};}
namespace Tegra::Texture{
struct TICEntry{u32 word;};
struct TexturePair{u32 first;TexturePair(u32 raw,bool):first(raw&0xfffff){}};
}
struct Memory{unsigned reads=0;u64 address=0;template<class T>T Read(u64 a){++reads;address=a;return T{42};}void ReadBlock(u64 a,void* p,unsigned n){++reads;address=a;assert(n==4);static_cast<Tegra::Texture::TICEntry*>(p)->word=42;}};
u64 MakeCbufKey(u32 i,u32 o){return u64{i}<<32|o;}
struct GenericEnvironment{Memory*gpu_memory;Tegra::Texture::TICEntry ReadTextureInfo(GPUVAddr,u32,bool,u32);};
struct Cbuf{bool enabled=true;u32 size=16;u64 address=0x10000;u64 Address()const{return address;}};
struct Graphics{struct{struct{std::array<Cbuf,18>const_buffers;}shader_stages[5];}state;};
struct Compute{struct{struct{u32 Value()const{return 255;}}const_buffer_enable_mask;std::array<Cbuf,8>const_buffer_config;}launch_description;};
struct GraphicsEnvironment{Graphics*maxwell3d;Memory*gpu_memory;unsigned stage_index=0;std::map<u64,u32>cbuf_values;u32 ReadCbufValue(u32,u32);};
struct ComputeEnvironment{Compute*kepler_compute;Memory*gpu_memory;std::map<u64,u32>cbuf_values;u32 ReadCbufValue(u32,u32);};
'''
tests=r'''
template<class F>void refused(F f){bool caught=false;try{f();}catch(const Shader::LogicError&){caught=true;}assert(caught);}
int main(){
Memory m;Graphics g;Compute c;GraphicsEnvironment ge{&g,&m,0,{}};ComputeEnvironment ce{&c,&m,{}};
assert(ge.ReadCbufValue(17,12)==42&&ce.ReadCbufValue(7,12)==42);
auto reads=m.reads;
for(u32 i:{18u,31u,std::numeric_limits<u32>::max()})refused([&]{ge.ReadCbufValue(i,0);});
for(u32 i:{8u,31u,32u,std::numeric_limits<u32>::max()})refused([&]{ce.ReadCbufValue(i,0);});
assert(m.reads==reads);
for(u32 offset:{13u,15u,16u,std::numeric_limits<u32>::max()}){assert(ge.ReadCbufValue(0,offset)==0);assert(ce.ReadCbufValue(0,offset)==0);}
assert(m.reads==reads);
GenericEnvironment env{&m};assert(env.ReadTextureInfo(0x20000,7,false,7).word==42);assert(m.address==0x2001c);
reads=m.reads;assert(env.ReadTextureInfo(0x20000,7,false,8).word==0);assert(m.reads==reads);
}
'''
with tempfile.TemporaryDirectory() as d:
    p=Path(d);cpp=p/'test.cpp';exe=p/'test';cpp.write_text(fixture+methods+tests)
    subprocess.run(['c++','-std=c++20','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(cpp),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('Shader environment bounds PASS: production graphics/compute/TIC reads, valid last entries, invalid banks and partial words, no GPU read on rejection (ASan/UBSan)')
