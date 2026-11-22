#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run actual MapBufferEx range guards against boundary and overflow inputs."""
from pathlib import Path
import subprocess,sys,tempfile
s=(Path(sys.argv[1])/'src/core/hle/service/nvdrv/devices/nvhost_as_gpu.cpp').read_text()
a=s.index('    // Validate against the alignment-rounded backing');b=s.index('    const DAddr pinned_address',a)
guard=s[a:b]
a=s.index('if (params.buffer_offset < 0 ||');b=s.index(' {',a);condition=s[a:b][3:]
remap=s[s.index('NvResult nvhost_as_gpu::Remap('):s.index('NvResult nvhost_as_gpu::MapBufferEx(')]
assert remap.index('std::scoped_lock lock(mutex);') < remap.index('if (!vm.initialised)')
code=r'''
#include <cassert>
#define LOG_ERROR(...) ((void)0)
#include <cstdint>
#include <limits>
using u64=uint64_t;
enum class NvResult {Success,BadValue};
struct Params {int64_t buffer_offset;u64 mapping_size;};
struct Handle {u64 orig_size;u64 aligned_size;};
NvResult Validate(Params params, Handle* handle){
'''+guard+r'''
return NvResult::Success;
}
bool InvalidRemap(Params params,u64 size){struct {u64 size;}mapping{size};return '''+condition+r''';}
int main(){
Handle h{65536,65536};
assert(Validate({0,0},&h)==NvResult::Success);
assert(Validate({4096,61440},&h)==NvResult::Success);
assert(Validate({65535,1},&h)==NvResult::Success);
assert(Validate({-1,1},&h)==NvResult::BadValue);
assert(Validate({65536,1},&h)==NvResult::BadValue);
assert(Validate({4096,65536},&h)==NvResult::BadValue);
assert(Validate({4096,std::numeric_limits<u64>::max()},&h)==NvResult::BadValue);
// CPU objects need not fill the last GPU page: explicit padded mappings are valid.
Handle padded{60000,65536};
if(Validate({0,65536},&padded)!=NvResult::Success)return 10;
assert(Validate({61440,4096},&padded)==NvResult::Success);
assert(Validate({61440,4097},&padded)==NvResult::BadValue);
assert(Validate({0,0},&padded)==NvResult::Success);
assert(!InvalidRemap({4096,61440},65536));
assert(InvalidRemap({4096,65536},65536));
assert(InvalidRemap({-1,1},65536));
assert(InvalidRemap({65537,0},65536));
assert(InvalidRemap({1,std::numeric_limits<u64>::max()},65536));
// Old length-only check accepted both an overflowing and an out-of-range submap.
assert(!(65536 < u64{65536}));
}
'''
with tempfile.TemporaryDirectory() as d:
    p=Path(d);(p/'test.cpp').write_text(code)
    subprocess.run(['c++','-std=c++20','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(p/'test.cpp'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True)
    # The regressed original-size check must refuse the valid page-padded range.
    (p/'test.cpp').write_text(code.replace('handle->aligned_size','handle->orig_size'))
    subprocess.run(['c++','-std=c++20','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(p/'test.cpp'),'-o',str(p/'test')],check=True)
    assert subprocess.run([str(p/'test')]).returncode==10

print('GPU mapping bounds PASS: actual guards, backing boundaries, negative offsets, integer overflow and remap locking (ASan/UBSan)')
