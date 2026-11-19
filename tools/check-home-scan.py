#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise real launcher scan scheduling and deferred Home settings methods with a gated reader."""
from pathlib import Path
import subprocess, tempfile, shutil
root=Path(__file__).resolve().parents[1]
ui=root/'headless/prosperoeden/pe/ui'
def method(file,name):
    s=(ui/file).read_text(); a=s.index('void Launcher::'+name+'('); b=s.index('\n}',a)+2
    return s[a:b]
code=r'''
#include <algorithm>
#include <atomic>
#include <cassert>
#include <chrono>
#include <future>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>
namespace sys { template<class... T> void log(const char*, T...) {} }
const char* tr(const char* s) {return s;}
enum class Screen {home, library, settings};
enum class Modal {none,game}; enum class Key {triangle};
struct Game {std::string file;};
struct Services {
 std::promise<std::vector<Game>> gate; std::atomic<unsigned> calls{0};
 std::vector<Game> games() {++calls; return gate.get_future().get();}
};
struct Launcher {
 Services services_; struct {bool setup_ready=true;} home_;
 Screen screen_=Screen::home; Modal modal_=Modal::none;
 bool library_opened_=false;
 bool opening_on_=true,done_=false,home_frame_presented_=false,initial_scan_requested_=false,games_loaded_=false,game_from_home_=false;
 float initial_scan_retry_wait_=0; std::string selected_game_,pending_home_settings_,message;
 std::future<std::vector<Game>> scan_; std::vector<Game> games_;
 struct {bool wrap=false;int count=0,selected=0;void reset(int n,int i){count=n;selected=i;}} library_;
 unsigned pages=0;
 void frame_presented(); void maybe_start_initial_scan(float);void start_scan();void finish_scan();
 void open_game_settings_from_home(const std::string&);
 void apply_games(std::vector<Game> v){games_=std::move(v);games_loaded_=true;}
 void say(const char* s,bool=false){message=s;}
 void open(Screen s,bool){screen_=s;}
 void refresh_selected_game(){} void sync_grid(bool){}
 void press_library(Key){++pages;modal_=Modal::game;}
};
METHODS
void ready(Launcher& l) {
 for(int i=0;i<2000 && l.scan_.wait_for(std::chrono::seconds(0))!=std::future_status::ready;++i)
  std::this_thread::sleep_for(std::chrono::milliseconds(1));
 assert(l.scan_.wait_for(std::chrono::seconds(0))==std::future_status::ready);
 l.finish_scan();
}
int main(){
 { Launcher l;
   l.maybe_start_initial_scan(1);assert(!l.scan_.valid());
   l.frame_presented(); assert(!l.scan_.valid()); // first swap never scans
   l.maybe_start_initial_scan(1);assert(!l.scan_.valid()); // opening still active
   l.opening_on_=false;l.maybe_start_initial_scan(1);assert(!l.scan_.valid());
   l.frame_presented();assert(!l.scan_.valid());
   l.modal_=Modal::game;l.maybe_start_initial_scan(1);assert(!l.scan_.valid());
   l.modal_=Modal::none;l.maybe_start_initial_scan(0.016f);assert(l.scan_.valid());
   l.maybe_start_initial_scan(1); // no duplicate reader
   auto t=std::chrono::steady_clock::now();
   l.open_game_settings_from_home("folder/game.xci");
   assert(std::chrono::steady_clock::now()-t<std::chrono::milliseconds(100));
   assert(l.screen_==Screen::home && l.pages==0 && l.pending_home_settings_=="folder/game.xci");
   l.finish_scan();assert(l.screen_==Screen::home); // gated reader cannot block the menu
   l.services_.gate.set_value({{"other.nsp"},{"folder/game.xci"}});ready(l);
   assert(l.pages==1 && l.library_.selected==1 && l.game_from_home_ && l.pending_home_settings_.empty());
   assert(l.services_.calls==1);
 }
 { Launcher l;l.opening_on_=false;l.frame_presented();l.maybe_start_initial_scan(1);
   l.open_game_settings_from_home("deleted.xci");l.services_.gate.set_value({{"other.nsp"}});ready(l);
   assert(l.screen_==Screen::home && l.pages==0 && !l.message.empty());
 }
 { Launcher l;l.opening_on_=false;l.frame_presented();l.maybe_start_initial_scan(1);
   l.open_game_settings_from_home("broken.xci");l.services_.gate.set_exception(std::make_exception_ptr(std::runtime_error("bad settings/metadata")));ready(l);
   assert(l.screen_==Screen::home && l.pages==0 && l.games_loaded_);
 }
 { Launcher l;l.home_.setup_ready=false;l.opening_on_=false;l.frame_presented();l.maybe_start_initial_scan(1);assert(!l.scan_.valid()); }
}
'''
methods='\n'.join([method('library.cpp',n) for n in ('frame_presented','maybe_start_initial_scan','start_scan','finish_scan')]+[method('home.cpp','open_game_settings_from_home')])
# Ensure the native frontend and normal update loop actually call these methods.
assert 'if (running) launcher.frame_presented();' in (root/'headless/prosperoeden/frontend.cpp').read_text()
assert 'maybe_start_initial_scan(dt);' in (ui/'launcher.cpp').read_text()
with tempfile.TemporaryDirectory() as t:
 p=Path(t);(p/'check.cpp').write_text(code.replace('METHODS',methods))
 subprocess.run([shutil.which('clang++-21') or 'c++','-std=c++20','-O1','-pthread','-fsanitize=address,undefined',str(p/'check.cpp'),'-o',str(p/'check')],check=True)
 subprocess.run([str(p/'check')],check=True,timeout=30)
print('Home scan PASS: after first swap and completed opening, one background reader; deferred exact-title settings; deleted games and failed scans stay on Home')
