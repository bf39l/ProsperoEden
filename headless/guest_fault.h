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
    RecordGuestFault(line);
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
