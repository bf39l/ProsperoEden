// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
// A guest thread that jumps to an unmapped address takes a prefetch abort, which Eden answers
// by parking that thread for a debugger; without one the game sits on a black screen. The
// first such fault of a session is recorded here so the frontend can end the session like a
// GPU failure (and retry a fault early in the boot).
#include <cstdint>
#include <cstdio>
#include <mutex>
#include <string>
#include <utility>
#include <vector>

namespace Eden {
inline std::mutex guest_fault_mutex;
inline std::string guest_fault;
inline void RecordGuestFault(std::string description) {
    std::lock_guard lock(guest_fault_mutex);
    if (guest_fault.empty()) guest_fault = std::move(description);
}
// Panics are terminal guest failures, not transient early-boot callback races.
inline bool GuestFaultMayRetry(const std::string& description) {
    return !description.starts_with("guest panic:");
}
inline void RecordGuestPanic(std::uint32_t reason, std::uint64_t thread) {
    char line[128];
    std::snprintf(line, sizeof(line), "guest panic: reason %#x on thread %llu", reason,
                  static_cast<unsigned long long>(thread));
    // The engine logger is asynchronous and teardown can strand its final messages.
    // Persist the terminal reason before publishing it to the frontend.
    std::fprintf(stderr, "EDEN_GUEST_PANIC %s\n", line);
    std::fflush(stderr);
    RecordGuestFault(line);
}

struct PanicContext { std::uint64_t pc, lr, sp, fp; };
template<class Valid, class Read32, class Read64, class Emit>
inline void PanicEvidence(std::uint64_t info1, std::uint64_t info2, PanicContext ctx,
                          Valid valid, Read32 read32, Read64 read64, Emit emit) {
    char line[256];
    std::snprintf(line, sizeof(line),
        "EDEN_GUEST_PANIC_CONTEXT pc=%#llx lr=%#llx sp=%#llx fp=%#llx info1=%#llx info2=%#llx",
        static_cast<unsigned long long>(ctx.pc), static_cast<unsigned long long>(ctx.lr),
        static_cast<unsigned long long>(ctx.sp), static_cast<unsigned long long>(ctx.fp),
        static_cast<unsigned long long>(info1), static_cast<unsigned long long>(info2));
    emit(line);
    if (info1 && info2 == 4 && info1 <= UINT64_MAX - 3 && valid(info1, 4)) {
        std::snprintf(line, sizeof(line), "EDEN_GUEST_PANIC_RESULT value=%08x", unsigned(read32(info1)));
        emit(line);
    }
    for (unsigned n = 0; n < 24; ++n) {
        if (!ctx.fp || (ctx.fp & 7) || ctx.fp < ctx.sp || ctx.fp - ctx.sp > 1024 * 1024 ||
            ctx.fp > UINT64_MAX - 15 || !valid(ctx.fp, 16)) break;
        const auto next = read64(ctx.fp);
        const auto lr = read64(ctx.fp + 8);
        std::snprintf(line, sizeof(line), "EDEN_GUEST_PANIC_FRAME index=%u fp=%#llx lr=%#llx",
            n, static_cast<unsigned long long>(ctx.fp), static_cast<unsigned long long>(lr));
        emit(line);
        if (next <= ctx.fp) break;
        ctx.fp = next;
    }
    emit("EDEN_GUEST_PANIC_CONTEXT_END");
}

// Bounded, read-only evidence at the call site. Validate every word; never read the
// invalid branch target, dereference guest object pointers, or scan arbitrary memory.
template<class Valid, class Read, class Emit>
inline void FaultCallSite(std::uint64_t lr, Valid valid, Read read, Emit emit) {
    if (lr < 16 || (lr & 3) != 0 || lr > UINT64_MAX - 12) return;
    for (std::uint64_t address = lr - 16; address < lr + 16; address += 4) {
        char line[128];
        if (!valid(address, 4)) {
            std::snprintf(line, sizeof(line), "EDEN_GUEST_CALL_SITE address=%#llx unmapped",
                          static_cast<unsigned long long>(address));
        } else {
            const auto word = read(address);
            std::snprintf(line, sizeof(line), "EDEN_GUEST_CALL_SITE address=%#llx instruction=%08x%s",
                          static_cast<unsigned long long>(address), static_cast<unsigned>(word),
                          address == lr - 4 ? " before_lr=1" : "");
        }
        emit(line);
    }
}

inline std::string TakeGuestFault() {
    std::lock_guard lock(guest_fault_mutex);
    return std::exchange(guest_fault, {});
}

// The line stderr.log gets for the fault (eden_log.txt has the whole backtrace): the thread, where
// it jumped, and the return addresses that led there, so a report without eden_log.txt still says
// which call it was. The addresses are the game's own; stderr.log names each module's start
// ("cheats: ... for main ... at").
inline std::string FaultLine(const std::string& thread, std::uint64_t id, std::uint64_t pc, std::uint64_t lr,
                             std::uint64_t sp, const std::vector<std::uint64_t>& calls) {
    char head[192];
    std::snprintf(head, sizeof(head), "EDEN_GUEST_FAULT guest thread %llu %s jumped to %#llx: lr %#llx sp %#llx, calls",
                  static_cast<unsigned long long>(id), thread.c_str(), static_cast<unsigned long long>(pc),
                  static_cast<unsigned long long>(lr), static_cast<unsigned long long>(sp));
    std::string line = head;
    if (calls.empty()) line += " unknown";
    for (std::size_t i = 0; i < calls.size() && i < 16; ++i) {
        char call[24];
        std::snprintf(call, sizeof(call), " %#llx", static_cast<unsigned long long>(calls[i]));
        line += call;
    }
    return line;
}
}
