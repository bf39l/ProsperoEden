#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Actual cache dispatch and bounds guards, including all six graphics inputs."""
from pathlib import Path
import re,subprocess,sys,tempfile
root=Path(sys.argv[1]);source=(root/'src/video_core/shader_environment.cpp').read_text()
def function(text,start):
 a=text.index(start);b=text.index('{',a)+1;depth=1
 while depth:depth+=(text[b]=='{')-(text[b]=='}');b+=1
 return text[a:b]
# Include the function-try-block handler as well as its body.
a=source.index('void LoadPipelines(');loader=source[a:source.index('\n\n} // namespace VideoCommon',a)]
read=function(source,'u64 FileEnvironment::ReadInstruction(')
a=source.index('    if (initial_offset >= code.size_bytes())');dump_guard=source[a:source.index('    const auto dump_dir',a)]
vk=(root/'src/video_core/renderer_vulkan/vk_pipeline_cache.cpp').read_text();gl=(root/'src/video_core/renderer_opengl/gl_shader_cache.cpp').read_text()
a=vk.index('        const size_t expected_envs');end=vk.index('\n        }',a)+len('\n        }');key_guard=vk[a:end]
assert key_guard in gl
vector_line=next(l.strip() for l in vk.splitlines() if 'static_vector<Shader::Environment*' in l)
assert vector_line in gl and 'Maxwell::MaxShaderProgram' in vector_line
# Also exercise the loader the PS5 port actually generates, not just raw Eden.
derived = root.parent/'native-local/headless/vk_pipeline_cache_cost.cpp'
if derived.exists():
 port = derived.read_text(); a=port.index('    auto load_graphics{'); b=port.index('    // Reads the file',a); actual=port[a:b]
 start=actual.index('        const auto expected_envs'); end=actual.index('\n        }',start)+len('\n        }')
 key_guard=actual[start:end]
 assert actual.index('expected_envs != envs.size()') < actual.index('loader->Note(') < actual.index('workers.QueueWork(')
 vector_line=next(l.strip() for l in actual.splitlines() if 'static_vector<Shader::Environment*' in l)
 assert 'Maxwell::MaxShaderProgram' in vector_line

count=int(re.search(r'MaxShaderProgram = (\d+)',(root/'src/video_core/engines/maxwell_3d.h').read_text())[1]);assert count==6
fixture=r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <filesystem>
#include <fstream>
#include <functional>
#include <span>
#include <stdexcept>
#include <stop_token>
#include <vector>
#include <boost/container/static_vector.hpp>
#include "common/common_types.h"
#include "shader_recompiler/stage.h"
#define LOG_ERROR(...) ((void)0)
#define LOG_INFO(...) ((void)0)
namespace Common{template<class R,class...T>using UniqueFunction=std::function<R(T...)>;namespace FS{bool RemoveFile(const std::filesystem::path&p){return std::filesystem::remove(p);}}}
namespace Shader{struct Environment{};struct LogicError:std::runtime_error{template<class...T>LogicError(const char*s,T&&...):runtime_error(s){}};}
namespace Maxwell{constexpr size_t MaxShaderProgram=6;}
constexpr std::array<char,8>MAGIC_NUMBER{'y','u','z','u','c','a','c','h'};
struct FileEnvironment:Shader::Environment{
 Shader::Stage stage=Shader::Stage::VertexB;u32 read_lowest=0,read_highest=0;std::vector<u64>code;
 void Deserialize(std::ifstream&f,std::streampos){f.read(reinterpret_cast<char*>(&stage),sizeof(stage));}
 Shader::Stage ShaderStage()const{return stage;}
 u64 ReadInstruction(u32);
};
void ValidateDump(std::span<const u64>code,u32 initial_offset){
'''+dump_guard+r'''
}
void ValidateKey(std::span<FileEnvironment>envs,unsigned mask){struct{std::array<u64,6>unique_hashes{};}key;for(unsigned n=0;n<6;++n)key.unique_hashes[n]=(mask>>n)&1;
'''+key_guard+r'''
}
void CollectPointers(std::span<FileEnvironment>envs){
'''+vector_line+r'''
 for(auto&env:envs){env_ptrs.push_back(&env);}
 assert(env_ptrs.size()==envs.size());
}
'''
tests=r'''
void Write(const std::filesystem::path&p,u32 count,Shader::Stage stage,unsigned mask){std::ofstream f(p,std::ios::binary);u32 version=123;f.write(MAGIC_NUMBER.data(),8);f.write(reinterpret_cast<char*>(&version),4);f.write(reinterpret_cast<char*>(&count),4);if(count<=6)for(unsigned n=0;n<count;++n){std::array<Shader::Stage,6>stages{Shader::Stage::VertexA,Shader::Stage::VertexB,Shader::Stage::TessellationControl,Shader::Stage::TessellationEval,Shader::Stage::Geometry,Shader::Stage::Fragment};auto current=stage==Shader::Stage::Compute?stage:stages[n];f.write(reinterpret_cast<char*>(&current),4);}u8 key=mask;f.write(reinterpret_cast<char*>(&key),1);}
int main(int argc,char**argv){assert(argc==2);auto file=std::filesystem::path(argv[1]);unsigned compute=0,graphics=0;
 auto lc=[&](std::ifstream&f,FileEnvironment){u8 key;f.read(reinterpret_cast<char*>(&key),1);++compute;};
 auto lg=[&](std::ifstream&f,std::vector<FileEnvironment>envs){u8 key;f.read(reinterpret_cast<char*>(&key),1);ValidateKey(envs,key);CollectPointers(envs);++graphics;};
 // A valid six-input pipeline exceeds the previous static_vector capacity of five.
 Write(file,6,Shader::Stage::VertexB,63);LoadPipelines({},file,123,lc,lg);if(graphics!=1)return 10;assert(std::filesystem::exists(file));
 Write(file,1,Shader::Stage::Compute,1);LoadPipelines({},file,123,lc,lg);assert(compute==1);
 for(u32 n:{0u,7u,0xffffffffu}){Write(file,n,Shader::Stage::VertexB,1);LoadPipelines({},file,123,lc,lg);assert(graphics==1&&compute==1&&!std::filesystem::exists(file));}
 Write(file,2,Shader::Stage::Compute,1);LoadPipelines({},file,123,lc,lg);assert(compute==1&&!std::filesystem::exists(file));
 Write(file,1,Shader::Stage::VertexB,63);LoadPipelines({},file,123,lc,lg);assert(graphics==1&&!std::filesystem::exists(file));
 FileEnvironment env;env.read_highest=16;env.code={42};assert(env.ReadInstruction(0)==42);bool caught=false;try{env.ReadInstruction(8);}catch(const Shader::LogicError&){caught=true;}assert(caught);
 std::array<u64,2>bytes{};ValidateDump(bytes,8);caught=false;try{ValidateDump(bytes,16);}catch(const Shader::LogicError&){caught=true;}assert(caught);caught=false;try{ValidateDump({},0);}catch(const Shader::LogicError&){caught=true;}assert(caught);
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d);cpp=p/'test.cpp';exe=p/'test';cpp.write_text(fixture+read+loader+tests)
 flags=['c++','-std=c++20','-D_GLIBCXX_DEBUG','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I'+str(root/'src')]
 flags += ['-I'+str(inc) for inc in sorted((root/'.cache/cpm/boost').glob('*/libs/*/include'))]
 subprocess.run(flags+[str(cpp),'-o',str(exe)],check=True);subprocess.run([str(exe),str(p/'cache.bin')],check=True)
 # Old five-entry capacity rejects the valid six-environment record.
 cpp.write_text((fixture+read+loader+tests).replace(vector_line,'boost::container::static_vector<Shader::Environment*, 5> env_ptrs;'))
 subprocess.run(flags+[str(cpp),'-o',str(exe)],check=True)
 result=subprocess.run([str(exe),str(p/'cache.bin')],capture_output=True,text=True);assert result.returncode!=0
print('Shader cache bounds PASS: actual loader/key/read/dump guards, six-input graphics and compute, invalid counts/key mismatch, real static_vector; old five-entry overflow reproduced (ASan/UBSan)')
