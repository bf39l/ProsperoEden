# Nightshade 1.500.000 adoption review

Local adoption branch: `adopt/nightshade-1.500.000-review`, based on
`debug/ff-indirect-draw-provenance` at `c4db6d9`, retaining the pending storage CAS
and allocator repairs (patches 47–48). Nothing has been posted to Nightshade.
Local console testing precedes any promotion to main.

The supplied `/Users/bo/ps5/Nightshade-1.500.000` snapshot remains on Eden
`67bada77f8a43a90da2e94e89b8e7da73c256989`. This fork retains its newer pinned
`d85bad89248fcae68f812d7e1c937436261404cb`. No engine downgrade, app-version bump,
console transfer or save/settings reset is part of this adoption.

## Engine changes reconciled

| Nightshade patch/change | Treatment here |
| --- | --- |
| 01–13: reads, local memory, flushing, CAS, coherence, draw arguments, indexed images and DMA | Already represented by our ordered stack; preserved |
| 14: storage image descriptor arrays | Ported as 49 |
| 15: GPU kind-map locking | Already fixed by our 11 |
| 16: audio underrun accounting | Ported as 50, with native output fade and counters |
| 17: empty shader discovery and retry, header-inclusive fallback | Rebased through 56, 58–59; decoder corruption handling reconciled in 57 |
| 18: preserve guest PCM before sink volume/downmix | Ported as 51 |
| 19: isolate host-worker/guest-core readback scratch | Ported as 52 |
| 20: conversion-specific completion waits | Ported as 53 |
| 21: ASTC decode/recompression by matching block rows | Ported as 54, with Vulkan conversion integration |
| 22: indexed storage-image atomics | Ported as 55 |
| 23: grow shader discovery in blocks | Ported as 56 |
| 24–47: our shared GPU, NVMap, cache and shader hardening | Retained; their additional overflow and compatibility corrections ported in 57 |
| Async texture reservations and teardown | Ported: input/output/layer-scratch accounting, queue rollback, worker-before-context destruction, unlock before erase |
| One-off small-target async shader draws | Adopted while keeping newer Eden side-effect and depth rules |
| Emitted SPIR-V provenance | Adopted alongside our guest hashes, counter/draw tracing and fault logs |
| Unmodded TOTK memory layout guard | Adopted; mods and explicit development override preserve chosen layout |
| Older-engine JIT APIs and less strict heap allocation | Not copied: our newer API adaptations and PTRDIFF/overflow checks are retained |
| Launcher redesign, release branding and automatic per-title async-shader defaults | Outside this engine adoption; existing UI, startup scanning and explicit shader settings retained |

Belladonna is Nightshade's Mesa/RADV PS5 graphics-driver fork, not Eden. This
review does not replace our driver dependency wholesale or claim its release
binary has been upgraded. Existing driver adaptations and stall diagnostics remain.

## Five audit catches

1. **Generated Vulkan loader:** corrected its actual static_vector capacity to
   `Maxwell::MaxShaderProgram`, and validates key/environment counts before loader
   bookkeeping or worker admission. The regression now checks the generated PS5
   loader as well as raw Eden, so preparation cannot silently discard the repair.
2. **New files in patch restoration:** already solved by our shared patch manager.
   It identifies `/dev/null` creations and restores the union of touched files from
   the verified archive. Repeated, damaged, edited and removed patch scenarios are
   covered, including new headers. The standalone sparse ownership header stays.
3. **Panic register wraparound:** corrected all three exact upper bounds. Added
   tests with an intentionally permissive validity callback to catch wrapping
   ranges before any guest read.
4. **Integer sampled buffer merging/cache:** ORs integer metadata on merged
   descriptors. The fork already had a separate internal cache version after
   opting into integer buffers; adoption advances it to `0x50530015` for the shader
   discovery/hash changes. This is an internal cache revision, not an app version.
5. **Multi-title compatibility:** out-of-range TIC indices log and return a zero
   entry without a GPU read. Constant-buffer bank/tail bounds still reject invalid
   access. Decoder words zero/all-ones still fail; other unrecognized encodings
   keep upstream's diagnostic/NOP fallback rather than rejecting all titles.

## FF Resonance leads and test plan

Wrong-type instance words are evidence of bad inputs, not proof of arithmetic
counter overflow. Their bit patterns alone cannot identify the writer, remap
ordering or shader responsible. Existing producer provenance, refreshed arguments,
translation-discontinuity diagnostics and title-scoped indirect safeguards remain.

A controlled comparison can now set `gpu_async=off` in `dev-settings.txt` alongside the app executable; `gpu_async=on` restores
normal behavior. The narrow switch works in release packages too. This switches `use_asynchronous_gpu_emulation`, independently of
asynchronous shader compilation. It defaults on and is reset for each session.
Do not change other settings between captures. Compare bad draw arguments, invalid
shader words, unmapped reads, translation discontinuities and frame behavior.
This is a diagnostic experiment, not a proven fix or a default global slowdown.

The earlier `current_block != 65535` assertion is a 16-bit CPU mapping identifier,
not direct proof of a cached-page reference-count imbalance. Our generated
`Memory::GetSpan` already uses `GuestSpan::OnePiece`, checking every page's pointer,
and does not use matching endpoint tags. Keep that repair and its coverage.

Unimplemented puller messages after an invalid engine word do not establish a
new NVN semaphore command. No guessed command implementation or synchronization
bypass has been added. Likewise, Wave32 requirements are already requested for
compute when subgroup-size control is supported; device capability, fragment
behavior and actual compiled shaders still need evidence before changing them.

The newer engine's shader-side-effect rules and Nightshade's small-target rule
are both retained. Feedback-loop barriers, native float/FP16 behavior and the
8 MiB unsized-storage fallback need controlled reproduction; no arbitrary SSBO
size inflation, shader skip or guest instruction patch was introduced here.
Existing FF guest render-request containment is preserved pending further tests.
A negative guest resize count still requires its object's writer/readback history;
it is not established as a new Unreal instruction or unsupported engine version.

## Validation

Build in the running `prosperoeden-build` Docker container using the documented
release command. `EDEN_SKIP_SOURCE_CHECKS=1` retains the existing architecture
workaround, so package success must not be called a full test-suite pass. Focused
host sanitizer, SPIR-V and production/generated-source regressions are run
separately. Validation logs are retained locally under `debug/nightshade-adoption-20261122/` (ignored by git).
Console gameplay, long-run FF memory pressure, synchronous-GPU comparison and
startup/settings flow still require user testing before merging to main.

## Credit

Thank you to [Oliv3rmoon](https://github.com/Oliv3rmoon), the
[Nightshade contributors](https://github.com/Oliv3rmoon/Nightshade), and their
[detailed review](https://github.com/Oliv3rmoon/Nightshade/issues/6). Adapted code
and tests retain their notices and GPL-3.0-or-later terms. Also thank you to
[heydemoura/ProsperoEden](https://github.com/heydemoura/ProsperoEden), the original
fork this work builds on, and the upstream Eden and yuzu contributors.

Validation completed: the adopted code compiled, linked and packaged successfully
in `prosperoeden-build` at version 1.000.001. Native package inventory/import
checks passed. Focused tests passed for patch restoration, shader bank/TIC bounds,
corrupt-word decoding, rasterizer read isolation, async decoder lifetime/budget,
ASTC/BCn codec equivalence, shader discovery, audio fade/queue behavior, generated
six-stage cache loading, panic wraparound, integer descriptor merging, readback
lifetimes, usage masks, storage spans and shader payload lengths. The 66-module
storage-image SPIR-V validator test passed and compiled the actual PS5 emitter.
The requested 1.000.002 version bump follows this validation; the user will build
that release package and perform console tests. No claim of a complete host suite
or PS5 runtime verification is made.
