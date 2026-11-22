# PS5: total vertices alone misses small meshes with tens of millions of instances.
# Keep the existing force-refresh/recheck/drop control flow and product limit.
set(draw_guard_old "bool IsDrawImplausible(u32 count, u32 instance_count) {")
set(draw_guard_new [=[bool IsDrawImplausible(u32 count, u32 instance_count) {
    // FF Resonance submitted six indices with 27-31 million instances, stopping the
    // GPU before the product-only guard rejected it. A zero-count draw is still a
    // no-op. Keep a generous 1,048,576-instance ceiling for CPU-decoded PS5 draws.
    if (count != 0 && instance_count > (u32{1} << 20)) {
        return true;
    }
]=])
macro_replace("${draw_guard_old}" "${draw_guard_new}")

# Native GPU indirect draws bypass IsDrawImplausible entirely. For the affected
# title, enter the existing refreshing fallback BEFORE native draw state is set.
# Do not read a CPU mirror and then submit the original GPU buffer: later GPU
# writes could invalidate that check. Fallback issues direct, validated values.
string(PREPEND macro_source "#include \"${EDEN_PORT_DIR}/indirect_draw_policy.h\"\n#include \"core/core.h\"\n")
foreach(kind IN ITEMS DrawArraysIndirect DrawIndexedIndirect MultiDrawIndexedIndirectCount)
    set(native_entry "void HLE_${kind}::Execute(Core::System& system, Engines::Maxwell3D& maxwell3d, std::span<const u32> parameters, [[maybe_unused]] u32 method) {")
    macro_replace("${native_entry}" "${native_entry}\n    if (::Eden::NeedsValidatedIndirectDraws(system.GetApplicationProcessProgramID())) {\n        static std::atomic<bool> eden_reported{false};\n        if (!eden_reported.exchange(true, std::memory_order_relaxed)) {\n            std::fprintf(stderr, \"EDEN_INDIRECT_VALIDATION macro=${kind} mode=refreshed-cpu-fallback%c\", 10);\n        }\n        Fallback(system, maxwell3d, parameters);\n        return;\n    }")
endforeach()
