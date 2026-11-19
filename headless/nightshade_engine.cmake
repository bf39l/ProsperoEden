# Adapted from Nightshade validation 1.010.015, Oliv3rmoon and contributors.
# SPDX-License-Identifier: GPL-3.0-or-later
file(READ "${PROJECT_SOURCE_DIR}/src/core/file_sys/registered_cache.cpp" content_source)
# A game with several updates beside it (in updates/ or in its game folder) runs the newest: the
# patch manager takes its code and data by version (ListUpdateVersions, newest first). Eden kept
# the rest of the update by the file it scanned last, which the folder's order decides: the game's
# version and its control data (its save data sizes, its DLC, its version string) could come from
# an older update than its code. They come from the newest too (issue 281).
eden_patch(content_source [=[            entries[{title_id, content_type, title_type}] = file;

            if (title_type == TitleType::Update) {
                versions[title_id] = version;
                UpsertExternalVersionEntry(multi_version_entries, title_id, version, version_string,
                                           content_type, file);
            }
]=] [=[            if (title_type == TitleType::Update) {
                UpsertExternalVersionEntry(multi_version_entries, title_id, version, version_string,
                                           content_type, file);
                // An older update than one already found stays listed, but is not the update.
                if (const auto known = versions.find(title_id); known != versions.end() && known->second > version)
                    return;
                versions[title_id] = version;
            }

            entries[{title_id, content_type, title_type}] = file;
]=])
write_derived("${PORT_BUILD_DIR}/registered_cache.cpp" "${content_source}")
get_target_property(core_sources core SOURCES)
list(REMOVE_ITEM core_sources file_sys/registered_cache.cpp)
list(APPEND core_sources "${PORT_BUILD_DIR}/registered_cache.cpp")
set_property(TARGET core PROPERTY SOURCES "${core_sources}")
# Shared-font input must fit the fixed shared region before decrypting/copying.
file(READ "${PROJECT_SOURCE_DIR}/src/core/hle/service/ns/platform_service_manager.cpp" font_source)
eden_patch(font_source [=[        std::vector<u32> font_data_u32(font_fp->GetSize() / sizeof(u32));]=]
[=[        const auto font_bytes = font_fp->GetSize();
        if (font_bytes < 8 || font_bytes % sizeof(u32) != 0 || offset > SHARED_FONT_MEM_SIZE || font_bytes > SHARED_FONT_MEM_SIZE - offset) {
            LOG_ERROR(Service_NS, "Shared font does not fit; left out");
            impl->shared_font_regions.push_back(EMPTY_REGION);
            continue;
        }
        std::vector<u32> font_data_u32(font_bytes / sizeof(u32));]=])
write_derived("${PORT_BUILD_DIR}/platform_service_manager.cpp" "${font_source}")
get_target_property(core_sources core SOURCES)
list(REMOVE_ITEM core_sources hle/service/ns/platform_service_manager.cpp)
list(APPEND core_sources "${PORT_BUILD_DIR}/platform_service_manager.cpp")
set_property(TARGET core PROPERTY SOURCES "${core_sources}")
