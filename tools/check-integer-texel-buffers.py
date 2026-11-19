#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check PS5 Vulkan integer texel-buffer declarations using patched production code."""
from pathlib import Path
import hashlib, json, re, shutil, subprocess, tarfile, tempfile
root = Path(__file__).resolve().parents[1]
archive = root/'.deps/eden-d85bad89.tar.gz'
expected = json.loads((root/'UPSTREAM.json').read_text())['archives'][archive.name]
hash = hashlib.sha256()
with archive.open('rb') as stream:
    for chunk in iter(lambda: stream.read(1 << 20), b''): hash.update(chunk)
assert hash.hexdigest() == expected
patches = sorted((root/'tools/eden-patches').glob('*.diff'))
touched = {line[6:].split('\t')[0] for p in patches for line in p.read_text().splitlines() if line.startswith('+++ b/')}
with tempfile.TemporaryDirectory() as work:
    work = Path(work); tree = work/'source'; tree.mkdir()
    with tarfile.open(archive) as tar:
        for member in tar:
            name = member.name.split('/', 1)
            if len(name) != 2 or name[1] not in touched or not member.isfile(): continue
            file = tree/name[1]; file.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as src, file.open('wb') as dst: shutil.copyfileobj(src, dst)
    for file in touched: (tree/file).parent.mkdir(parents=True, exist_ok=True)
    for patch in patches:
        subprocess.run(['patch', '-s', '-p1', '--forward', '-i', str(patch)], cwd=tree, check=True)
    folder = tree/'src/shader_recompiler'
    emit = (folder/'backend/spirv/spirv_emit_context.cpp').read_text()
    images = (folder/'backend/spirv/emit_spirv_image.cpp').read_text()
    texture = (folder/'ir_opt/texture_pass.cpp').read_text()
    definition = emit[emit.index('void EmitContext::DefineTextureBuffers('):emit.index('void EmitContext::DefineImageBuffers(')]
    integer = images[images.index('bool IsTextureInteger('):images.index('\n}\n', images.index('bool IsTextureInteger('))+3]
    expr = re.search(r'\.is_integer = (host_info.support_integer_texture_buffers &&\s+is_texture_pixel_format_integer\(cbuf\)),', texture).group(1)
    assert 'bool support_integer_texture_buffers{};' in (folder/'host_translate_info.h').read_text()
    assert '.image_type = image_type,' in definition and '.is_integer = desc.is_integer,' in definition
    texture_image = images[images.index('Id TextureImage('):images.index('std::pair<Id, bool> Image(')]
    assert 'ctx.image_buffer_type' not in texture_image
    assert 'ctx.OpLoad(def.image_type, def.id)' in texture_image
    fetch = images[images.index('Id EmitImageFetch('):images.index('Id EmitImageQueryDimensions(')]
    assert 'is_integer ? ctx.U32[4] : ctx.F32[4]' in fetch
    assert 'return is_integer ? ctx.OpBitcast(ctx.F32[4], color) : color;' in fetch
    # Vulkan opts in and must discard pre-fix serialized environments, which have
    # no cached pixel-format entries for the sampled buffers.
    port = (root/'tools/prepare-vulkan-port.py').read_text()
    assert 'host_info.support_integer_texture_buffers = true;' in port
    assert 'constexpr u32 CACHE_VERSION = 0x50530014;' in port
    assert 'eden_binding.integer = desc.is_integer;' in port
    code = r'''
#include <array>
#include <vector>
#include <string>
#include <stdexcept>
#include <cassert>
#include <bit>
#include <cstdint>
using u32=std::uint32_t; using Id=unsigned;
namespace spv {
enum class ImageFormat { Unknown };
enum class Dim { Buffer };
enum class StorageClass { UniformConstant };
enum class Decoration { Binding, DescriptorSet };
}
namespace IR { struct TextureInstInfo { int type; unsigned descriptor_index; }; }
namespace TextureType { constexpr int Buffer=1; }
struct Descriptor { u32 count; bool is_integer; };
using TextureBufferDescriptor=Descriptor;
struct Info { std::vector<Descriptor> texture_buffer_descriptors; };
struct Definition { Id id; u32 count; Id image_type, pointer_type; bool is_integer; };
struct EmitContext {
    struct { u32 supported_spirv=0x10400; } profile;
    int stage=0;
    struct { Id scalar=0, pointer=0, variable=0; } node[128];
    Id next=10;
    std::array<Id,5> F32{0,1,2,3,4}, U32{0,5,6,7,8};
    std::vector<Definition> texture_buffers;
    std::vector<Descriptor> textures;
    std::vector<Id> interfaces;
    Id TypeImage(Id scalar, spv::Dim, unsigned, bool, bool, int, spv::ImageFormat) {
        Id n=next++; node[n].scalar=scalar; return n;
    }
    Id TypePointer(spv::StorageClass, Id type) { Id n=next++; node[n].pointer=type; return n; }
    Id AddGlobalVariable(Id type, spv::StorageClass) { Id n=next++; node[n].variable=type; return n; }
    void Decorate(Id, spv::Decoration, unsigned) {}
    void Name(Id, const std::string&) {}
    void DefineTextureBuffers(const Info&, u32&);
};
std::runtime_error NotImplementedException(const char* text) { return std::runtime_error(text); }
std::string NameOf(int, const Descriptor&, const char*) { return "buffer"; }
''' + definition + integer + r'''
bool Choose(bool supported, bool integer_format, unsigned& calls) {
    struct { bool support_integer_texture_buffers; } host_info{supported};
    int cbuf=0;
    auto is_texture_pixel_format_integer=[&](int) { ++calls; return integer_format; };
    return ''' + expr + r''';
}
int main() {
    unsigned calls=0;
    assert(!Choose(false, true, calls) && calls==0); // OpenGL/old hosts do not query new metadata.
    assert(Choose(true, true, calls) && calls==1);
    assert(!Choose(true, false, calls) && calls==2);
    EmitContext context; u32 binding=3;
    context.DefineTextureBuffers(Info{{{1,false},{1,true},{1,false},{1,true}}}, binding);
    assert(binding==7 && context.interfaces.size()==4);
    for (unsigned i=0; i<4; ++i) {
        const auto& def=context.texture_buffers[i];
        assert(def.is_integer==bool(i&1));
        assert(context.node[def.image_type].scalar==(i&1 ? context.U32[1] : context.F32[1]));
        assert(context.node[def.pointer_type].pointer==def.image_type);
        assert(context.node[def.id].variable==def.pointer_type);
        assert(IsTextureInteger(context, IR::TextureInstInfo{TextureType::Buffer,i})==bool(i&1));
    }
    context.textures={{1,true},{1,false}};
    assert(IsTextureInteger(context, IR::TextureInstInfo{0,0}));
    assert(!IsTextureInteger(context, IR::TextureInstInfo{0,1}));
    // Integer fetched words must retain their bits through the IR's float carrier.
    for (u32 word : {0u,1u,27232513u,0x3f800001u,0xffffffffu})
        assert(std::bit_cast<u32>(std::bit_cast<float>(word))==word);
    bool refused=false;
    try { context.DefineTextureBuffers(Info{{{2,true}}}, binding); }
    catch (const std::runtime_error&) { refused=true; }
    assert(refused); // Do not silently introduce new array semantics.
}
'''
    source = work/'check.cpp'; source.write_text(code)
    binary = work/'check'
    subprocess.run(['c++','-std=c++20','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(source),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
print('Integer texel buffers PASS: full pinned patch stack, real declaration/selection code, mixed float/uint buffers, per-descriptor loads, bit preservation, unchanged float/default-host paths, cache migration and existing array rejection')
