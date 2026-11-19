#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise bounded IPC history, reply parsing, concurrent writers and generated hook ordering."""
from pathlib import Path
import shutil,subprocess,tempfile
root=Path(__file__).resolve().parents[1];scratch=Path((root/'.local/headless-cache').read_text().strip())
service=(scratch/'native-local/headless/hle_service.cpp').read_text()
write=service.index('ctx.WriteToOutgoingCommandBuffer();');read=service.index('eden_reply.data()',write);record=service.index('::Eden::IpcRing::Record(',read)
assert write<read<record
assert 'std::array<u32, 64> eden_reply{};' in service
assert service.count('::Eden::IpcRing::Record(')==1
original=(scratch/'source/src/core/hle/service/service.cpp').read_text()
assert 'if (system.IsPoweredOn()) {' in original and 'if (system.IsPoweredOn()) {' in service
exception=(scratch/'native-local/headless/svc_exception.cpp').read_text()
assert 'if (!notification_only)' in exception and '::Eden::IpcRing::Dump(' in exception
main=(root/'headless/main.cpp').read_text()
assert main.index('Eden::IpcRing::Reset();')<main.index('Core::System system;')
code=r'''
#include "ipc_ring.h"
#include <cassert>
#include <string>
#include <thread>
#include <vector>
int main(){
 using namespace Eden::IpcRing;
 Reset();std::vector<std::string> lines;
 Dump(0,[&](const char* p){lines.emplace_back(p);});assert(lines.empty());
 std::uint32_t reply[8]={1,2,kReplyMagic,0,0x1234,0,0,0};
 Record(std::string(80,'s'),99,17,5,reply,8);
 {std::lock_guard guard{Lock()};const auto e=Entries()[0];assert(Count()==1 && e.magic_at==2 && e.result==0x1234 && e.header[0]==1 && e.header[1]==2 && std::strlen(e.service)==31);}
 Dump(99,[&](const char* p){lines.emplace_back(p);});assert(lines.size()==1 && lines[0].find("BREAKING")!=std::string::npos);
 std::uint32_t short_reply[]={kReplyMagic};Record("short",1,1,1,short_reply,1);
 {std::lock_guard guard{Lock()};assert(Entries()[1].magic_at==-1);}
 Reset();std::vector<std::thread> threads;
 for(unsigned i=0;i<4;++i)threads.emplace_back([&,i]{for(int j=0;j<2000;++j)Record("fsp-srv",i,j,5,reply,8);});
 for(auto& t:threads)t.join();
 {std::lock_guard guard{Lock()};assert(Count()==8000);for(unsigned n=8000-kEntries;n<8000;++n){const auto e=Entries()[n%kEntries];assert(e.sequence==n && e.magic_at==2 && e.result==0x1234);}}
 lines.clear();Dump(1,[&](const char* p){lines.emplace_back(p);Record("during-dump",9,0,0,reply,8);});assert(lines.size()==kEntries);
 assert(lines.front().find("#7936 ")!=std::string::npos && lines.back().find("#7999 ")!=std::string::npos);
 Reset();lines.clear();Dump(0,[&](const char* p){lines.emplace_back(p);});assert(lines.empty());
}
'''
with tempfile.TemporaryDirectory() as t:
 p=Path(t);(p/'check.cpp').write_text(code)
 subprocess.run([shutil.which('clang++-21') or 'c++','-std=c++20','-pthread','-fsanitize=address,undefined','-I'+str(root/'headless'),str(p/'check.cpp'),'-o',str(p/'check')],check=True)
 subprocess.run([str(p/'check')],check=True,timeout=30)
print('IPC history PASS: post-reply capture, 64-entry bounds, reply/header parsing, 8000 concurrent calls, reentrant dumps and session reset (ASan/UBSan)')
