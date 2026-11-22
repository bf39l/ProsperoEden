#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Actual cache serializer/deserializer round trips and pre-allocation length guards."""
from pathlib import Path
import re,subprocess,sys,tempfile
root=Path(sys.argv[1]);s=(root/'src/video_core/shader_environment.cpp').read_text()
def function(signature):
 a=s.index(signature);b=s.index('{',a)+1;depth=1
 while depth:depth+=(s[b]=='{')-(s[b]=='}');b+=1
 return s[a:b]
serialize=function('void GenericEnvironment::Serialize(');deserialize=function('void FileEnvironment::Deserialize(')
a=s.index('void LoadPipelines(');loader=s[a:s.index('\n\n} // namespace VideoCommon',a)]
info=(root/'src/shader_recompiler/shader_info.h').read_text()
enums='\n'.join(re.search(r'enum class '+name+r'\b[^}]*};',info)[0] for name in ['TextureType','TexturePixelFormat','ReplaceConstant'])
fixture=r'''
#include <array>
#include <cerrno>
#include <cstdio>
#include <streambuf>
#include <system_error>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <cassert>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <functional>
#include <stop_token>
#include <limits>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>
#include "common/common_types.h"
#include "shader_recompiler/program_header.h"
#include "shader_recompiler/stage.h"
#undef LOG_ERROR
#undef LOG_INFO
#define LOG_ERROR(...) ((void)0)
#define LOG_INFO(...) ((void)0)
namespace Common{template<class R,class...T>using UniqueFunction=std::function<R(T...)>;namespace FS{bool RemoveFile(const std::filesystem::path&p){return std::filesystem::remove(p);}std::string PathToUTF8String(const std::filesystem::path&p){return p.string();}}}
namespace Maxwell{constexpr size_t MaxShaderProgram=6;}
constexpr std::array<char,8>MAGIC_NUMBER{'y','u','z','u','c','a','c','h'};
namespace Shader{
'''+enums+r'''
}
struct Fields{
 std::map<u32,Shader::TextureType>texture_types;
 std::map<u32,Shader::TexturePixelFormat>texture_pixel_formats;
 std::map<u64,u32>cbuf_values;std::map<u64,Shader::ReplaceConstant>cbuf_replacements;
 std::array<u32,3>workgroup_size{};std::array<u32,8>gp_passthrough_mask{};
 Shader::ProgramHeader sph{};Shader::Stage stage{};
 u32 local_memory_size=0,texture_bound=0,start_address=0,viewport_transform_state=1,shared_memory_size=0,initial_offset=0;
 bool is_proprietary_driver=false;
};
struct GenericEnvironment:Fields{
 std::vector<u64>code;u32 cached_lowest=0,cached_highest=0;
 size_t CachedSizeBytes()const{return size_t(cached_highest)-cached_lowest+8;}
 void Serialize(std::ofstream&)const;
};
struct FileEnvironment:Fields{
 struct Code:std::vector<u64>{unsigned resizes=0;void resize(size_t n){++resizes;std::vector<u64>::resize(n);}}code;
 u32 read_lowest=0,read_highest=0;
 Shader::Stage ShaderStage()const{return stage;}
 void Deserialize(std::ifstream&,std::streampos);
};
std::filesystem::path file;
std::string Encode(GenericEnvironment&env){
 {std::ofstream out(file,std::ios::binary);env.Serialize(out);}
 std::ifstream in(file,std::ios::binary);return std::string(std::istreambuf_iterator<char>(in),{});
}
void Save(const std::string&bytes){std::ofstream out(file,std::ios::binary);out.write(bytes.data(),bytes.size());}
void Read(FileEnvironment&env){std::ifstream in(file,std::ios::binary|std::ios::ate);in.exceptions(std::ios::failbit|std::ios::badbit);auto end=in.tellg();in.seekg(0);env.Deserialize(in,end);}
bool RefusedBeforeAllocation(const std::string&bytes){Save(bytes);FileEnvironment env;bool caught=false;try{Read(env);}catch(const std::ios_base::failure&){caught=true;}return caught&&env.code.resizes==0;}
void Set64(std::string&bytes,size_t at,u64 word){std::memcpy(bytes.data()+at,&word,8);}void Set32(std::string&bytes,size_t at,u32 word){std::memcpy(bytes.data()+at,&word,4);}
'''
tests=r'''
int main(int argc,char**argv){assert(argc==2);file=argv[1];GenericEnvironment env;
 env.texture_types[5]=Shader::TextureType::Color2D;env.texture_pixel_formats[7]=Shader::TexturePixelFormat::A8B8G8R8_UNORM;
 env.cbuf_values[0x100000010]=42;env.cbuf_replacements[0x200000020]=Shader::ReplaceConstant::BaseVertex;
 env.workgroup_size={8,4,2};env.gp_passthrough_mask.fill(17);env.texture_bound=2;env.local_memory_size=64;env.shared_memory_size=256;
 std::string original;
 for(auto stage:{Shader::Stage::VertexA,Shader::Stage::VertexB,Shader::Stage::TessellationControl,Shader::Stage::TessellationEval,Shader::Stage::Geometry,Shader::Stage::Fragment,Shader::Stage::Compute}){
  env.stage=stage;env.code.assign(stage==Shader::Stage::Compute?2:12,0x123456789abcdef0ULL);env.cached_lowest=0x1000;env.cached_highest=0x1000+env.code.size()*8-8;env.start_address=0x1000;
  auto bytes=Encode(env);Save(bytes);FileEnvironment decoded;Read(decoded);
  assert(std::vector<u64>(decoded.code)==env.code&&decoded.stage==stage&&decoded.texture_types==env.texture_types&&decoded.texture_pixel_formats==env.texture_pixel_formats&&decoded.cbuf_values==env.cbuf_values&&decoded.cbuf_replacements==env.cbuf_replacements);
  assert(decoded.read_lowest==env.cached_lowest&&decoded.read_highest==env.cached_highest&&decoded.is_proprietary_driver);
  if(stage==Shader::Stage::Compute){assert(decoded.workgroup_size==env.workgroup_size&&decoded.shared_memory_size==env.shared_memory_size&&decoded.initial_offset==0);original=bytes;}
  if(stage==Shader::Stage::Geometry)assert(decoded.gp_passthrough_mask==env.gp_passthrough_mask);
 }
 // Consistent but impossible payload length: old reader allocated8MiB before EOF.
 auto damaged=original;Set64(damaged,0,8*1024*1024);Set32(damaged,56,0x1000+8*1024*1024-8);
 if(!RefusedBeforeAllocation(damaged))return 20;
 for(size_t at:{8u,16u,24u,32u}){damaged=original;Set64(damaged,at,std::numeric_limits<u64>::max());assert(RefusedBeforeAllocation(damaged));}
 damaged=original;Set64(damaged,0,std::numeric_limits<u64>::max());assert(RefusedBeforeAllocation(damaged));
 damaged=original;Set32(damaged,64,99);assert(RefusedBeforeAllocation(damaged));
 damaged=original;Set32(damaged,56,0);assert(RefusedBeforeAllocation(damaged));
 damaged=original;Set64(damaged,0,17);assert(RefusedBeforeAllocation(damaged));
 for(size_t cut=0;cut<original.size();++cut)assert(RefusedBeforeAllocation(original.substr(0,cut)));
 // A later key/record must remain unread; no extra seek or format/version change.
 Save(original+std::string("TAIL",4));{std::ifstream in(file,std::ios::binary|std::ios::ate);in.exceptions(std::ios::failbit);auto end=in.tellg();in.seekg(0);FileEnvironment decoded;decoded.Deserialize(in,end);assert(in.tellg()==std::streampos(original.size()));std::array<char,4>tail;in.read(tail.data(),4);assert(std::string(tail.data(),4)=="TAIL");}
 // The real loader catches an invalid payload and uses its existing cache rebuild path.
 auto CacheBytes=[&](const std::string&payload){std::string data(MAGIC_NUMBER.data(),8);u32 version=123,count=1;data.append(reinterpret_cast<char*>(&version),4);data.append(reinterpret_cast<char*>(&count),4);data+=payload;data.push_back('K');return data;};
 unsigned loaded=0;auto compute=[&](std::ifstream&in,FileEnvironment){char key;in.read(&key,1);assert(key=='K');++loaded;};auto graphics=[](std::ifstream&,std::vector<FileEnvironment>){assert(false);};
 Save(CacheBytes(original));LoadPipelines({},file,123,compute,graphics);assert(loaded==1&&std::filesystem::exists(file));
 damaged=original;Set64(damaged,0,8*1024*1024);Set32(damaged,56,0x1000+8*1024*1024-8);Save(CacheBytes(damaged));LoadPipelines({},file,123,compute,graphics);assert(loaded==1&&!std::filesystem::exists(file));
 // No new arbitrary shader-size limit: preserve a valid record over1MiB.
 env.code.assign(131074,0x1234);env.cached_highest=env.cached_lowest+env.code.size()*8-8;auto large=Encode(env);Save(large);FileEnvironment decoded;Read(decoded);assert(decoded.code.size()==env.code.size());
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d);cpp=p/'test.cpp';exe=p/'test';cpp.write_text(fixture+serialize+deserialize+loader+tests)
 flags=['c++','-std=c++23','-D_GLIBCXX_DEBUG','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-fsanitize=address,undefined','-I'+str(root/'src')]
 flags += ['-I'+str(inc) for inc in sorted((root/'.cache/cpm/boost').glob('*/libs/*/include'))]
 subprocess.run(flags+[str(cpp),'-o',str(exe)],check=True);subprocess.run([str(exe),str(p/'cache.bin')],check=True)
 a=deserialize.index('    // Validate against the writer');b=deserialize.index('    code.resize(',a)
 old=deserialize[:a]+deserialize[b:];cpp.write_text(fixture+serialize+old+loader+tests)
 subprocess.run(flags+[str(cpp),'-o',str(exe)],check=True);assert subprocess.run([str(exe),str(p/'cache.bin')]).returncode==20
 port=(Path(__file__).resolve().parents[1]/'headless/shader_cache_reader.inc').read_text()
 port_tests=tests.replace('assert(loaded==1&&!std::filesystem::exists(file));', 'assert(loaded==1&&std::filesystem::file_size(file)==12);')
 port_tests=port_tests.replace(' // No new arbitrary shader-size limit:', ' damaged=original;Set64(damaged,8,100);Save(damaged);{std::ifstream in(file,std::ios::binary|std::ios::ate);in.exceptions(std::ios::failbit);auto end=in.tellg();in.seekg(0);CheckEnvironment(in,static_cast<std::streamoff>(end));FileEnvironment decoded;bool caught=false;try{decoded.Deserialize(in,end);}catch(const std::ios_base::failure&){caught=true;}assert(caught&&decoded.code.resizes==0); }\n // No new arbitrary shader-size limit:')
 port_tests=port_tests.replace(' // No new arbitrary shader-size limit:', ' Save(CacheBytes(original)+CacheBytes(damaged).substr(12));shader_cache_chunk_bytes=7;LoadPipelines({},file,123,compute,graphics);assert(loaded==2&&std::filesystem::file_size(file)==CacheBytes(original).size());\n // No new arbitrary shader-size limit:')
 cpp.write_text(fixture+serialize+deserialize+port+port_tests)
 subprocess.run(flags+[str(cpp),'-o',str(exe)],check=True);subprocess.run([str(exe),str(p/'cache.bin')],check=True)
print('Shader cache payload PASS: actual writer/reader, seven stages and metadata, every compute truncation, overflowing counts and oversized lengths refused before allocation; old allocation reproduced (ASan/UBSan)')
