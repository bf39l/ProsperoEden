// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <algorithm>
#include <array>
#include <cstdint>
#include <span>
#include <string_view>

namespace Eden {
// Captured FF main build. Negative resize requests can drain an inline array
// past zero: main+164d6f4 then clears the backing pointer and +164d788 saves -1.
// Use unsigned LO for the shrink decision. For nonnegative current counts,
// negative requests fail LO and the subsequent signed LE skips the grow path.
// This mitigates the underflow; the producer of invalid requests is unresolved.
inline bool ApplyFFRenderRequestGuard(std::uint64_t title, std::string_view module,
                                     std::span<const std::uint8_t> build,
                                     std::span<std::uint8_t> image) {
    constexpr std::array<std::uint8_t, 32> expected_build{
        0xb7, 0xf9, 0x65, 0xb9, 0xd7, 0x22, 0x7d, 0xb8,
        0xe2, 0x9f, 0x04, 0xe8, 0x4e, 0xa7, 0x33, 0x1b};
    constexpr std::size_t start = 0x164d68c;
    constexpr std::array<std::uint32_t, 7> expected{
        0xb9400909, // ldr w9, [x8, #8]: requested count
        0xb940db88, // ldr w8, [x28, #0xd8]: current count
        0xb9000f89, // str w9, [x28, #0xc]
        0x6b08013f, // cmp w9, w8
        0x1a9fa7e9, // cset w9, lt
        0x0a090189, // and w9, w12, w9
        0x36000569  // tbz w9, #0, main+164d750
    };
    constexpr std::size_t grow_branch = 0x164d750;
    if (title != 0x0100b8a026f14000ULL || module != "main" ||
        build.size() != expected_build.size() ||
        !std::equal(build.begin(), build.end(), expected_build.begin()) ||
        image.size() < grow_branch + 4) return false;
    const auto read = [&](std::size_t offset) {
        return std::uint32_t(image[offset]) | (std::uint32_t(image[offset + 1]) << 8) |
               (std::uint32_t(image[offset + 2]) << 16) | (std::uint32_t(image[offset + 3]) << 24);
    };
    for (std::size_t i = 0; i < expected.size(); ++i)
        if (read(start + 4 * i) != expected[i]) return false;
    if (read(grow_branch) != 0x54fff72d) return false; // b.le main+164d634
    constexpr std::uint32_t replacement = 0x1a9f27e9; // cset w9, lo
    for (unsigned byte = 0; byte < 4; ++byte)
        image[start + 16 + byte] = static_cast<std::uint8_t>(replacement >> (byte * 8));
    return true;
}
}
