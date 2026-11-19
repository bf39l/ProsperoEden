// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "settings_store.h"
#include <sys/stat.h>

namespace Eden {
struct GameHistory {
    std::string last;
    std::vector<std::string> recent;
};

// Inspect only saved entries, never scan the library while Home opens. Missing,
// removed or inaccessible ROMs (and folders posing as ROMs) are simply omitted.
// Do not erase saved history: a temporarily disconnected drive may come back.
inline GameHistory ExistingGameHistory(std::string_view roms, std::string_view last,
                                       const std::vector<std::string>& recent) {
    const auto exists = [&](std::string_view name) {
        if (roms.empty() || !ValidRomPath(name)) return false;
        std::string path(roms);
        if (path.back() != '/') path += '/';
        path += name;
        struct stat info{};
        return stat(path.c_str(), &info) == 0 && S_ISREG(info.st_mode);
    };
    GameHistory result;
    for (const auto& name : recent)
        if (exists(name)) result.recent.push_back(name);
    if (exists(last)) result.last = last;
    else if (!result.recent.empty()) result.last = result.recent.front();
    return result;
}
} // namespace Eden
