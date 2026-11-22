// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>

namespace Eden {
// A compatibility workaround for observed corrupt GPU-written draw counts. Use
// the engine's refreshing, validated CPU fallback instead of submitting unchecked
// GPU indirect draws. Keep other titles and non-PS5 hosts on their existing path.
inline constexpr bool NeedsValidatedIndirectDraws(std::uint64_t program_id) {
#ifdef PS5_NATIVE
    return program_id == 0x0100B8A026F14000ULL; // Final Fantasy Resonance
#else
    (void)program_id;
    return false;
#endif
}
}
