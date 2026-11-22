#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise the actual sampled-buffer descriptor merge and key predicate."""
from pathlib import Path
import subprocess,sys,tempfile
engine=Path(sys.argv[1]);s=(engine/'src/shader_recompiler/ir_opt/texture_pass.cpp').read_text()
def function(signature):
 a=s.index(signature);b=s.index('{',a)+1;depth=1
 while depth:depth+=(s[b]=='{')-(s[b]=='}');b+=1
 return s[a:b]
method=function('    u32 Add(const TextureBufferDescriptor& desc)')
helper=function('    template <typename Descriptors, typename Descriptor, typename Func>')
code=r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <vector>
using u32=std::uint32_t;
struct TextureBufferDescriptor {
 u32 cbuf_index=0,cbuf_offset=0,shift_left=0,secondary_cbuf_index=0,secondary_cbuf_offset=0,
 secondary_shift_left=0,count=1,size_shift=0,mask=0,secondary_mask=0;
 bool has_secondary=false,is_integer=false;
};
struct Descriptors {
 std::vector<TextureBufferDescriptor> texture_buffer_descriptors;
'''+method+helper+r'''
};
int main(){
 for(bool first:{false,true}){
  Descriptors d;TextureBufferDescriptor a;a.is_integer=first;
  assert(d.Add(a)==0);a.is_integer=!first;assert(d.Add(a)==0);
  if(!d.texture_buffer_descriptors[0].is_integer)return 10;
  a.is_integer=false;assert(d.Add(a)==0 && d.texture_buffer_descriptors[0].is_integer);
  a.cbuf_offset=4;assert(d.Add(a)==1 && !d.texture_buffer_descriptors[1].is_integer);
  a.mask=15;assert(d.Add(a)==2);a.secondary_mask=255;assert(d.Add(a)==3);
 }
}
'''
with tempfile.TemporaryDirectory() as tmp:
 tmp=Path(tmp);cpp=tmp/'merge.cpp';exe=tmp/'merge'
 def run(text):
  cpp.write_text(text)
  subprocess.run(['c++','-std=c++20','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(cpp),'-o',str(exe)],check=True)
  return subprocess.run([str(exe)],check=False).returncode
 assert run(code)==0
 assert run(code.replace('texture_buffer_descriptors[index].is_integer |= desc.is_integer;',''))==10
print('Texel descriptor merge PASS: production merge, either integer declaration order, distinct cbuf/masks; original lost-metadata control reproduced')
