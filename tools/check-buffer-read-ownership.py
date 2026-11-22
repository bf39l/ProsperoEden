#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise patched engine read paths and upload ordering without an app build.

Pass an engine tree prepared with tools/apply-eden-patches.py. The real engine
functions run against a small cache/scheduler fixture; this is not a GPU test.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

engine = Path(sys.argv[1])


def function(text, signature):
    start = text.index(signature)
    end = text.index('{', start)
    depth = 1
    pos = end + 1
    while depth:
        depth += (text[pos] == '{') - (text[pos] == '}')
        pos += 1
    return text[start:pos]


cache = (engine/'src/video_core/buffer_cache/buffer_cache.h').read_text()
runtime = (engine/'src/video_core/renderer_vulkan/vk_buffer_cache.cpp').read_text()
vk = (engine/'src/video_core/renderer_vulkan/vk_rasterizer.cpp').read_text()
gl = (engine/'src/video_core/renderer_opengl/gl_rasterizer.cpp').read_text()
for text in (vk, gl):
    dispatch = function(text, 'void Rasterizer' + ('Vulkan' if text is vk else 'OpenGL') + '::DispatchCompute()')
    assert 'ObtainBufferOperation::DiscardWrite' not in dispatch
    assert 'ObtainBufferOperation::DoNothing' in dispatch

start = vk.index('        static constexpr auto sync_info', vk.index('void RasterizerVulkan::DispatchCompute()'))
end = vk.index('        scheduler.RequestOutsideRenderPassOperationContext();', start)
acquire = vk[start:end]
assert 'buffer->MarkUsage(offset, 12);' in acquire

code = r'''
#include <algorithm>
#include <array>
#include <bit>
#include <cassert>
#include <cstdint>
#include <limits>
#include <optional>
#include <span>
#include <utility>
#include <vector>
using u32=std::uint32_t; using u64=std::uint64_t; using DAddr=u64;
using BufferId=unsigned;
constexpr unsigned NUM_VERTEX_BUFFERS=2;
namespace Dirty { constexpr unsigned VertexBuffer0=0; }
namespace Settings {
struct Option { bool value=true; bool GetValue()const{return value;} };
inline struct { Option use_optimized_vertex_buffers; bool disable_buffer_reorder=false; } values;
}
namespace VideoCommon {
enum class ObtainBufferSynchronize { FullSynchronize, NoSynchronize };
enum class ObtainBufferOperation { DoNothing, MarkAsWritten, DiscardWrite };
struct BufferCopy { u64 src_offset, dst_offset, size; };
}
using namespace VideoCommon;
struct Buffer {
    std::vector<std::pair<u64,u64>> used;
    u32 Offset(u64 address)const{return static_cast<u32>(address);}
    void MarkUsage(u64 at,u64 size){if(size)used.emplace_back(at,size);}
    bool IsRegionUsed(u64 at,u64 size)const{
        return std::ranges::any_of(used,[&](auto r){return at<r.first+r.second&&r.first<at+size;});
    }
};
struct Policy { using Buffer=::Buffer; };
struct Binding { u64 device_addr=0; u32 size=0; unsigned buffer_id=0; };
template<class B> struct HostBindings {
    std::vector<B*> buffers; std::vector<u32> offsets,sizes,strides;
    u32 min_index=~0u,max_index=0;
};
struct BufferCacheRuntime {
    unsigned binds=0;
    template<class B> void BindVertexBuffers(const HostBindings<B>&){++binds;}
    bool CanReorderUpload(const Buffer&,std::span<const BufferCopy>);
};
template<class P> struct BufferCache {
    using Buffer=typename P::Buffer;
    std::array<Buffer,2> slot_buffers;
    std::array<Binding,2> v_buffer{{{64,32,0},{128,32,1}}};
    struct Maxwell {
        struct {std::array<bool,2> flags{true,true};} dirty;
        struct {struct Stream {u32 stride=16;}; std::array<Stream,2> vertex_streams;} regs;
    } maxwell;
    Maxwell* maxwell3d=&maxwell;
    struct Channel {
        std::array<Binding,2> vertex_buffers{{{64,32,0},{128,32,1}}};
        Binding count_buffer_binding{8,4,1},indirect_buffer_binding{16,20,0};
    } channel;
    Channel* channel_state=&channel;
    struct Indirect {bool include_count=true;} indirect;
    Indirect* current_draw_indirect=&indirect;
    u32 enabled_vertex_buffers_mask=3;
    BufferCacheRuntime runtime;
    struct Ranges { bool dirty=true; void Subtract(u64,u32){dirty=false;} } gpu_modified_ranges;
    bool downloadable=true;
    unsigned synchronizations=0;
    Binding& VertexBufferSlot(u32 i){return v_buffer[i];}
    void TouchBuffer(Buffer&,unsigned){}
    void SynchronizeBuffer(Buffer&,DAddr,u32){++synchronizations;}
    BufferId FindBuffer(DAddr,u32,bool){return 0;}
    void ClearDownload(DAddr,u32){downloadable=false;}
    void MarkWrittenBuffer(BufferId,DAddr,u32){gpu_modified_ranges.dirty=true;}
    std::pair<Buffer*,u32> ObtainCPUBuffer(DAddr,u32,ObtainBufferSynchronize,ObtainBufferOperation);
    auto ObtainBuffer(DAddr a,u32 n,ObtainBufferSynchronize s,ObtainBufferOperation p){return ObtainCPUBuffer(a,n,s,p);}
    void BindHostVertexBuffers();
    void BindHostDrawIndirectBuffers();
};
'''
for name in ('BindHostVertexBuffers', 'BindHostDrawIndirectBuffers'):
    code += '\ntemplate<class P>\n' + function(cache, f'void BufferCache<P>::{name}()')
code += '\ntemplate<class P>\n' + function(cache, 'std::pair<typename P::Buffer*, u32> BufferCache<P>::ObtainCPUBuffer(')
code += '\n' + function(runtime, 'bool BufferCacheRuntime::CanReorderUpload(')
code += '\nvoid Consume(BufferCache<Policy>& buffer_cache) {\nstd::optional<u64> indirect_address=64;\n' + acquire + '\n}\n'
code += r'''
int main() {
    for(bool optimized:{false,true}) {
        Settings::values.use_optimized_vertex_buffers.value=optimized;
        BufferCache<Policy> c;
        c.BindHostVertexBuffers();
        assert(c.runtime.binds==1);
        for(auto& b:c.slot_buffers)b.used.clear(); // prior submission completed
        c.BindHostVertexBuffers(); // same bindings, new draw: no redundant bind needed
        assert(c.runtime.binds==1);
        for(unsigned i=0;i<2;++i) {
            const u64 offset=i==0?64:128;
            const std::array copies{BufferCopy{0,offset,4}};
            assert(!c.runtime.CanReorderUpload(c.slot_buffers[i],copies));
            const std::array separate{BufferCopy{0,offset+64,4}};
            assert(c.runtime.CanReorderUpload(c.slot_buffers[i],separate));
        }
        assert(c.synchronizations==4);
    }
    BufferCache<Policy> c;
    c.BindHostDrawIndirectBuffers();
    assert(c.slot_buffers[0].IsRegionUsed(16,20));
    assert(c.slot_buffers[1].IsRegionUsed(8,4));
    c.slot_buffers[1].used.clear();c.indirect.include_count=false;
    c.BindHostDrawIndirectBuffers();
    assert(c.slot_buffers[1].used.empty());

    BufferCache<Policy> args;
    Consume(args);
    assert(args.gpu_modified_ranges.dirty && args.downloadable);
    assert(args.synchronizations==1);
    assert(args.slot_buffers[0].IsRegionUsed(64,12));
    const std::array overwrite{BufferCopy{0,64,12}};
    assert(!args.runtime.CanReorderUpload(args.slot_buffers[0],overwrite));
    // Actual old acquisition loses ownership and allows reordering. This
    // negative control distinguishes fixing the caller from hiding the defect.
    BufferCache<Policy> old;
    old.ObtainBuffer(64,12,ObtainBufferSynchronize::FullSynchronize,ObtainBufferOperation::DiscardWrite);
    assert(!old.gpu_modified_ranges.dirty && !old.downloadable);
    assert(old.runtime.CanReorderUpload(old.slot_buffers[0],overwrite));
}
'''
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    source = tmp/'check.cpp'; source.write_text(code)
    binary = tmp/'check'
    subprocess.run(['c++', '-std=c++20', '-D__ANDROID__', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print('Buffer read ownership PASS: reused vertex bindings, indirect commands/counts, '
      'compute argument ownership and overlapping/nonoverlapping upload ordering; old-path negative control reproduced')
