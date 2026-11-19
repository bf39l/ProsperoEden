#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise terminal panic recovery and bounded failed-call diagnostics."""
from pathlib import Path
import subprocess, tempfile, sys
root = Path(__file__).resolve().parents[1]
engine = Path(sys.argv[1])
cmake = (root/'headless/CMakeLists.txt').read_text()
start = cmake.index('file(READ "${PROJECT_SOURCE_DIR}/src/core/hle/kernel/svc/svc_exception.cpp" break_source)')
end = cmake.index('list(REMOVE_ITEM core_sources "hle/kernel/svc/svc_exception.cpp")', start)
with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp)
    script = p/'derive.cmake'
    script.write_text('function(write_derived path content)\nfile(WRITE "${path}" "${content}")\nendfunction()\n'
        + f'set(PROJECT_SOURCE_DIR "{engine}")\nset(PORT_BUILD_DIR "{p}")\nset(EDEN_PORT_DIR "{root}/headless")\n'
        + cmake[start:end])
    subprocess.run(['cmake','-P',str(script)],check=True)
    derived = (p/'svc_exception.cpp').read_text()
    a = derived.index('    if (!notification_only && !system.IsShuttingDown() && !system.DebuggerEnabled() &&')
    b = derived.index('    const bool should_break',a)
    assert derived.index('system.CurrentPhysicalCore().LogBacktrace') < a
    code = r'''#include "guest_fault.h"
#include <cassert>
#include <thread>
#include <vector>
#include <limits>
using u32=unsigned;
enum class BreakReason { Panic, Assert, CppException, User, PreLoadDll };
struct System {
 bool shutdown=false, debugger=false;
 bool IsShuttingDown() {return shutdown;}
 bool DebuggerEnabled() {return debugger;}
 System& Kernel() {return *this;}
};
struct Thread { unsigned GetThreadId(){return 81;} };
Thread GetCurrentThread(System&) {return {};}
void Check(System& system, BreakReason break_reason, bool notification_only) {
''' + derived[a:b] + r'''}
int main() {
 System s;
 for(auto reason:{BreakReason::Panic,BreakReason::Assert,BreakReason::CppException}) {
  Check(s,reason,false);auto fault=Eden::TakeGuestFault();assert(!fault.empty());
  assert(!Eden::GuestFaultMayRetry(fault));assert(Eden::TakeGuestFault().empty());
  Check(s,reason,true);assert(Eden::TakeGuestFault().empty());
  s.shutdown=true;Check(s,reason,false);assert(Eden::TakeGuestFault().empty());s.shutdown=false;
  s.debugger=true;Check(s,reason,false);assert(Eden::TakeGuestFault().empty());s.debugger=false;
 }
 for(auto reason:{BreakReason::User,BreakReason::PreLoadDll}) {
  Check(s,reason,false);assert(Eden::TakeGuestFault().empty());
 }
 Eden::RecordGuestFault("original");Check(s,BreakReason::Panic,false);
 assert(Eden::TakeGuestFault()=="original");assert(Eden::GuestFaultMayRetry("guest jumped"));
 std::vector<std::thread> workers;
 for(int i=0;i<16;++i) workers.emplace_back([]{Eden::RecordGuestPanic(0,81);});
 for(auto& t:workers) { t.join(); }
 assert(!Eden::TakeGuestFault().empty());
 unsigned reads=0, emits=0;
 auto valid=[](auto at,auto size){assert(size==4);return at!=0x1000;};
 auto read=[&](auto at){assert(at!=0x1000);++reads;return 0xd63f0100u;};
 auto emit=[&](const char* line){assert(std::string(line).starts_with("EDEN_GUEST_CALL_SITE"));++emits;};
 Eden::FaultCallSite(0x1010,valid,read,emit);assert(reads==7&&emits==8);
 for(auto lr:{0ull,4ull,15ull,0x1001ull,~0ull-3}) Eden::FaultCallSite(lr,valid,read,emit);
 assert(reads==7&&emits==8);
}
'''
    cpp=p/'test.cpp';exe=p/'test';cpp.write_text(code)
    subprocess.run(['c++','-std=c++20','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-pthread',
        '-I'+str(root/'headless'),str(cpp),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('Guest panic recovery: fatal/nonfatal, shutdown/debugger, first fault, concurrent recording and bounded call-site reads PASS')
