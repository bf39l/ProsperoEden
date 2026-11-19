#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Draw provenance: real CMake anchors, unchanged draw/refresh policy and bounded observations."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile
root = Path(__file__).resolve().parents[1]
code = r'''
#include "indirect_draw_log.h"
#include <cassert>
#include <optional>
#include <thread>
#include <vector>
namespace D = Eden::IndirectDrawLog;
struct Memory {
    mutable unsigned queries = 0;
    bool dirty = true;
    std::optional<std::uint64_t> GpuToCpuAddress(std::uint64_t addr) const {
        return addr ? std::optional<std::uint64_t>{addr + 0x100000} : std::nullopt;
    }
    // The two-argument Eden overload searches pages and returns a page base.
    // Returning a deliberately different value catches use of the wrong overload.
    std::optional<std::uint64_t> GpuToCpuAddress(std::uint64_t addr, std::size_t) const {
        return GpuToCpuAddress(addr & ~std::uint64_t{0xfff});
    }
    bool IsMemoryDirty(std::uint64_t, std::size_t) const { ++queries; return dirty; }
};
using Segments = std::vector<std::pair<std::uint64_t, std::size_t>>;
int main() {
    D::Reset(); Memory memory;
    Segments segments{{0, 1}, {0x4000, 2}, {0, 3}};
    std::array<std::uint32_t, 6> p{4, 6, 31126785, 0, 0, 0};
    {
        D::ContextScope context{0xe00, segments, true, memory};
        assert(D::Local().context->source(&segments, 0).gpu == 0);
        assert(D::Local().context->source(&segments, 1).gpu == 0x4000);
        assert(D::Local().context->source(&segments, 2).gpu == 0x4004);
        assert(D::Local().context->source(&segments, 4).gpu == 0);
        assert(!D::Local().context->source(&segments, 6).known);
        {
            D::ProducerScope producer{"compute", 0, {}, 0xabcdef};
            D::BindingScope binding{"compute-storage", 0, 3};
            D::GpuWriteTracked(0x104000, 8, true);
        }
        assert(D::Local().producer.compute_shader == 0);
        assert(D::Local().binding.slot == ~0u);
        assert(D::LastTrackedWrite(0x104004).needs_sync);
        {
            D::DrawScope trace{"indexed", p, 1, ~std::uint32_t{0}};
            assert(D::Local().active->queued_checked[1]);
            assert(D::Local().active->queued_dirty[1]);
            {
                D::RefreshScope refresh{memory, 0x4000, 1, 2};
                // Stand-in for the ORIGINAL read: instrumentation must never invoke it.
                memory.dirty = false; p[2] = 2;
                D::Flushed(0x104000, 8); refresh.Done(memory);
            }
            trace.Refreshed(p);
            assert(D::Local().active->gpu_dirty_before[1]);
            assert(!D::Local().active->gpu_dirty_after[1]);
            p[2] = 1; trace.Retried(p);
            assert(D::Local().active->flush_calls == 1);
        }
        const auto& record = D::Local().history[1];
        assert(record.before[1] == 31126785 && record.refreshed[1] == 2 && record.retried[1] == 1);
        assert(record.source[0].gpu == 0x4000 && record.source[1].gpu == 0x4004);
        assert(record.source[2].known && record.source[2].gpu == 0);
        assert(record.cpu[1] == 0x104004 && record.refresh_calls == 1);
        assert(record.tracked_write[1].sequence == 1 && record.tracked_write[1].needs_sync);
        assert(record.tracked_write[1].producer.compute_shader == 0xabcdef);
        assert(record.tracked_write[1].binding.slot == 3);
        assert(D::Local().watched_compute == 0xabcdef);
        assert(!D::CounterProbeWanted(0x123456));
        assert(D::CounterProbeWanted(0xabcdef));
        D::CounterBinding binding{};
        binding.shader = 0xabcdef; binding.slot = 4; binding.cpu = 0x104004;
        binding.bytes = 4; binding.mapped = true; binding.image = true;
        D::ProbeCounterBinding(binding);
        unsigned probes = 1;
        for (int n = 1; n < 1000000; ++n) probes += D::CounterProbeWanted(0xabcdef);
        assert(probes == 4 + 17);

        // No extra ownership queries for ordinary draws; no external read API exists in Memory.
        const unsigned queries = memory.queries;
        for (int n = 0; n < 100; ++n) {
            D::DrawScope trace{"normal", p, 1, ~std::uint32_t{0}};
            D::RefreshScope refresh{memory, 0x4000, 1, 2}; refresh.Done(memory);
            trace.Refreshed(p);
        }
        assert(memory.queries == queries && D::Local().sequence == 101);
        assert(D::Local().history[101 % 32].sequence == 101);
        // Bounds, mask semantics, skipped refresh and existing guard outcome.
        p[2] = 31126785;
        { D::DrawScope trace{"masked", p, 1, 0}; }
        assert(D::Local().suspicious == 1);
        { D::DrawScope trace{"skipped-refresh", p, 1, ~std::uint32_t{0}}; D::Dropped(); }
        assert(D::Local().history[103 % 32].refresh_calls == 0);
        assert(D::Local().history[103 % 32].outcome == std::string_view{"rejected-by-existing-guard"});
        { D::DrawScope trace{"short", p, 5, ~std::uint32_t{0}}; }
        { D::DrawScope trace{"past-end", p, 999, ~std::uint32_t{0}}; }
    }
    assert(!D::Local().active && !D::Local().context);
    for (unsigned n = 0; n < 256; ++n) D::GpuWriteTracked(0x200000 + n * 8, 8, false);
    assert(D::LastTrackedWrite(0x200000).sequence == 0); // evicted from bounded ring
    assert(D::LastTrackedWrite(0x200000 + 255 * 8).size == 8);

    // Reset between games and bounded output even for a million suspicious draws.
    D::Reset();
    {
        D::ContextScope context{0xe00, segments, false, memory};
        assert(D::Local().sequence == 0 && D::Local().suspicious == 0 && D::Local().write_sequence == 0);
        const unsigned before = memory.queries;
        for (int n = 0; n < 1000000; ++n) { D::DrawScope trace{"repeat", p, 1, ~std::uint32_t{0}}; }
        assert(D::Local().suspicious == 1000000);
        assert(memory.queries - before == (32 + 14) * 2);
        std::thread([&] {
            D::ContextScope other{0xe00, segments, false, memory};
            assert(!D::Local().active && D::Local().sequence == 0);
        }).join();
        assert(D::Local().sequence == 1000000);
    }
    // Rejected draws cannot exhaust the accepted-draw sampling budget.
    D::Reset();
    {
        D::ContextScope context{0xe00, segments, false, memory};
        D::Local().rejected_suspicious = 1000000;
        D::Local().suspicious = 1000000;
        { D::DrawScope accepted{"accepted-after-rejections", p, 1, ~std::uint32_t{0}};
          assert(D::Local().active->inspect); }
        assert(D::Local().accepted_suspicious == 1);
    }
}
'''
# The test deliberately has no GPU readback/read API, so added calls cannot be hidden in a mock.
code = code.replace('#include <thread>', '#include <thread>\n#include <string_view>')
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    source = tmp / 'check.cpp'; source.write_text(code)
    binary = tmp / 'check'
    subprocess.run(['c++', '-std=c++20', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-g', '-pthread', '-I'+str(root/'headless'), str(source), '-o', str(binary)], check=True)
    result = subprocess.run([str(binary)], capture_output=True, text=True, check=True)
    assert len(result.stderr.splitlines()) < 400, len(result.stderr.splitlines())
    assert 'queued_instances=31126785 count=6 instances=1' in result.stderr
    assert 'origin=inline-command' in result.stderr and 'origin=memory' in result.stderr
    assert 'queued_gpu_dirty=1' in result.stderr and 'last_refresh_gpu_dirty_after=0' in result.stderr
    assert 'flush_completed=1' in result.stderr and 'instances=31126785' in result.stderr
    assert 'kind=accepted-after-rejections' in result.stderr
    assert 'cpu=0x104004' in result.stderr
    assert 'EDEN_DRAW_PRODUCER' in result.stderr and 'cs=abcdef' in result.stderr
    assert 'EDEN_COUNTER_UPSTREAM probe=1 slot=4 write_seq=1 writer_kind=compute' in result.stderr
    assert 'writer_cs=abcdef' in result.stderr
    assert 'binding=compute-storage stage=0 slot=3 byte_offset=4 intent_only=1' in result.stderr
    if len(sys.argv) > 1:
        eden = Path(sys.argv[1])
        # Exercise the real CMake edits against the patched engine, no full app build.
        subprocess.run(['cmake', '-DMACRO_INPUT='+str(eden/'src/video_core/macro.cpp'),
                        '-DMACRO_OUTPUT='+str(tmp/'macro.cpp'), '-DEDEN_PORT_DIR='+str(root/'headless'),
                        '-P', str(root/'headless/macro_recovery.cmake')], check=True)
        original = (eden/'src/video_core/macro.cpp').read_text(); derived = (tmp/'macro.cpp').read_text()
        guard = re.search(r'bool IsDrawImplausible\(.*?\n}', original, re.S).group()
        # The product limit is preserved; the PS5 instance ceiling closes the observed gap.
        product = next(line for line in guard.splitlines() if 'return u64(count)' in line)
        assert product in derived
        fixed_guard = re.search(r'bool IsDrawImplausible\(.*?\n}', derived, re.S).group()
        guard_test = tmp/'guard.cpp'
        guard_test.write_text('#include <cstdint>\n#include <cassert>\nusing u32=std::uint32_t; using u64=std::uint64_t;\n' + fixed_guard + r"""
int main() {
    assert(IsDrawImplausible(6, 27232513));
    assert(IsDrawImplausible(6, 30909185));
    assert(IsDrawImplausible(6, 31126795));
    assert(IsDrawImplausible(192, 2684685881u));
    assert(IsDrawImplausible(3, 1048577));
    assert(!IsDrawImplausible(3, 1048576));
    assert(!IsDrawImplausible(6, 2));
    assert(!IsDrawImplausible(1188, 1));
    assert(!IsDrawImplausible(6, 65536));
    assert(!IsDrawImplausible(0, 0xffffffffu));
    assert(!IsDrawImplausible(0xffffffffu, 0));
    assert(IsDrawImplausible(0xffffffffu, 16));
}
""")
        guard_binary = tmp/'guard'
        subprocess.run(['c++', '-std=c++20', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined', str(guard_test), '-o', str(guard_binary)], check=True)
        subprocess.run([str(guard_binary)], check=True)
        for name in ['DrawArraysIndirect', 'DrawIndexedIndirect']:
            begin = derived.index('void HLE_'+name+'::Fallback(')
            end = derived.index('\n}\n', begin)
            body = derived[begin:end]
            first = body.index('if (IsDrawImplausible(')
            refresh = body.index('maxwell3d.ForceRefreshParameters();', first)
            recheck = body.index('if (IsDrawImplausible(', refresh)
            drop = body.index('ReportDroppedDraw(', recheck)
            finish = body.index('return;', drop)
            assert first < refresh < recheck < drop < finish
        assert derived.count('maxwell3d.draw_manager.DrawIndex(') == original.count('maxwell3d.draw_manager.DrawIndex(')
        # Execute the actual generated single-draw guard block, not a policy mirror.
        begin = derived.index('void HLE_DrawIndexedIndirect::Fallback(')
        block_start = derived.index('    if (IsDrawImplausible(', begin)
        block_end = derived.index('    const u32 instance_count =', block_start)
        block = derived[block_start:block_end]
        flow = tmp/'refresh_flow.cpp'
        flow.write_text('#include <cstdint>\n#include <span>\n#include <cassert>\nusing u32=std::uint32_t; using u64=std::uint64_t;\n' + fixed_guard + r"""
int accepted = 0, dropped = 0;
void ReportDroppedDraw(const char*, u32, u32) { ++dropped; }
struct Trace { void Retried(std::span<const u32>) {} };
struct Maxwell {
    std::span<u32> words; bool repair; int refreshes = 0;
    u32 GetRegisterValue(u32) const { return 0xffffffffu; }
    void ForceRefreshParameters() { ++refreshes; if (repair) words[2] = 2; }
};
void Try(Maxwell& maxwell3d, std::span<const u32> parameters) {
    Trace eden_args;
""" + block + r"""
    ++accepted;
}
int main() {
    u32 args[]{4,6,27232513,0,0,0};
    Maxwell repair{args, true}; Try(repair, args);
    assert(repair.refreshes == 1 && accepted == 1 && dropped == 0 && args[2] == 2);
    accepted = dropped = 0; args[2] = 27232513;
    Maxwell unchanged{args, false}; Try(unchanged, args);
    assert(unchanged.refreshes == 1 && accepted == 0 && dropped == 1);
    accepted = dropped = 0; args[2] = 2;
    Maxwell ordinary{args, false}; Try(ordinary, args);
    assert(ordinary.refreshes == 0 && accepted == 1 && dropped == 0);
}
""")
        flow_binary = tmp/'refresh_flow'
        subprocess.run(['c++', '-std=c++20', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined', str(flow), '-o', str(flow_binary)], check=True)
        subprocess.run([str(flow_binary)], check=True)


        for call in ['maxwell3d.RefreshParameters();', 'maxwell3d.ForceRefreshParameters();']:
            assert derived.count(call) == original.count(call), call
        assert derived.count('DrawScope eden_args') == 3
        assert derived.count('eden_args.Refreshed(parameters)') == 2
        engine = eden/'src/video_core/engines/maxwell_3d.cpp'
        cmake = tmp/'engine.cmake'
        cmake.write_text(f'file(READ "{engine}" maxwell_source)\n'
                         f'set(EDEN_PORT_DIR "{root / "headless"}")\n'
                         f'include("{root / "headless/indirect_draw_trace.cmake"}")\n'
                         f'file(WRITE "{tmp / "maxwell.cpp"}" "${{maxwell_source}}")\n')
        subprocess.run(['cmake', '-P', str(cmake)], check=True)
        assert (tmp/'maxwell.cpp').read_text().count('memory_manager.ReadBlock(') == engine.read_text().count('memory_manager.ReadBlock(')
        assert 'ContextScope eden_context' in (tmp/'maxwell.cpp').read_text()
        # Also run the exact ReadBlock flush-observation edits from the main CMake file.
        cmake_source = (root/'headless/CMakeLists.txt').read_text()
        begin = cmake_source.index('if(PS5_NATIVE)\n    set(draw_flush_old ')
        end = cmake_source.index('endif()', begin) + len('endif()')
        # The first endif closes the anchor check, so include the outer block too.
        end = cmake_source.index('endif()', end) + len('endif()')
        memory = eden/'src/video_core/memory_manager.cpp'
        cmake.write_text(f'file(READ "{memory}" gpu_memory_source)\nset(PS5_NATIVE TRUE)\n'
                         f'set(EDEN_PORT_DIR "{root / "headless"}")\n' + cmake_source[begin:end] +
                         f'\nfile(WRITE "{tmp / "memory.cpp"}" "${{gpu_memory_source}}")\n')
        subprocess.run(['cmake', '-P', str(cmake)], check=True)
        observed = (tmp/'memory.cpp').read_text(); original_memory = memory.read_text()
        assert observed.count('rasterizer->FlushRegion(') == original_memory.count('rasterizer->FlushRegion(')
        assert observed.count('IndirectDrawLog::Flushed(dev_addr_base, copy_amount);') == 2
        vulkan = tmp/'vulkan'
        vulkan.mkdir()
        subprocess.run([sys.executable, str(root/'tools/prepare-vulkan-port.py'), str(eden), str(vulkan)], check=True)
        buffer = (vulkan/'vulkan-cache/video_core/buffer_cache/buffer_cache.h').read_text()
        assert buffer.count('IndirectDrawLog::GpuWriteTracked(device_addr, size, needs_sync);') == 1
        assert '#include "indirect_draw_log.h"' in buffer
        graphics = (vulkan/'vk_graphics_pipeline_cost.cpp').read_text()
        compute = (vulkan/'vk_compute_pipeline_cost.cpp').read_text()
        assert 'ProducerScope eden_producer{"graphics", key.Hash(), key.unique_hashes}' in graphics
        assert 'ProducerScope eden_producer{"compute", 0, {}, shader_hash}' in compute
        assert 'CounterProbeWanted(shader_hash)' in compute
        assert 'eden_binding.handle = views[index].index;' in compute
        assert 'eden_binding.view_format = static_cast<int>(image_view.format);' in compute
        assert 'ProbeCounterBinding(eden_binding);' in compute
        assert compute.count('gpu_memory.Read<u32>') == (eden/'src/video_core/renderer_vulkan/vk_compute_pipeline.cpp').read_text().count('gpu_memory.Read<u32>')

        assert graphics.index('ProducerScope eden_producer') < graphics.index('buffer_cache.SetUniformBuffersState')
        assert compute.index('ProducerScope eden_producer') < compute.index('buffer_cache.SetComputeUniformBufferState')
        assert 'BindingScope eden_binding{"compute-storage", 0, index}' in buffer
        assert 'BindingScope eden_binding{"graphics-storage", static_cast<unsigned>(stage), index}' in buffer

print('Indirect draw provenance PASS: queued/refreshed/retried values, exact origins, cache ownership, existing flushes, skipped reads, masks, bounded history/output, session reset and thread isolation; refresh-before-rejection retained; PS5 ceiling rejects recorded 27–31M-instance hangs')
