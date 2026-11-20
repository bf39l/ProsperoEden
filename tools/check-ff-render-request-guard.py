#!/usr/bin/env python3
"""Verify the FF negative resize workaround and its executable identity checks."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
code = r"""
#include "ff_render_request_guard.h"
#include <cassert>
#include <vector>
#include <limits>
int main() {
    constexpr std::uint64_t title = 0x0100b8a026f14000ULL;
    std::array<std::uint8_t, 32> build{
        0xb7,0xf9,0x65,0xb9,0xd7,0x22,0x7d,0xb8,
        0xe2,0x9f,0x04,0xe8,0x4e,0xa7,0x33,0x1b};
    std::vector<std::uint8_t> image(0x164d754);
    auto put = [&](std::size_t at, std::uint32_t value) {
        for (unsigned i=0; i<4; ++i) image[at+i] = value >> (8*i);
    };
    const std::uint32_t words[] = {
        0xb9400909,0xb940db88,0xb9000f89,0x6b08013f,
        0x1a9fa7e9,0x0a090189,0x36000569};
    for (unsigned i=0;i<7;++i) put(0x164d68c+4*i,words[i]);
    put(0x164d750,0x54fff72d);
    const auto original = image;
    assert(!Eden::ApplyFFRenderRequestGuard(title+1,"main",build,image));
    assert(!Eden::ApplyFFRenderRequestGuard(title,"sdk",build,image));
    build[31]=1;
    assert(!Eden::ApplyFFRenderRequestGuard(title,"main",build,image));
    build[31]=0;
    assert(!Eden::ApplyFFRenderRequestGuard(title,"main",build,
        std::span<std::uint8_t>(image).first(100)));
    assert(image==original);
    for (unsigned i=0;i<7;++i) {
        image[0x164d68c+4*i]^=1;
        const auto modified=image;
        assert(!Eden::ApplyFFRenderRequestGuard(title,"main",build,image));
        assert(image==modified);
        image=original;
    }
    image[0x164d750]^=1;
    assert(!Eden::ApplyFFRenderRequestGuard(title,"main",build,image));
    image=original;
    assert(Eden::ApplyFFRenderRequestGuard(title,"main",build,image));
    auto expected=original;
    expected[0x164d69d]=0x27; // Only the condition nibble changes.
    assert(image==expected);
    assert(!Eden::ApplyFFRenderRequestGuard(title,"main",build,image));
    assert(image==expected);
    // Model both branches, including the second pass where shrinking is disabled.
    for (std::int32_t count : {0,1,2,3,32,std::numeric_limits<std::int32_t>::max()}) {
        for (std::int32_t request : {std::numeric_limits<std::int32_t>::min(),
                -2147481973,-2147480050,-1,0,1,2,3,32,
                std::numeric_limits<std::int32_t>::max()}) {
            for (bool first_pass : {false,true}) {
                const bool shrink = first_pass &&
                    std::uint32_t(request)<std::uint32_t(count);
                const bool grow = !shrink && request>count;
                if (request<0) assert(!shrink && !grow);
                else assert(shrink==(first_pass && request<count));
            }
        }
    }
}
"""
with tempfile.TemporaryDirectory() as directory:
    source = Path(directory) / "check.cpp"
    binary = Path(directory) / "check"
    source.write_text(code)
    subprocess.run([os.environ.get("CXX", "c++"), "-std=c++20",
                    "-Wall", "-Wextra", "-Werror", "-I", str(root / "headless"),
                    str(source), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print("FF render guard identity, atomic refusal, instruction change and branch checks passed")
