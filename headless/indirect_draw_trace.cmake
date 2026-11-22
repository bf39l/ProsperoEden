# Observation only: preserve the original refresh/read/draw ordering and guard.
macro(draw_trace_replace variable old new)
    string(FIND "${${variable}}" "${old}" draw_trace_at)
    if(draw_trace_at LESS 0)
        message(FATAL_ERROR "Pinned indirect draw trace anchor changed: ${old}")
    endif()
    string(REPLACE "${old}" "${new}" ${variable} "${${variable}}")
endmacro()
if(DRAW_TRACE_MACRO)
    string(PREPEND macro_source "#include \"${EDEN_PORT_DIR}/indirect_draw_log.h\"\n")
    foreach(kind IN ITEMS DrawArraysIndirect DrawIndexedIndirect)
        set(entry "void HLE_${kind}::Fallback(Core::System& system, Engines::Maxwell3D& maxwell3d, std::span<const u32> parameters) {")
        draw_trace_replace(macro_source "${entry}" "${entry}\n    ::Eden::IndirectDrawLog::DrawScope eden_args{\"${kind}\", parameters, 1, maxwell3d.GetRegisterValue(0xD1B), false, IsDrawImplausible(parameters[1], maxwell3d.GetRegisterValue(0xD1B) & parameters[2])};")
    endforeach()
    # Both single-draw paths have the same refresh/guard sequence. Keep it intact.
    draw_trace_replace(macro_source
        "    maxwell3d.RefreshParameters();\n    if (IsDrawImplausible(parameters[1]"
        "    maxwell3d.RefreshParameters();\n    eden_args.Refreshed(parameters);\n    if (IsDrawImplausible(parameters[1]")
    draw_trace_replace(macro_source
        "        maxwell3d.ForceRefreshParameters();\n        if (IsDrawImplausible(parameters[1]"
        "        maxwell3d.ForceRefreshParameters();\n        eden_args.Retried(parameters);\n        if (IsDrawImplausible(parameters[1]")
    draw_trace_replace(macro_source
        "void ReportDroppedDraw(const char* macro, u32 count, u32 instance_count) {"
        "void ReportDroppedDraw(const char* macro, u32 count, u32 instance_count) {\n    ::Eden::IndirectDrawLog::Dropped();")
    draw_trace_replace(macro_source
        "        const std::size_t base = index * indirect_words + 5;\n        if (IsDrawImplausible"
        "        const std::size_t base = index * indirect_words + 5;\n        ::Eden::IndirectDrawLog::DrawScope eden_args{\"MultiDrawIndexedIndirectCount\", parameters, base, ~u32{0}, true, IsDrawImplausible(parameters[base], parameters[base + 1])};\n        if (IsDrawImplausible")
    draw_trace_replace(macro_source
        "                refreshed = true;\n            }\n            if (IsDrawImplausible(parameters[base]"
        "                refreshed = true;\n                eden_args.Retried(parameters);\n            }\n            if (IsDrawImplausible(parameters[base]")
else()
    string(PREPEND maxwell_source "#include \"${EDEN_PORT_DIR}/indirect_draw_log.h\"\n")
    draw_trace_replace(maxwell_source
        "        CallMacroMethod(system, executing_macro, macro_params);"
        "        ::Eden::IndirectDrawLog::ContextScope eden_context{executing_macro, macro_segments, current_macro_dirty, memory_manager};\n        CallMacroMethod(system, executing_macro, macro_params);")
    draw_trace_replace(maxwell_source
        "        memory_manager.ReadBlock(segment.first, &macro_params[current_index],\n                                 sizeof(u32) * segment.second);"
        "        ::Eden::IndirectDrawLog::RefreshScope eden_refresh{memory_manager, segment.first, current_index, segment.second};\n        memory_manager.ReadBlock(segment.first, &macro_params[current_index],\n                                 sizeof(u32) * segment.second);\n        eden_refresh.Done(memory_manager);")
endif()
