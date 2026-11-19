// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
// Observes existing macro parameters and refreshes only. No extra memory readback,
// draw rejection, refresh or GPU wait. Bounded stderr output survives engine-log limits.
#include <algorithm>
#include <array>
#include <atomic>
#include <cstddef>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <span>

namespace Eden::IndirectDrawLog {
inline std::atomic<std::uint64_t> generation{1};
inline void Reset() { generation.fetch_add(1, std::memory_order_relaxed); }
struct Source { bool known = false; std::uint64_t gpu = 0; };
struct Ownership { bool mapped = false, dirty = false; std::uint64_t cpu = 0; };
struct Context {
    const void* segments = nullptr;
    Source (*source)(const void*, std::size_t) = nullptr;
    const void* memory = nullptr;
    Ownership (*query)(const void*, std::uint64_t) = nullptr;
    std::uint32_t method = 0;
    bool dirty = false;
};
struct Producer {
    std::uint64_t work = 0, key = 0, compute_shader = 0;
    const char* kind = "unknown";
    std::array<std::uint64_t, 6> stages{};
};
struct Binding { const char* kind = "unknown"; unsigned stage = ~0u, slot = ~0u; };
struct TrackedWrite {
    std::uint64_t sequence = 0, cpu = 0, size = 0;
    bool needs_sync = false;
    Producer producer{};
    Binding binding{};
};
struct Record {
    std::uint64_t sequence = 0;
    const char* kind = "unknown";
    const char* outcome = "guard-not-rejected";
    std::size_t base = 0, words = 0;
    std::uint32_t method = 0, mask = 0;
    bool dirty = false, inspect = false, dropped = false;
    const char* baseline = "queued";
    std::array<std::uint32_t, 5> before{}, refreshed{}, retried{};
    bool has_refresh = false, has_retry = false;
    std::array<Source, 5> source{};
    std::array<std::uint64_t, 5> cpu{};
    std::array<bool, 5> queued_checked{}, queued_dirty{}, mapped{}, observed{}, gpu_dirty_before{}, gpu_dirty_after{};
    std::array<TrackedWrite, 5> tracked_write{};
    unsigned refresh_calls = 0, flush_calls = 0;
    std::uint64_t last_flush_cpu = 0, last_flush_size = 0;
};
struct State {
    std::uint64_t epoch = 0, sequence = 0, suspicious = 0;
    std::uint64_t accepted_suspicious = 0, rejected_suspicious = 0;
    std::array<Record, 32> history{};
    std::array<TrackedWrite, 128> writes{};
    std::uint64_t write_sequence = 0, producer_sequence = 0;
    std::uint64_t watched_compute = 0, counter_probes = 0;
    Producer producer{};
    Binding binding{};
    Context* context = nullptr;
    Record* active = nullptr;
};
inline State& Local() {
    thread_local State state;
    const auto epoch = generation.load(std::memory_order_relaxed);
    if (state.epoch != epoch) { state = {}; state.epoch = epoch; }
    return state;
}
// Pipeline Configure scopes run on the GPU emulation thread, around writable-buffer
// binding. Compiler-worker pipeline construction must never set these scopes.
class ProducerScope {
    Producer previous;
public:
    ProducerScope(const char* kind, std::uint64_t key,
                  std::array<std::uint64_t, 6> stages = {}, std::uint64_t cs = 0) {
        auto& state = Local(); previous = state.producer;
        state.producer = {++state.producer_sequence, key, cs, kind, stages};
    }
    ~ProducerScope() { Local().producer = previous; }
    ProducerScope(const ProducerScope&) = delete;
    ProducerScope& operator=(const ProducerScope&) = delete;
};
class BindingScope {
    Binding previous;
public:
    BindingScope(const char* kind, unsigned stage, unsigned slot) {
        auto& state = Local(); previous = state.binding;
        state.binding = {kind, stage, slot};
    }
    ~BindingScope() { Local().binding = previous; }
    BindingScope(const BindingScope&) = delete;
    BindingScope& operator=(const BindingScope&) = delete;
};
// A buffer marked for a GPU write is producer intent, not evidence of completion.
inline void GpuWriteTracked(std::uint64_t cpu, std::uint64_t bytes, bool needs_sync) {
    if (!bytes) return;
    auto& state = Local(); const auto seq = ++state.write_sequence;
    state.writes[seq % state.writes.size()] = {seq, cpu, bytes, needs_sync, state.producer, state.binding};
}
inline TrackedWrite LastTrackedWrite(std::uint64_t cpu) {
    const auto& state = Local();
    const auto count = std::min<std::uint64_t>(state.write_sequence, state.writes.size());
    for (std::uint64_t i = 0; i < count; ++i) {
        const auto& write = state.writes[(state.write_sequence - i) % state.writes.size()];
        if (cpu >= write.cpu && cpu - write.cpu < write.size) return write;
    }
    return {};
}
// Arm on a compute producer actually linked to suspicious arguments, rather than
// hard-coding one game's shader hash or logging every descriptor of every game.
inline void WatchCounterProducer(const TrackedWrite& write) {
    auto& state = Local();
    if (!state.watched_compute && write.producer.compute_shader) {
        state.watched_compute = write.producer.compute_shader; state.counter_probes = 0;
        std::fprintf(stderr, "EDEN_COUNTER_WATCH cs=%llx\n", static_cast<unsigned long long>(state.watched_compute));
    }
}
inline bool CounterProbeWanted(std::uint64_t shader) {
    auto& state = Local();
    if (!shader || shader != state.watched_compute) return false;
    const auto n = ++state.counter_probes;
    return n <= 4 || (n & (n - 1)) == 0;
}
struct CounterBinding {
    std::uint64_t shader = 0, gpu = 0, cpu = 0;
    std::size_t bytes = 0;
    std::uint32_t slot = 0, handle = 0, cbuf = 0, offset = 0, count = 0, shader_format = 0;
    int view_format = 0, bound_format = 0;
    bool mapped = false, image = false, read = false, written = false, integer = false;
};
inline void ProbeCounterBinding(const CounterBinding& b) {
    const auto& state = Local();
    std::fprintf(stderr,
        "EDEN_COUNTER_BINDING probe=%llu cs=%llx slot=%u kind=%s tic=%x cbuf=%u offset=%x elements=%u read=%u write=%u shader_scalar=%s shader_format=%u view_format=%d bound_format=%d gpu=%#llx mapped=%u cpu=%#llx bytes=%zu\n",
        static_cast<unsigned long long>(state.counter_probes), static_cast<unsigned long long>(b.shader),
        b.slot, b.image ? "storage-image-buffer" : "sampled-texture-buffer", b.handle, b.cbuf, b.offset,
        b.count, unsigned(b.read), unsigned(b.written), b.integer ? "uint" : "float", b.shader_format,
        b.view_format, b.bound_format, static_cast<unsigned long long>(b.gpu), unsigned(b.mapped),
        static_cast<unsigned long long>(b.cpu), b.bytes);
    TrackedWrite overlap{};
    if (b.mapped && b.bytes) {
        const auto count = std::min<std::uint64_t>(state.write_sequence, state.writes.size());
        for (std::uint64_t i = 0; i < count; ++i) {
            const auto& w = state.writes[(state.write_sequence - i) % state.writes.size()];
            if (w.size && (b.cpu <= w.cpu ? w.cpu - b.cpu < b.bytes : b.cpu - w.cpu < w.size)) {
                overlap = w; break;
            }
        }
    }
    const auto& p = overlap.producer;
    std::fprintf(stderr,
        "EDEN_COUNTER_UPSTREAM probe=%llu slot=%u write_seq=%llu writer_kind=%s writer_work=%llu writer_cs=%llx writer_key=%llx va=%llx vb=%llx tc=%llx te=%llx gs=%llx fs=%llx binding=%s binding_stage=%u binding_slot=%u cpu=%#llx+%llu overlap_intent_only=1\n",
        static_cast<unsigned long long>(state.counter_probes), b.slot,
        static_cast<unsigned long long>(overlap.sequence), p.kind, static_cast<unsigned long long>(p.work),
        static_cast<unsigned long long>(p.compute_shader), static_cast<unsigned long long>(p.key),
        static_cast<unsigned long long>(p.stages[0]), static_cast<unsigned long long>(p.stages[1]),
        static_cast<unsigned long long>(p.stages[2]), static_cast<unsigned long long>(p.stages[3]),
        static_cast<unsigned long long>(p.stages[4]), static_cast<unsigned long long>(p.stages[5]),
        overlap.binding.kind, overlap.binding.stage, overlap.binding.slot,
        static_cast<unsigned long long>(overlap.cpu), static_cast<unsigned long long>(overlap.size));
}
inline bool Suspicious(std::uint32_t count, std::uint32_t instances) {
    // Diagnostic threshold only: deliberately below the existing draw rejection limit.
    return instances >= (1u << 20) || std::uint64_t(count) * instances >= (1ull << 26);
}
inline bool Wanted(std::uint64_t n) { return n <= 32 || (n & (n - 1)) == 0; }
class ContextScope {
    Context context;
    Context* previous = nullptr;
public:
    template <typename Segments, typename Memory>
    ContextScope(std::uint32_t method, const Segments& segments, bool dirty, const Memory& memory) {
        auto& state = Local();
        context = {&segments, [](const void* pointer, std::size_t index) {
            for (const auto& [address, words] : *static_cast<const Segments*>(pointer)) {
                if (index < words)
                    return Source{true, address ? std::uint64_t(address) + index * 4 : 0};
                index -= words;
            }
            return Source{};
        }, &memory, [](const void* pointer, std::uint64_t gpu) {
            const auto& manager = *static_cast<const Memory*>(pointer);
            const auto cpu = manager.GpuToCpuAddress(gpu);
            return Ownership{cpu.has_value(), manager.IsMemoryDirty(gpu, 4), cpu ? *cpu : 0};
        }, method, dirty};
        previous = state.context; state.context = &context;
    }
    ~ContextScope() { Local().context = previous; }
    ContextScope(const ContextScope&) = delete;
    ContextScope& operator=(const ContextScope&) = delete;
};
inline void Values(const char* name, const Record& r, const std::array<std::uint32_t, 5>& words) {
    std::fprintf(stderr, " %s=", name);
    for (std::size_t i = 0; i < r.words; ++i)
        std::fprintf(stderr, "%s%08x", i ? "," : "", words[i]);
}
inline void Print(const Record& r, bool sources) {
    const auto& final = r.has_retry ? r.retried : r.has_refresh ? r.refreshed : r.before;
    const auto us = std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
    std::fprintf(stderr, "EDEN_DRAW_ARGS time_us=%lld seq=%llu kind=%s method=%x offset=%zu dirty=%u mask=%08x queued_count=%u queued_instances=%u count=%u instances=%u outcome=%s refresh_calls=%u flush_completed=%u last_flush_cpu=%#llx+%llu baseline=%s",
        static_cast<long long>(us), static_cast<unsigned long long>(r.sequence), r.kind, r.method, r.base,
        unsigned(r.dirty), r.mask, r.before[0], r.before[1] & r.mask, final[0], final[1] & r.mask, r.outcome, r.refresh_calls, r.flush_calls, static_cast<unsigned long long>(r.last_flush_cpu),
        static_cast<unsigned long long>(r.last_flush_size), r.baseline);
    Values("queued", r, r.before);
    if (r.has_refresh) Values("after_refresh", r, r.refreshed);
    if (r.has_retry) Values("after_retry", r, r.retried);
    std::fputc('\n', stderr);
    if (!sources) return;
    for (std::size_t i = 0; i < r.words; ++i) {
        const auto& source = r.source[i];
        std::fprintf(stderr, "EDEN_DRAW_SOURCE seq=%llu word=%zu origin=%s gpu=%#llx mapped=%u cpu=%#llx queued_checked=%u queued_gpu_dirty=%u refresh_observed=%u last_refresh_gpu_dirty_before=%u last_refresh_gpu_dirty_after=%u tracked_write_seq=%llu tracked_write_cpu=%#llx+%llu tracked_write_needs_sync=%u\n",
            static_cast<unsigned long long>(r.sequence), r.base + i,
            !source.known ? "unknown" : source.gpu ? "memory" : "inline-command",
            static_cast<unsigned long long>(source.gpu), unsigned(r.mapped[i]),
            static_cast<unsigned long long>(r.cpu[i]), unsigned(r.queued_checked[i]), unsigned(r.queued_dirty[i]), unsigned(r.observed[i]),
            unsigned(r.gpu_dirty_before[i]), unsigned(r.gpu_dirty_after[i]),
            static_cast<unsigned long long>(r.tracked_write[i].sequence),
            static_cast<unsigned long long>(r.tracked_write[i].cpu),
            static_cast<unsigned long long>(r.tracked_write[i].size), unsigned(r.tracked_write[i].needs_sync));
        const auto& write = r.tracked_write[i];
        if (write.sequence) {
            const auto& p = write.producer;
            const auto& b = write.binding;
            std::fprintf(stderr,
                "EDEN_DRAW_PRODUCER seq=%llu word=%zu write_seq=%llu work=%llu kind=%s key=%llx cs=%llx va=%llx vb=%llx tc=%llx te=%llx gs=%llx fs=%llx binding=%s stage=%u slot=%u byte_offset=%llu intent_only=1\n",
                static_cast<unsigned long long>(r.sequence), r.base + i,
                static_cast<unsigned long long>(write.sequence), static_cast<unsigned long long>(p.work),
                p.kind, static_cast<unsigned long long>(p.key), static_cast<unsigned long long>(p.compute_shader),
                static_cast<unsigned long long>(p.stages[0]), static_cast<unsigned long long>(p.stages[1]),
                static_cast<unsigned long long>(p.stages[2]), static_cast<unsigned long long>(p.stages[3]),
                static_cast<unsigned long long>(p.stages[4]), static_cast<unsigned long long>(p.stages[5]),
                b.kind, b.stage, b.slot, static_cast<unsigned long long>(r.cpu[i] - write.cpu));
        }
    }
}
class DrawScope {
    Record record;
    Record* previous = nullptr;
    static void Copy(Record& r, std::span<const std::uint32_t> parameters,
                     std::array<std::uint32_t, 5>& to) {
        for (std::size_t i = 0; i < r.words; ++i) to[i] = parameters[r.base + i];
    }
public:
    DrawScope(const char* kind, std::span<const std::uint32_t> parameters,
              std::size_t base, std::uint32_t mask, bool after_initial_refresh = false, bool would_reject = false) {
        auto& state = Local();
        record.sequence = ++state.sequence; record.kind = kind;
        record.base = base; record.mask = mask;
        if (after_initial_refresh) record.baseline = "after-multi-refresh";
        record.words = base < parameters.size() ? std::min<std::size_t>(5, parameters.size() - base) : 0;
        if (const auto* ctx = state.context) {
            record.method = ctx->method; record.dirty = ctx->dirty;
            for (std::size_t i = 0; i < record.words; ++i)
                record.source[i] = ctx->source(ctx->segments, base + i);
        }
        Copy(record, parameters, record.before);
        record.inspect = record.words >= 2 && Suspicious(record.before[0], record.before[1] & mask) && Wanted((would_reject ? state.rejected_suspicious : state.accepted_suspicious) + 1);
        if (record.inspect && state.context) {
            const auto* ctx = state.context;
            for (std::size_t i = 0; i < 2; ++i) {
                if (!record.source[i].known || !record.source[i].gpu) continue;
                const auto ownership = ctx->query(ctx->memory, record.source[i].gpu);
                record.queued_checked[i] = true; record.queued_dirty[i] = ownership.dirty;
                record.mapped[i] = ownership.mapped; record.cpu[i] = ownership.cpu;
                if (ownership.mapped) {
                    record.tracked_write[i] = LastTrackedWrite(ownership.cpu);
                    WatchCounterProducer(record.tracked_write[i]);
                }
            }
        }
        previous = state.active; state.active = &record;
    }
    void Refreshed(std::span<const std::uint32_t> parameters) {
        Copy(record, parameters, record.refreshed); record.has_refresh = true;
    }
    void Retried(std::span<const std::uint32_t> parameters) {
        Copy(record, parameters, record.retried); record.has_retry = true;
    }
    ~DrawScope() {
        auto& state = Local(); state.active = previous;
        bool suspicious = false;
        for (const auto* values : {&record.before, &record.refreshed, &record.retried})
            suspicious |= record.words >= 2 && Suspicious((*values)[0], (*values)[1] & record.mask);
        bool wanted = false;
        if (suspicious) {
            ++state.suspicious;
            auto& category = record.dropped ? state.rejected_suspicious : state.accepted_suspicious;
            wanted = Wanted(++category);
        }
        if (wanted) {
            // The first suspicious draw also carries the previous eight observed CPU draws.
            if (state.suspicious == 1) {
                const auto start = record.sequence > 8 ? record.sequence - 8 : 1;
                for (auto seq = start; seq < record.sequence; ++seq) {
                    const auto& prior = state.history[seq % state.history.size()];
                    if (prior.sequence == seq) Print(prior, false);
                }
            }
            Print(record, true);
        }
        state.history[record.sequence % state.history.size()] = record;
    }
    DrawScope(const DrawScope&) = delete;
    DrawScope& operator=(const DrawScope&) = delete;
};
inline void Dropped() {
    if (auto* r = Local().active) { r->outcome = "rejected-by-existing-guard"; r->dropped = true; }
}
// Records completion of a pre-existing ReadBlock flush callback; a completed callback
// may be a no-op on clean memory, not proof of a GPU download or a hardware fence.
inline void Flushed(std::uint64_t cpu, std::size_t bytes) {
    if (auto* record = Local().active) {
        ++record->flush_calls; record->last_flush_cpu = cpu; record->last_flush_size = bytes;
    }
}
// Called around a ReadBlock that Maxwell was already going to perform. Queries cache
// ownership only; the before/after values themselves come from DrawScope snapshots.
class RefreshScope {
    Record* record = nullptr;
    std::array<bool, 5> affected{};
    std::array<std::uint64_t, 5> addresses{};
public:
    template <typename Memory>
    RefreshScope(Memory& memory, std::uint64_t address, std::size_t offset, std::size_t words) {
        record = Local().active;
        if (!record) return;
        ++record->refresh_calls;
        if (!record->inspect) return;
        for (std::size_t i = 0; i < record->words; ++i) {
            const auto index = record->base + i;
            if (index < offset || index - offset >= words) continue;
            affected[i] = true; record->observed[i] = true;
            const auto gpu = address + (index - offset) * 4;
            addresses[i] = gpu;
            const auto cpu = memory.GpuToCpuAddress(gpu);
            record->mapped[i] = cpu.has_value();
            record->cpu[i] = cpu ? *cpu : 0;
            if (cpu) {
                record->tracked_write[i] = LastTrackedWrite(*cpu);
                WatchCounterProducer(record->tracked_write[i]);
            }
            record->gpu_dirty_before[i] = memory.IsMemoryDirty(gpu, 4);
        }
    }
    template <typename Memory>
    void Done(Memory& memory) {
        if (!record) return;
        for (std::size_t i = 0; i < record->words; ++i)
            if (affected[i]) record->gpu_dirty_after[i] = memory.IsMemoryDirty(addresses[i], 4);
    }
};
} // namespace Eden::IndirectDrawLog
