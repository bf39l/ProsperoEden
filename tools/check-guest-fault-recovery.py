#!/usr/bin/env python3
"""Exercise the real COW fault handler with controlled slot transitions."""
from pathlib import Path
import subprocess, tempfile, sys
root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
source = (root / 'src/guest_memory_service.inc').read_text()
start = source.index('bool HandleGuestWriteFault(void* fault) noexcept {')
end = source.index('\nnamespace {\nstruct sigaction', start)
handler = source[start:end]
fixture = r'''
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
constexpr std::size_t SparseSlot = 2 * 1024 * 1024;
constexpr std::uint8_t SlotZero=0, SlotOwn=1, SlotShared=2, SlotFine=3;
struct SparseRange {std::atomic<std::uintptr_t> begin{0x8000000000ull};};
SparseRange range;
std::atomic<std::uintptr_t> probe_expected{0};
std::atomic<bool> probe_mismatch{false};
struct {std::atomic<unsigned> faults{},promotions{},failures{};} counters;
std::uint8_t current = SlotZero;
bool wait_next = false, fail_promotion = false, locked = false;
unsigned promoted = 0;
SparseRange* WriteRangeOf(std::uintptr_t a) noexcept {
 return a >= range.begin && a < range.begin + SparseSlot ? &range : nullptr;
}
bool LockSlot(SparseRange&, std::size_t slot, bool) noexcept {
 assert(slot == 0 && !locked);locked=true;const bool w=wait_next;wait_next=false;return w;
}
std::uint8_t SlotState(SparseRange&,std::size_t) noexcept {assert(locked);return current;}
void UnlockSlot(SparseRange&,std::size_t,std::uint8_t to) noexcept {assert(locked);current=to;locked=false;}
bool PromoteZero(SparseRange&,std::size_t) noexcept {++promoted;return !fail_promotion;}
bool PromoteShared(SparseRange&,std::size_t) noexcept {++promoted;return !fail_promotion;}
bool PromoteFine(SparseRange&,std::size_t) noexcept {++promoted;return !fail_promotion;}
void Note(const char*) noexcept {}
'''
tests = r'''
int main(int argc,char** argv) {
 assert(argc==2);
 void* address=reinterpret_cast<void*>(0x806f2bcd68ull);
 range.begin=0x806f200000ull;
 if(std::strcmp(argv[1],"repeat")==0) {
  // Reclaiming/clearing a page makes the SAME address legitimately fault again.
  // Successful promotions must not count toward the stuck-fault limit.
  for(unsigned i=0;i<192;++i) {
   current=static_cast<std::uint8_t>(i%3 == 0 ? SlotZero : i%3 == 1 ? SlotShared : SlotFine);
   assert(HandleGuestWriteFault(address));assert(current==SlotOwn && !locked);
  }
  assert(promoted==192 && counters.failures==0);
 } else if(std::strcmp(argv[1],"stuck")==0) {
  current=SlotOwn;
  for(unsigned i=0;i<16;++i) assert(HandleGuestWriteFault(address));
  assert(!HandleGuestWriteFault(address));assert(!locked && promoted==0);
 } else if(std::strcmp(argv[1],"failure")==0) {
  fail_promotion=true;
  assert(!HandleGuestWriteFault(address));assert(current==SlotZero && !locked && counters.failures==1);
 } else if(std::strcmp(argv[1],"wait")==0) {
  wait_next=true;current=SlotFine;
  assert(HandleGuestWriteFault(address));assert(promoted==0 && current==SlotFine && !locked);
  assert(HandleGuestWriteFault(address));assert(promoted==1 && current==SlotOwn && !locked);
 } else {
  assert(std::strcmp(argv[1],"outside")==0);
  assert(!HandleGuestWriteFault(nullptr));assert(!HandleGuestWriteFault(reinterpret_cast<void*>(range.begin+SparseSlot)));
  assert(promoted==0 && !locked);
 }
}
'''
with tempfile.TemporaryDirectory() as tmp:
    cpp=Path(tmp)/'test.cpp';exe=Path(tmp)/'test';cpp.write_text(fixture+handler+tests)
    subprocess.run(['c++','-std=c++20','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(cpp),'-o',str(exe)],check=True)
    for case in ('repeat','stuck','failure','wait','outside'):
        result=subprocess.run([str(exe),case],capture_output=True,text=True)
        if result.returncode:
            print(f'FAIL: {case}\n{result.stderr}',flush=True);sys.exit(1)
        print(f'PASS: {case}',flush=True)
