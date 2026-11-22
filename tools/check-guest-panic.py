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
    assert derived.index('::Eden::PanicEvidence') < derived.index('::Eden::RecordGuestPanic')
    assert '#include "core/hle/kernel/physical_core.h"' in derived
    code = r'''#include "guest_fault.h"
#include <cassert>
#include <thread>
#include <vector>
#include <limits>
using u32=unsigned; using u64=std::uint64_t;
enum class BreakReason { Panic, Assert, CppException, User, PreLoadDll };
struct ThreadContext { u64 pc=0x1234,lr=0x5678,sp=0x8000,fp=0; };
struct Memory {
 bool IsValidVirtualAddressRange(u64,u64){return false;}
 u32 Read32(u64){assert(false);return 0;}
 u64 Read64(u64){assert(false);return 0;}
};
struct Arm {void GetContext(ThreadContext&){};};
struct Process {
 Arm arm;Memory memory;
 Arm* GetArmInterface(unsigned){return &arm;}
 Memory& GetMemory(){return memory;}
};
struct System {
 bool shutdown=false, debugger=false;
 Process process;
 bool IsShuttingDown() {return shutdown;}
 bool DebuggerEnabled() {return debugger;}
 System& Kernel() {return *this;}
 System& CurrentPhysicalCore(){return *this;}
 unsigned CoreIndex(){return 0;}
};
Process* GetCurrentProcessPointer(System& s){return &s.process;}
struct Thread { unsigned GetThreadId(){return 81;} };
Thread GetCurrentThread(System&) {return {};}
void Check(System& system, BreakReason break_reason, bool notification_only) {
 u64 info1=0, info2=0;
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
 // Panic evidence is bounded even with a cyclic or malicious guest frame chain.
 unsigned reads32=0, reads64=0; std::vector<std::string> lines;
 auto panic_valid=[](u64 at,u64 size){return at>=0x8000&&at+size<=0x9000;};
 auto panic_read32=[&](u64 at){assert(at==0x8000);++reads32;return 0x2a2u;};
 auto panic_read64=[&](u64 at){++reads64;return at==0x8010?0x8010ull:0x1234ull;};
 auto panic_emit=[&](const char* line){lines.emplace_back(line);};
 Eden::PanicEvidence(0x8000,4,{1,2,0x8000,0x8010},panic_valid,panic_read32,panic_read64,panic_emit);
 assert(reads32==1&&reads64==2&&lines.size()==4);
 assert(lines[1]=="EDEN_GUEST_PANIC_RESULT value=000002a2");
 assert(lines.back()=="EDEN_GUEST_PANIC_CONTEXT_END");
 for(auto fp:{0ull,0x8001ull,0x7ff0ull,~0ull-7})
  Eden::PanicEvidence(~0ull,4,{1,2,0x8000,fp},panic_valid,panic_read32,panic_read64,panic_emit);
 assert(reads32==1&&reads64==2);
 // The engine validity check can accept wrapped ranges; guard before calling it.
 auto wrapped_valid=[](u64,u64){return true;};
 unsigned wrapped_reads=0;
 auto never32=[&](u64){++wrapped_reads;return 0u;};
 auto never64=[&](u64){++wrapped_reads;return u64{0};};
 Eden::PanicEvidence(~0ull-3,4,{1,2,~0ull-15,~0ull-15},wrapped_valid,never32,never64,panic_emit);
 Eden::FaultCallSite(~0ull-15,wrapped_valid,never32,panic_emit);
 assert(wrapped_reads==0);

 reads64=0;
 Eden::PanicEvidence(0,0,{1,2,0x8000,0x8010},panic_valid,panic_read32,
  [&](u64 at){++reads64;return at+16;},panic_emit);
 assert(reads64==48); // strict 24-frame cap
}
'''
    cpp=p/'test.cpp';exe=p/'test';cpp.write_text(code)
    subprocess.run(['c++','-std=c++20','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-pthread',
        '-I'+str(root/'headless'),str(cpp),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('Guest panic recovery: fatal/nonfatal, shutdown/debugger, first fault, concurrent recording and bounded call-site reads PASS')
