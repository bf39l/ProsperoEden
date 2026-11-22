#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Original shader failure survives secondary diagnostic failures."""
from pathlib import Path
import subprocess,sys,tempfile
s=(Path(sys.argv[1])/'src/video_core/renderer_vulkan/vk_pipeline_cache.cpp').read_text()
a=s.index('} catch (const Shader::Exception& exception) {',s.index('CreateGraphicsPipeline'));b=s.index('\n}',a)
body=s[a:b+2]
assert 'Flow::CFG' not in body
fixture=r'''
#include <array>
#include <cassert>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
using u32=unsigned;
std::vector<std::string> messages;
#define LOG_ERROR(category,format,arg) messages.emplace_back(arg)
namespace Shader{struct Exception:std::runtime_error{using runtime_error::runtime_error;};struct Environment{int calls=0;bool fail=false;void Dump(unsigned,unsigned){++calls;if(fail)throw Exception("dump failed");}};}
namespace Maxwell{constexpr unsigned MaxShaderProgram=3;}
struct Key{std::array<unsigned,3>unique_hashes{1,0,2};unsigned Hash(){return 42;}};
std::unique_ptr<int> Build(Key key,std::array<Shader::Environment*,2>envs)try{throw Shader::Exception("original shader failure");
'''
test=r'''
int main(){Shader::Environment a,b;a.fail=true;auto p=Build({}, {&a,&b});assert(!p);assert(a.calls==1&&b.calls==1);assert(messages.size()==2&&messages[0]=="original shader failure"&&messages[1]=="dump failed");}
'''
with tempfile.TemporaryDirectory() as d:
    p=Path(d);(p/'test.cpp').write_text(fixture+body+test)
    subprocess.run(['c++','-std=c++20','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(p/'test.cpp'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True)
print('Shader error reporting PASS: production handler retains original failure, isolates failed dumps, continues remaining dumps and returns null (ASan/UBSan)')
