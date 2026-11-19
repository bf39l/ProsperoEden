#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the production shader-cache stream buffer across chunks/seeks/truncation."""
from pathlib import Path
import shutil,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
s=(root/'headless/shader_cache_reader.inc').read_text();a=s.index('class CacheFileBuffer final');b=s.index('\n};',a)+3
code=r'''
#include <array>
#include <cassert>
#include <cerrno>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <streambuf>
#include <vector>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
CLASS
int main(int argc,char** argv){
 assert(argc==2);std::filesystem::path path=argv[1];std::string data;
 for(int i=0;i<10000;++i)data+=char(i%251);
 for(auto piece:{1ul,7ul,13ul,64ul,4096ul,8ul<<20}){
  {std::ofstream out(path,std::ios::binary);out.write(data.data(),data.size());}
  CacheFileBuffer reader(piece);assert(reader.Open(path));
  std::ifstream in;static_cast<std::ios&>(in).rdbuf(&reader);in.exceptions(std::ios::failbit);
  assert(in.tellg()==0);std::string got(data.size(),' ');in.read(got.data(),got.size());assert(got==data);
  for(auto at:{0,1,12,100,4095,4096,9990}){
   in.seekg(at);assert(in.tellg()==at);std::array<char,7> part;in.read(part.data(),part.size());
   assert(std::string(part.data(),part.size())==data.substr(at,part.size()));
   in.seekg(-3,std::ios::cur);assert(in.tellg()==at+4);
  }
  in.seekg(-4,std::ios::end);assert(in.tellg()==9996);
  bool failed=false;try{in.seekg(10001);}catch(const std::ios_base::failure&){failed=true;}assert(failed);in.clear();
  failed=false;try{in.seekg(-1);}catch(const std::ios_base::failure&){failed=true;}assert(failed);in.clear();
  reader.Close();
 }
 std::filesystem::remove(path);
}
'''
with tempfile.TemporaryDirectory() as t:
 p=Path(t);(p/'check.cpp').write_text(code.replace('CLASS',s[a:b]))
 subprocess.run([shutil.which('clang++-21') or 'c++','-std=c++20','-fsanitize=address,undefined',str(p/'check.cpp'),'-o',str(p/'check')],check=True)
 subprocess.run([str(p/'check'),str(p/'cache.bin')],check=True,timeout=30)
print('Shader cache buffer PASS: initial tell, binary reads across every chunk boundary, backward/current/end seeks and invalid ranges (ASan/UBSan)')
