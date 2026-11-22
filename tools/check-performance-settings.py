#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""A release build applies the "performance" settings of the settings file (settings_store.h).

headless/preferences_check.cpp checks how they are stored. This checks that the session reads
them for the game it starts and hands each one to the emulator, outside the development-only
dev-settings block, and that the block list is off unless the settings turn it on.
"""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
main = (root / 'headless/main.cpp').read_text()

begin = main.index('#ifdef EDEN_DEV_PROFILE\n        // One-run A/B switches')
end = main.index('#else', begin)
release = main[:begin] + main[end:]  # what a release build compiles

assert 'const auto speed = Eden::LoadPerformance(eden_game_title_id(guest));' in release
for statement in (
    'Settings::values.use_asynchronous_shaders = speed.async_shaders;',
    'Settings::values.gpu_accuracy.SetValue(Settings::GpuAccuracy::Low);',
    'Settings::values.current_gpu_accuracy = Settings::GpuAccuracy::Low;',
    'Settings::values.cpu_accuracy = Settings::CpuAccuracy::Unsafe;',
    'Settings::values.dma_accuracy.SetValue(Settings::DmaAccuracy::Unsafe);',
    'Settings::values.use_reactive_flushing.SetValue(speed.reactive_flushing);',
    'Settings::values.skip_cpu_inner_invalidation.SetValue(speed.skip_invalidation);',
    'Common::SetGuestMemoryFine(speed.compact_memory || dev_cram_fine);',
    'Settings::values.use_speed_limit.SetValue(speed_percent > 0);',
    'Settings::values.speed_limit.SetValue(static_cast<u16>(speed_percent > 0 ? speed_percent : 100));',
):
    assert statement in release, statement
for guard in ('if (speed.fast_gpu) {', 'if (speed.unsafe_cpu)', 'if (speed.unsafe_dma)'):
    assert guard in release, guard
# Every session starts at the exact levels, before the settings are read: one app run starts many
# games, and a level the game before lowered would stay for the next one.
start = release.index('Settings::values.cpu_accuracy = Settings::CpuAccuracy::Auto;')
read = release.index('const auto speed = Eden::LoadPerformance(eden_game_title_id(guest));')
for statement in (
    'Settings::values.gpu_accuracy.SetValue(Settings::GpuAccuracy::High);',
    'Settings::values.current_gpu_accuracy = Settings::GpuAccuracy::High;',
    'Settings::values.dma_accuracy.SetValue(Settings::DmaAccuracy::Default);',
):
    assert start < release.index(statement) < read, statement
# Nothing sets the shaders back to synchronous after the setting was applied.
assert 'Settings::values.use_asynchronous_shaders = false;' not in main

# The block list: off unless the settings turn it on, and block-list.txt still turns it on.
assert 'if (!dev_block_list) Eden::JitList::enabled = speed.block_list;' in release
store = (root / 'headless/settings_store.h').read_text()
assert 'bool block_list = false;' in store and 'bool block_list = true;' not in store
assert 'if (std::filesystem::exists(Eden::AppFile("block-list.txt"))) Eden::JitList::enabled = true;' in release

# Settings > Performance in the launcher: its eight switches are the general values.
services = (root / 'headless/prosperoeden/eden_services.cpp').read_text()
load = services.split('pe::ui::Preferences EdenServices::preferences() {', 1)[1].split('\n}\n', 1)[0]
save = services.split('bool EdenServices::set_preferences(', 1)[1].split('\n}\n', 1)[0]
assert 'const Eden::PerformanceSettings speed = Eden::LoadPerformance(0);' in load
for name in ('block_list', 'async_shaders', 'fast_gpu', 'unsafe_cpu', 'unsafe_dma', 'reactive_flushing',
             'skip_invalidation', 'compact_memory'):
    assert f'result.{name} = speed.{name};' in load, name
    assert f'speed.{name} = preferences.{name};' in save, name
# The speed limit (Settings > Performance > Speed limit) is a general value too, and its first step
# is 100%: the speed every session had before the setting existed.
assert 'result.speed_limit = speed.speed_limit;' in load
assert 'speed.speed_limit = std::clamp(preferences.speed_limit, 0,' in save
assert 'inline constexpr int kSpeedLimitPercent[] = {100, ' in store
assert 'int speed_limit = 0;' in store
assert 'Eden::PerformanceSettings speed = Eden::LoadPerformance(0);' in save
assert 'Eden::SavePerformance(0, speed)' in save
# Every session resets to 4 GiB. After the game's settings and enabled mods
# are known, the compatibility guard chooses the layout before Core construction.
assert 'Settings::values.memory_layout_mode = Settings::MemoryLayout::Memory_4Gb;' in release
layout = release.index('Settings::values.memory_layout_mode =\n')
mods = release.index('const auto all_mods = Eden::Mods::List(')
guard = release.index('const int layout = Eden::MemoryLayoutGuard::Layout(')
assert read < mods < guard < layout < release.index('Core::System system;')
assert 'title, speed.memory_layout, mods_on,' in release[guard:layout]
assert 'dev_layout_guard_off' in release[guard:layout]
selection = release[release.index('            const bool mods_on =', mods):layout]
assert 'Eden::Mods::CheatsOnly(mod)' in selection
assert 'std::find(mods_off.begin(), mods_off.end(), mod.name) == mods_off.end()' in selection
layout_end = release.index(';', layout) + 1
assignment = release[layout:layout_end]
for case in ('layout == 1 ? Settings::MemoryLayout::Memory_6Gb',
             'layout == 2 ? Settings::MemoryLayout::Memory_8Gb',
             'Settings::MemoryLayout::Memory_4Gb;'):
    assert case in assignment, case
# Execute the actual session selection/assignment with the real policy header.
# This catches bypassing the guard, ignoring disabled mods or treating cheats as mods.
code = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <string>
#include <vector>
#include "memory_layout_guard.h"
namespace Settings {
enum class MemoryLayout {Memory_4Gb,Memory_6Gb,Memory_8Gb};
inline struct {MemoryLayout memory_layout_mode;} values;
}
namespace Eden::Mods {
struct Mod {std::string name;bool cheats=false;};
bool CheatsOnly(const Mod& mod){return mod.cheats;}
}
Settings::MemoryLayout Select(std::uint64_t title,int chosen,
    const std::vector<Eden::Mods::Mod>& all_mods,const std::vector<std::string>& mods_off,
    bool dev_layout_guard_off=false){
    struct {int memory_layout;} speed{chosen};
'''+selection+assignment+r'''
return Settings::values.memory_layout_mode;
}
int main(){
 constexpr std::uint64_t totk=0x0100F2C0115B6000,ff=0x0100B8A026F14000;
 using L=Settings::MemoryLayout;
 assert(Select(totk,2,{}, {})==L::Memory_4Gb);
 assert(Select(totk,1,{}, {})==L::Memory_4Gb);
 assert(Select(totk,0,{}, {})==L::Memory_4Gb);
 assert(Select(ff,2,{}, {})==L::Memory_8Gb);
 assert(Select(ff,1,{}, {})==L::Memory_6Gb);
 assert(Select(totk,1,{{"mod",false}}, {})==L::Memory_6Gb);
 assert(Select(totk,2,{{"mod",false}}, {})==L::Memory_8Gb);
 assert(Select(totk,2,{{"mod",false}}, {"mod"})==L::Memory_4Gb);
 assert(Select(totk,2,{{"cheats",true}}, {})==L::Memory_4Gb);
 assert(Select(totk,2,{}, {},true)==L::Memory_8Gb);
 assert(Select(totk,1,{{"mod",false}}, {"mod"},true)==L::Memory_6Gb);
}
'''
with tempfile.TemporaryDirectory() as tmp:
    tmp=Path(tmp);cpp=tmp/'layout.cpp';exe=tmp/'layout'
    cpp.write_text(code)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++20','-Wall','-Wextra','-Werror',
                    '-fsanitize=address,undefined','-I'+str(root/'headless'),
                    str(cpp),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
assert 'Memory layout: ' in release  # the session says which one it uses
assert 'inline constexpr const char* kMemoryLayoutKeys[] = {"4Gb", "6Gb", "8Gb"};' in store
assert 'int memory_layout = 0;' in store
assert 'kMemoryLayoutKeys[value.memory_layout]' in store
# Above the Switch's own 4 GiB the block is the one backed where the kernel uses it, and a refusal
# says which step refused it instead of leaving the session to die somewhere else.
pages = (root / 'src/memory_pages.cpp').read_text()
assert 'void* AllocateGuestMemoryWhereUsed(std::size_t size) noexcept {' in pages
assert 'EDEN_GUEST_MEMORY sparse refused bytes=%zu step=%s' in pages
# The menu holds it too, so nobody has to open the settings file: Settings > Performance > Memory,
# a row after the switches whose value is one of the three sizes and reaches the same key. Every
# language already says "Memory" (the overlay's piece of the same name), and the sizes are numbers,
# so the row adds no text a catalog has to translate.
ui = (root / 'headless/prosperoeden/pe/ui/settings.cpp').read_text()
launcher = (root / 'headless/prosperoeden/pe/ui/services.hpp').read_text()
assert 'int memory_layout = 0;' in launcher
assert 'speed_memory_layout, // the memory a game\'s console is told it has' in ui
assert 'constexpr const char *kMemoryLayouts[] = {"4 GiB", "6 GiB", "8 GiB"};' in ui
assert 'result.memory_layout = speed.memory_layout;' in load
assert 'speed.memory_layout = std::clamp(preferences.memory_layout,' in save
# The clamped value is the last word on it: a plain copy of what the launcher sent would leave a
# number outside the three layouts in place, and SavePerformance refuses one, which would take the
# rest of the page's settings with it.
assert 'speed.memory_layout = preferences.memory_layout;' not in save
assert 'prefs_.memory_layout =' in ui and 'TR("Memory")' in ui
# A change is worth a line on where it arrives, and the words for that are already translated.
assert 'else if (modal_ == Modal::performance && (option_ == speed_memory_layout || option_ == speed_limit_row))' in ui
assert 'Saved. Applies when a game starts.' in ui
# The switches keep their own count: the dialog's rows are the switches, the speed limit and this
# one, and the line under them describes the switches and the speed limit only.
assert 'constexpr int kPerformanceSwitches = speed_limit_row;' in ui
assert 'kAbout[kPerformanceSwitches]' in ui and 'kNames[kPerformanceRows]' in ui
print('Performance settings: the block list, shaders, GPU, CPU and DMA accuracy, flushing and invalidation, '
      'the console memory and the speed limit reach the session, and the menu writes them PASS')
