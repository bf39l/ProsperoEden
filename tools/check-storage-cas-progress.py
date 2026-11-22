#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate production subword-store SPIR-V and execute its retry loop under contention."""
from pathlib import Path
import concurrent.futures
import shutil
import struct
import subprocess
import sys
import tempfile
engine=Path(sys.argv[1]); cpm=engine/'.cache/cpm'
sirit=next((cpm/'sirit').glob('*/include/sirit/sirit.h')).parents[2]
headers=next((cpm/'spirv-headers').glob('*/include/spirv/unified1/spirv.hpp11')).parents[2]
source=(engine/'src/shader_recompiler/backend/spirv/spirv_emit_context.cpp').read_text()
sig='void EmitContext::DefineWriteStorageCasLoopFunction('
a=source.index(sig); pos=source.index('{',a)+1; depth=1
while depth:
    depth+=(source[pos]=='{')-(source[pos]=='}');pos+=1
method=source[a:pos]
a=source.index('Id CasLoop(');pos=source.index('{',a)+1;depth=1
while depth:
    depth+=(source[pos]=='{')-(source[pos]=='}');pos+=1
cas_loop=source[a:pos]
preamble=r'''
#include <array>
#include <cstdint>
#include <fstream>
#include <sirit/sirit.h>
using Sirit::Id; using u32=std::uint32_t;
enum class Operation { Increment };
struct Info {bool uses_int8=true,uses_int16=true;};
struct EmitContext: Sirit::Module {
    struct {bool support_int8=false,support_int16=false;} profile;
    bool uses_explicit_workgroup_layout=false;
    std::array<Id,3> F32; Id shared_memory_u32{};
    std::array<Id,2> U32; Id U1,void_id,u32_zero_value,write_storage_cas_loop_func{};
    EmitContext():Sirit::Module(0x00010300){
        AddCapability(spv::Capability::Shader);
        SetMemoryModel(spv::AddressingModel::Logical,spv::MemoryModel::GLSL450);
        void_id=TypeVoid();U1=TypeBool();U32[1]=TypeInt(32,false);u32_zero_value=Const(0);
        F32[1]=TypeFloat(32);F32[2]=TypeVector(F32[1],2);
    }
    Id Const(u32 v){return Constant(U32[1],v);}
    void DefineWriteStorageCasLoopFunction(const Info&);
};
'''
cas_stub=r'''
Id CasFunction(EmitContext& c,Operation,Id type){
    auto f=c.OpFunction(type,spv::FunctionControlMask::MaskNone,c.TypeFunction(type,type,type));
    auto a=c.OpFunctionParameter(type);auto b=c.OpFunctionParameter(type);c.AddLabel();
    c.OpReturnValue(c.OpIAdd(type,a,b));c.OpFunctionEnd();return f;
}
'''
main=r'''
int main(int argc,char** argv){
    EmitContext c;
    c.DefineWriteStorageCasLoopFunction(Info{});
    auto array=c.TypeRuntimeArray(c.U32[1]); c.Decorate(array,spv::Decoration::ArrayStride,4u);
    auto block=c.TypeStruct(array);c.Decorate(block,spv::Decoration::Block);
    c.MemberDecorate(block,0,spv::Decoration::Offset,0u);
    auto global=c.AddGlobalVariable(c.TypePointer(spv::StorageClass::StorageBuffer,block),spv::StorageClass::StorageBuffer);
    c.Decorate(global,spv::Decoration::DescriptorSet,0u);c.Decorate(global,spv::Decoration::Binding,0u);
    auto retry=CasLoop(c,Operation::Increment,c.TypePointer(spv::StorageClass::StorageBuffer,block),
        c.TypePointer(spv::StorageClass::StorageBuffer,c.U32[1]),c.U32[1],c.U32[1],spv::Scope::Device);
    auto entry=c.OpFunction(c.void_id,spv::FunctionControlMask::MaskNone,c.TypeFunction(c.void_id));c.AddLabel();
    auto pointer=c.OpAccessChain(c.TypePointer(spv::StorageClass::StorageBuffer,c.U32[1]),global,c.Const(0),c.Const(0));
    c.OpFunctionCall(c.void_id,c.write_storage_cas_loop_func,pointer,c.Const(0x7f),c.Const(8),c.Const(8));
    c.OpFunctionCall(c.U32[1],retry,c.Const(0),c.Const(1),global);
    c.OpReturn();c.OpFunctionEnd();
    c.AddEntryPoint(spv::ExecutionModel::GLCompute,entry,"main");
    c.AddExecutionMode(entry,spv::ExecutionMode::LocalSize,1u,1u,1u);
    auto words=c.Assemble();std::ofstream out(argv[1],std::ios::binary);
    out.write(reinterpret_cast<const char*>(words.data()),words.size()*4);
}
'''
# Interpret the helper instructions actually emitted by Sirit, with a stale plain-load
# cache and a competing write before the first CAS. Atomic loads bypass that cache.
def execute(words, offset, count, insert, contender):
    ops=[];at=5
    while at<len(words):
        n=words[at]>>16; op=words[at]&65535
        ops.append((op,list(words[at+1:at+n])));at+=n
    values={args[1]:args[2] for op,args in ops if op==43 and len(args)==3}
    start=next(i for i,(op,_) in enumerate(ops) if op==54)
    end=next(i for i in range(start+1,len(ops)) if ops[i][0]==56)
    body=ops[start:end];labels={args[0]:i for i,(op,args) in enumerate(body) if op==248}
    params=[args[1] for op,args in body if op==55]
    values.update(zip(params,[0x1000,insert,offset,count]))
    memory=0x12345678;cached=memory^0x01000000; raced=False;cas=0;pc=0
    for step in range(300):
        op,x=body[pc];pc+=1
        if op==61:values[x[1]]=cached
        elif op==227:values[x[1]]=memory # OpAtomicLoad
        elif op==201:
            base,val,off,bits=(values[v] for v in x[2:]);mask=((1<<bits)-1)<<off
            values[x[1]]=(base&~mask)|((val<<off)&mask)
        elif op==230:
            if contender and not raced:memory^=0x01010101;raced=True
            cas+=1;actual=memory
            if actual==values[x[7]]:memory=values[x[6]]
            values[x[1]]=actual
        elif op==170:values[x[1]]=values[x[2]]==values[x[3]]
        elif op==249:pc=labels[x[0]]
        elif op==250:pc=labels[x[1] if values[x[0]] else x[2]]
        elif op==253:
            base=0x12345678^(0x01010101 if contender else 0)
            mask=((1<<count)-1)<<offset
            assert memory==(base&~mask)|((insert<<offset)&mask)
            assert 1<=cas<=2
            return True
    return False
with tempfile.TemporaryDirectory() as td:
    td=Path(td);includes=['-I'+str(sirit/'include'),'-I'+str(sirit/'src'),'-I'+str(headers)]
    sources=[sirit/'src/sirit.cpp',*sorted((sirit/'src/instructions').glob('*.cpp'))]
    def compile_obj(src):
        obj=td/(src.stem+'.o')
        subprocess.run(['c++','-std=c++20','-O0',*includes,'-c',str(src),'-o',str(obj)],check=True)
        return str(obj)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:objects=list(pool.map(compile_obj,sources))
    def generate(body,name):
        cpp=td/(name+'.cpp');exe=td/name;spv=td/(name+'.spv')
        cpp.write_text(preamble+body+cas_stub+cas_loop+main)
        subprocess.run(['c++','-std=c++20','-g','-fsanitize=address,undefined',*includes,str(cpp),*objects,'-o',str(exe)],check=True)
        subprocess.run([str(exe),str(spv)],check=True)
        validator=shutil.which('spirv-val')
        if not validator:raise RuntimeError('spirv-val required for this emitter regression')
        subprocess.run([validator,'--target-env','vulkan1.1',str(spv)],check=True)
        data=spv.read_bytes();return struct.unpack('<'+'I'*(len(data)//4),data)
    fixed=generate(method,'fixed')
    # Both the subword-store fallback and generic storage counter/float helper
    # must load atomically. Workgroup branches remain outside this fixture.
    at=5;atomic_loads=0;plain_loads=0
    while at<len(fixed):
        op=fixed[at]&65535
        atomic_loads+=op==227;plain_loads+=op==61;at+=fixed[at]>>16
    assert atomic_loads==2 and plain_loads==0
    old=method.replace('OpAtomicLoad(U32[1], pointer, scope_device, ordering_relaxed)','OpLoad(U32[1], pointer)')
    assert old!=method
    original=generate(old,'original')
    for count in (8,16):
        for offset in range(0,32,count):
            for insert in (0,1,0x55,0xffff):
                for contender in (False,True):
                    assert execute(fixed,offset,count,insert,contender)
                    assert not execute(original,offset,count,insert,contender)
print('Storage CAS progress PASS: production emitter, valid Vulkan SPIR-V, byte/halfword neighbour preservation, competing writes and stale-load nontermination control')
