#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compile actual Maxwell Decode: invalid words fail, valid encodings remain unchanged."""
from pathlib import Path
import subprocess,sys,tempfile
root=Path(sys.argv[1]);s=(root/'src/shader_recompiler/frontend/maxwell/decode.cpp').read_text()
code=r'''
#include <cassert>
#include <cstdint>
#include "shader_recompiler/frontend/maxwell/decode.h"
#include "shader_recompiler/exception.h"
using namespace Shader::Maxwell;
int main(){
// Every canonical encoding from the real decode table remains decodable.
#define INST(name,cute,encoding) {const char* p=encoding;u64 word=0;u64 bit=u64{1}<<63;for(unsigned i=0;i<20;++i){if(p[i]=='1')word|=bit;if(p[i]=='1'||p[i]=='0'||p[i]=='-')bit>>=1;}(void)Decode(word);}
#include "shader_recompiler/frontend/maxwell/maxwell.inc"
#undef INST
// Observed in FF's invalid-instruction reports; none is a supported opcode.
for(u64 word:{0ULL,0xffffffffffffffffULL}){
 bool rejected=false;try{(void)Decode(word);}catch(const Shader::LogicError&){rejected=true;}
 if(!rejected)return 10;
}
for(u64 word:{0x4cffffff00ffffffULL,0x4cffffffffffffffULL,0x00ffffffffffffULL,0x5dffff00ffffffffULL})assert(Decode(word)==Opcode::NOP);
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d);(p/'common').mkdir();(p/'shader_recompiler').mkdir()
 (p/'common/assert.h').write_text('#pragma once\n#define ASSERT_MSG(...) ((void)0)\n')
 # Isolate logging/formatting dependencies; the production decoder is unmodified.
 (p/'shader_recompiler/exception.h').write_text('#pragma once\n#include <stdexcept>\nnamespace Shader{struct LogicError:std::runtime_error{template<class...T>LogicError(const char*s,T&&...):runtime_error(s){}};}\n')
 cpp=p/'test.cpp';decoder=p/'decode.cpp';exe=p/'test';cpp.write_text(code);decoder.write_text(s)
 flags=['c++','-std=c++23','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I'+str(p),'-I'+str(root/'src'),'-I'+str(root/'src/shader_recompiler/frontend/maxwell')]
 subprocess.run(flags+[str(cpp),str(decoder),'-o',str(exe)],check=True);subprocess.run([str(exe)],check=True)
 # The exact previous fallback accepted invalid words as NOPs.
 old=s.replace('throw Shader::LogicError("Invalid Maxwell instruction {:#016x}", insn);','return Opcode::NOP;');assert old!=s;decoder.write_text(old)
 subprocess.run(flags+[str(cpp),str(decoder),'-o',str(exe)],check=True);assert subprocess.run([str(exe)]).returncode==10
print('Shader invalid instructions PASS: actual decoder, real canonical instruction table, observed invalid FF words rejected; old NOP fallback reproduced (ASan/UBSan)')
