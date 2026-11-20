# Nightshade engine adaptations

Source: [Nightshade](https://github.com/Oliv3rmoon/Nightshade), by
[Oliv3rmoon](https://github.com/Oliv3rmoon) and the Nightshade contributors.
Thank you for sharing these improvements and regression checks under
GPL-3.0-or-later. This integration uses the user-provided
`Nightshade-nightshade-validation-1.010.015` snapshot, not Nightshade's current main.
See [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md#nightshade-engine-adaptations).

This fork started from [heydemoura/ProsperoEden](https://github.com/heydemoura/ProsperoEden).
Thank you to [heydemoura](https://github.com/heydemoura), the original ProsperoEden
contributors, the Eden team, Oliv3rmoon and the Nightshade contributors.

## Engine and identity

Keep Eden `d85bad89248fcae68f812d7e1c937436261404cb` and LLVM 21. Nightshade's
snapshot pins the older `67bada77f8a43a90da2e94e89b8e7da73c256989`; it is not copied
over this engine. Older fmt and removed small-vector API anchors are rebased.
The application remains ProsperoEden, PPSA99018, content version `01.000.001`.

## Imported engine changes

| Area | Change |
| --- | --- |
| Audio | Recover a full PCM queue by dropping complete old buffers while preserving queue accounting. Invalid oversized buffers remain errors. |
| Guest timing | Normal clock by default; optional per-game adaptive clock, with session state reset. |
| Memory spans | Check every page's host offset before using a direct-read span; otherwise use the safe fallback. |
| Shader/GPU correctness | Patches 15–23: relative post-processing paths, atomic CAS/coherence/cache operations, GPU-written indirect arguments, bounded indexed storage images, and DMA constant fills. |
| Vulkan textures | Layer-at-a-time ASTC conversion in the actual Vulkan copy of texture utilities, chunked transfers, and bounded background conversion work. Light scenes may send moderate textures to background conversion instead of freezing all conversion workers. |
| Staging memory | Large mapped transfers rounded in 16 MiB steps, capacity-checked buffer reuse, completed idle buffers released before one retry, and large transfers split into chunks. |
| CPU scheduling | Read-before-write spin locks, PAUSE in context retries, and adaptive idle polling with interrupt timestamps and corrected idle CPU accounting. |
| GPU device loss | Write the crash report and close on `VK_ERROR_DEVICE_LOST`; the GPU worker reports immediately instead of entering normal teardown. Ordinary exception recovery remains unchanged. |
| Shutdown | Request timing-thread stop before waking its waits, preventing a consumed wake from hanging join. |
| Update selection | Keep code/control/version entries from the newest update regardless of directory scan order; retain the other versions in the version list. |
| NSO decoding | Require the decoded ZBIC byte count to equal the declared segment size, including positive-but-short results. Existing layout/BSS/patch/dump handling is retained. |
| Fault logging | Log the first 64 unmapped accesses, then powers of two, with the total count. Reset before each guest session; memory access behavior is unchanged. |
| Startup diagnostics | Keep a 64-entry service-reply ring in memory, dump it on non-notification svcBreak, and report prolonged first-frame startup at 45/90/180 seconds. Both renderers use the watcher; it does not stop or restart the game. |
| Shared fonts | Reject short, unaligned, oversized or overflowing font input before reading/copying into shared memory. Font-mod UI/features are not imported. |
| Shader-cache reads | Buffered, chunked reads and positions; preserve valid entries of a damaged/truncated cache. |
| Shader startup | Bounded background pipeline loading on Vulkan, duplicate ownership/save coordination, stop/join before teardown, startup worker placement and later return to spare CPUs. OpenGL remains foreground. |
| Memory pressure | Reclaim empty heap pieces/arenas and free runs; fragmented backing for large allocations, reusable direct-memory ranges, guest reserve, and graphics-cache budgeting. Reject impossible allocation sizes before reaching the host allocator. |

The heap's 6 GiB is a reserved address range, backed as needed; the fallback that
cannot reserve a range still takes 3 GiB. The guest reserve has a 1 GiB target,
filled incrementally, released with the session. These policies share the PS5's
CPU/GPU memory pool and require long-session console testing.

The entire ordered patch stack is restored and applied together when changed.
Unchanged sources are verified against a receipt; damaged/changed stacks rebuild
from the pinned archive, retaining the fork's existing patches.

## Existing fixes retained

- The PS5 VFS cache stays at 64 host handles per instance. Commit `ad7d62d`
  addressed scan-time EMFILE. Final Fantasy Tactics: The Ivalice Chronicles ran
  with OpenGL at 64; Tears of the Kingdom also started. This is not a limit on
  the assets a game may open.
- Preserve NCA short-read/indirect-update handling, firmware checks, file diagnostics,
  unknown-system-archive handling, settings recovery, and game-content teardown.
- Preserve program-switch callbacks/launch parameters, the Vulkan attribute-handle
  workaround, recent subfolder paths/deleted-game handling, and successful repeated
  guest-write recovery (reset both address and repeat count after promotion).
- Keep existing driver-cache atomic writes and pipeline wait striping; these were
  already present. Do not restore the old Boost small-vector helper, downgrade
  dependency pins, or import Nightshade UI/updater/streaming/NCZ features.

## Home startup and Continue Playing settings

Nightshade starts its scan in the constructor and can wait for it when entering
Library. This fork retains a later, nonblocking start: the first successful Home
swap only records readiness; the update loop starts one background reader after
the opening finishes. It does not scan synchronously on the first frame.

Continue Playing → Game settings queues the exact relative game path while the
scan runs and stays on Home. The completed list opens that game's settings.
A missing game or scan exception leaves Home available and logs the failure.
The menu never waits on the future; leaving Home or starting a game cancels the
pending settings action. A failed attempt to create the worker can retry after
2 seconds. `game list: starting background scan` identifies scan starts in logs.
Nightshade's library.json export is not a startup metadata cache.

## Build and validation

Use the existing running container and the workflow in
[BUILD_WITH_DOCKER.md](BUILD_WITH_DOCKER.md):

```bash
docker exec -w /workspace prosperoeden-build bash -lc 'EDEN_SKIP_SOURCE_CHECKS=1 make release JOBS=4'
```

That switch skips host source checks affected by Apple Silicon/x86 translation;
package validation still runs. Run supported focused engine checks separately.
Native x86 CI retains ThreadSanitizer; the translated container explicitly reports
that its shadow-memory layout is unsupported and runs supported sanitizer cases.
The existing JIT test also refreshes translated RX code after verifying both
aliases; the production PS5 allocator is unchanged by that test accommodation.

Focused checks cover audio queues, clock reset, contiguous spans, CAS/image/DMA
patches, staging sizes/chunks/refusal recovery, shader cancellation and duplicate
ownership, font boundaries, shutdown wake ordering, update scan permutations,
heap ownership/reclamation under concurrent use, and actual Home scan/settings
methods with a blocked reader. Existing COW recovery and performance-settings
regressions remain in use.

The memory-soak model improved from three failing synthetic seeds with its old
control rules to one of five with the imported rules; four recorded memory traces
passed. This model is not proof that every long PS5 session avoids allocation
failure. ThreadSanitizer and PS5 validation must be reported separately.

## Verified integration build — 2026-11-19

`EDEN_SKIP_SOURCE_CHECKS=1 make release JOBS=4` completed successfully in the
existing `prosperoeden-build` container. Native package inventory, fixture,
alignment and import validation passed. The final ZIP's integrity, checksum,
app identity, executable bytes and both project credits were verified.

Outputs: `build/release/PPSA99018`, `dist/ProsperoEden-v1.000.001.zip`, and
`build/symbols/ProsperoEden-v1.000.001.elf` (retain for crash symbolization).
ZIP SHA-256: `59162fefa515a154940673b77ed9b410b1c8d0a6cc727d48808ae5a36016b171`.

Supported focused regressions passed for the new engine behavior and retained
settings/history, NSO loading, audio/cheat shutdown, failed-load/content teardown,
repeated COW recovery, JIT aliases, and Home behavior. The whole host source suite
was not run as the final package gate; native-x86 race checks and PS5 tests remain
separate. The memory model limitation above remains.

## GPU device loss recovery

Adapt Nightshade's close-with-report policy for `VK_ERROR_DEVICE_LOST` on any
reporting thread, including the native GPU worker. The worker calls the fatal
reporter immediately so teardown does not wait on the failed GPU. The report and
restart note say the app closes, and the exit helper is used instead of restarting.
Ordinary crashes keep their existing restart/no-restart-loop policy; ordinary
worker errors keep their existing stop/failure path.

A driver-facing `eden_gpu_stalled` hook can mark a detected stall so a subsequent
fault also closes. The current driver must actually call it to provide that
signal; this port does not add Belladonna's complete stall-dump instrumentation
or claim to detect every GPU hang. Closing avoids an automatic restart onto a
failed GPU, but cannot guarantee recovery from a console-level driver fault.

The crash reporter tests pass both host and mocked-console calls: device-loss
exceptions, explicit fatal device-loss calls, and faults after a marked stall
write one report and exit without restarting. Native-worker tests cover device
loss and ordinary exceptions, as well as creation failure, stop/wake/join and
blocked-command teardown. The Docker release build and package validation pass.

Release 1.000.001 retains Eden `d85bad89`. Any `eden-nx2` migration is deferred to
a separate experiment after this release, not included in this branch.

## Diagnosing a stalled startup

`/data/prosperoeden/logs/stderr.log` gets `EDEN_START_WAIT` once at 45, 90 and
180 seconds in the final starting step, until the first picture arrives. It names
whether the GPU recently had an empty command queue, completed service-call
count and time since the last completed call. At 45 and 180 seconds it also prints
the latest calls as `EDEN_IPC_RING`. A load stuck in an earlier step is outside
this watcher's scope.

On a non-notification guest `svcBreak`, Eden's normal log also receives the ring,
including thread, service/command/type, reply-header words and CMIF result when
found. Check `/data/prosperoeden/user/log/eden_log.txt` alongside stderr.log.
`EDEN_BREAK_DURING_STOP` labels a break observed after shutdown already began;
it does not suppress the break or change the service reply.

Recording is bounded and silent during ordinary play; no per-call heap allocation
or per-call file logging is added. IPC and unmapped-access counters reset before
constructing each guest. The ring is a history of completed replies, not a full
trace of pending calls and not proof of a particular stall's root cause.

The follow-up Docker build/package validation and focused diagnostic checks pass:
77 log lines for a million invalid accesses; real ZBIC round-trips and malformed
frames; short/long/exact NSO decode-size cases; 8,000 concurrent IPC records,
wraparound, reentrant dumps and resets; timed watchdog reports; retained Home and
repeated COW recovery checks. Architecture-related test exclusions remain as above.

## Console comparison

1. Test Home startup with a populated library, wait for the opening to finish,
   and open Continue Playing → Game settings, including immediately after startup.
2. Test a removed recent game and a missing/invalid game directory; Home must stay
   responsive. Preserve stderr.log and boot-trace.txt if a scan does not finish.
3. Compare the same game/save/scene, renderer and speed limit as Nightshade for
   audio/frame pacing; test another session to check state resets.
4. Test quitting during shader loading, switching programs, DLC/updates, and a long
   open-world session. Capture EDEN_SHADER_START, EDEN_MEMORY, heap and crash logs.

For a title needing the old clock workaround, set `adaptive_clock: true` under
its `games/<title-id>` JSON entry. Normal timing is the default. To compare
foreground shader loading, set `background_shader_cache: false` in that title's
`performance` object (or the global performance object); there is no new UI switch.

## Final Fantasy diagnostic follow-up

Ported Nightshade's validation 1.010.015 pipeline identity/thread activity trace
and v1.012.002 reactive-flush/guest-fault diagnostics, with Oliv3rmoon/Belladonna
318deb146daa's GPU stall report. Eden remains pinned to d85bad89, verified against
Eden master on 2026-11-19. Neither the engine nor the driver revision is downgraded.

- `EDEN_PIPELINE`: Vulkan handle, pipeline key and stage hashes after creation.
  A crash during compilation names its key/hash on the crash report's `doing:` line.
- `radv/ps5 stall`: after the existing ten-second driver timeout, the submission,
  waits, first unmet wait, preceding draws/dispatches and matching shader code.
  It marks the GPU stalled before inspecting it, preserving close-on-device-loss.
- `EDEN_REACTIVE_FLUSH`: first 64 GPU-to-guest copies, then powers of two per game,
  with read address, copied range and up to 32 before/after bytes within a page.
  The first 16 also reach stderr; image lines describe already-requested downloads.
  Logging adds no new GPU download or synchronization operation.
- `EDEN_UNMAPPED_READ`: first 32 A64 callback reads with PC/LR/SP, first four also
  in stderr; `EDEN_GUEST_FAULT` adds thread and up to 16 return addresses.
  Existing guest-fault handling remains in control.
- The independent crash flusher also attempts to drain Eden's log after stderr
  and stdout; it cannot delay the separate process exit/restart helper.

Reproduce the same FF scene with Vulkan. Preserve `/data/prosperoeden/logs/`
(including stderr and crash sidecars) and `/data/prosperoeden/user/log/eden_log.txt`.
These diagnostics identify the remaining failure; they do not establish a fix
for FF or prove that stale GPU data is its cause. Existing ATOM.CAS/ATOMS.CAS,
coherence and cache-operation shader fixes remain applied.

Final FF diagnostic Docker validation: the PS5 app and patched RADV built and
packaged successfully; ZIP integrity and packaged executable match verified.
The driver test checked the actual patched source, PM4/register definitions and
call sites, not only a copied fixture. Reactive flush bounds/reset, shader-cache
concurrency, crash pipeline identity/device-loss behavior and safe Home scanning
checks passed. On this ARM/Rosetta container, supported ASan/UBSan checks were
used; native x86 ThreadSanitizer remains for CI. FF gameplay is not yet verified.

### Quieter detailed logging

Detailed logging now starts at Info and enables Debug only for Render,
Render.Vulkan, HW.GPU, Shader and Core.ARM. Service polling and filesystem
Debug traffic no longer fill the engine log while graphics diagnostics are
being collected. Warning/error messages and the separate bounded stderr GPU
diagnostics remain enabled. An explicit development log_filter still overrides
this profile. Docker release build and package validation passed.

## Indirect draw argument provenance (new diagnostic branch)

`debug/ff-indirect-draw-provenance` adds `EDEN_DRAW_ARGS` and `EDEN_DRAW_SOURCE`
to stderr, independently of the Detailed logs setting. The current Eden master
pin, refresh policy, draw rejection threshold and accepted draw calls are retained.
No full PS5 build was run for this addition: the user will build it. Focused
ASan/UBSan checks and generation against the actual patched Eden sources pass.

The CPU fallback paths for arrays/indexed/multi-indexed indirect macros record:

- Macro method, sequence, host monotonic observation timestamp, raw words, instance
  mask, count/instances before the existing refresh and after it or a forced retry.
- The exact macro segment source: inline command or GPU virtual address; mapped
  device/CPU address and GPU-cache dirty state for sampled suspicious arguments.
- Existing refresh-read and completed FlushRegion callback counts. A completed
  callback may be a no-op; it does not prove a GPU download or a hardware fence.
- Recent matching Vulkan buffer write-tracking marks from a 128-entry thread-local
  history: range and needs_sync flag. These show producer intent, not completion.
  A missing entry means unknown/evicted, not proof that the GPU never wrote it.
- The existing rejection outcome. The last eight CPU draw observations are
  printed with the first suspicious draw for context.

Diagnostic suspicion starts at one million instances or 2^26 count*instances;
this ONLY selects logging. The existing guard is unchanged. The first 32 accepted and first 32 rejected suspect
draws, then powers of two in each category, are logged; state resets per game session.
Ordinary draws do not add cache-ownership queries. No new GPU reads, waits,
refreshes, readbacks or draw rejection are introduced.

`queued_checked` and `refresh_observed` qualify the cache flags: zero means the
state was not sampled, not that the range was clean. An argument that first
becomes suspicious after refresh has value snapshots but can lack pre-refresh
ownership samples. Multi-draw per-record baselines follow that macro's initial
batch refresh (`baseline=after-multi-refresh`); an existing forced retry is
recorded separately. The GPU-native indirect path is not decoded by this CPU
trace; the existing driver stall report still captures GPU work.

Interpretation: bad queued values replaced by sane refreshed values suggest a
stale command-list snapshot; bad values surviving a refresh, missing dirty
tracking despite a recent write mark, or suspicious values appearing after a
refresh point to different producers/coherency paths for investigation. These
observations narrow the next check; none alone proves a synchronization defect
or identifies the exact guest instruction that wrote the counter.

Focused check (inside the running container):

```bash
python3 -B tools/check-indirect-draw-log.py "$(cat .local/headless-cache)/source"
```

The 212533 console test exposed two observation issues, corrected locally: use
the exact one-argument `GpuToCpuAddress(address)` rather than the range-search
overload, and keep separate accepted/rejected sampling budgets. The latter
prevents repetitive rejected draws from hiding an accepted dangerous draw.
Regression checks cover exact offsets and accepted samples after rejected-budget
exhaustion. Full rebuilding of these corrections is left to the user.

## Counter producer tracing and PS5 draw containment

The corrected 213328 console trace matched a 27,232,513-instance CPU draw to the
stalled GPU submission. Its argument range was recently marked for GPU writing,
but the cache reported clean and skipped normal refresh. Existing forced refresh
also left the same value on sampled larger rejected draws.

`EDEN_DRAW_PRODUCER` now associates each matched write mark with the active
graphics pipeline key and six stage hashes, or compute shader hash, plus a work
sequence and logical storage/image-buffer binding slot. The printed byte offset
locates the argument within that writable range. Identity scopes wrap pipeline
configuration on the GPU emulation thread, not asynchronous shader compilation.
`intent_only=1` is deliberate: a writable binding may not execute a store, so
this identifies candidate producer shaders, not an observed hardware write.
Unknown/out-of-history producers remain unknown.

The PS5 CPU-decoded indirect draw guard additionally rejects nonzero draws above
1,048,576 instances, after the existing forced-refresh and recheck. This closes
the product-only gap for six-index draws with 27–31 million instances. It leaves
the original product limit and ordinary/zero-count behavior intact. This is
containment; corrupt counters could still cause missing geometry or another game
failure. It does not establish or repair the root producer/coherency defect.

Focused checks exercise the actual generated guard and retry flow, recorded
crash values, normal/boundary/zero cases, producer identity and Vulkan/CMake
anchors. The user performs the full Docker build and console test.

## Upstream counter-source probe

The 411-second 215111 test still loses the device through native GPU indirect
draws (192 x 1,000,593,163), bypassing the CPU fallback guard. That guard is not
a complete compatibility fix. The cached 824-byte compute producer contains
input texture fetches, a counter surface load, and five argument-buffer stores.
The original counter may therefore come from another producer.

When suspicious draws first identify a compute producer, `EDEN_COUNTER_WATCH`
arms bounded descriptor snapshots on subsequent configurations of that program.
`EDEN_COUNTER_BINDING` logs input/output image and texture buffer handles,
constant-buffer offsets, element counts, access flags, shader scalar/format,
runtime view/bound formats, sizes and GPU/CPU addresses.
`EDEN_COUNTER_UPSTREAM` names the most recent overlapping buffer-write intent
before the current program's output bindings are marked. This can identify the
next shader in the counter's producer chain. An overlap alone does not prove
which store executed. Unknown or evicted writers remain explicit.

The probe selects its shader from the observed bad argument history rather than
a game-specific hash. It captures the first four configurations and powers of
two thereafter. No shader semantics, GPU waits or readbacks are added by this
probe. Focused tests pass; the user runs the full build. For the next capture,
play until the character artifacts occur and then collect stderr; deliberately
waiting for another crash is unnecessary if the source-probe lines are present.

## Integer sampled texel-buffer candidate correction

The 221934 run confirms reactive flushing OFF, but still crashes on GPU-native
indirect draws with billion-instance arguments. The earlier live source probe
shows PixelFormat 58 (`R32_UINT`) on sampled counter/argument buffers while the
shader backend declares every sampled buffer as float.

This fork's patch `24-vulkan-integer-texel-buffers.diff` adds an explicit Vulkan
opt-in, integer format metadata on sampled-buffer descriptors, per-descriptor
SPIR-V scalar/image types, and integer fetch selection with bitcasts into the
existing IR carrier. Float buffers and non-opt-in hosts retain their old path.
OpenGL does not opt in. This is a correction to an observed type mismatch;
console testing is still needed to establish whether it fixes FF's bad counters.

The PS5 Vulkan internal cache version changes from 19 to `0x50530014`, because
old serialized environments did not cache the sampled-buffer pixel formats.
The next build will rebuild incompatible Vulkan shader/pipeline caches
automatically; saves, keys, firmware, OpenGL caches and the pinned Eden commit
are unaffected. The app version remains 1.000.001.

`tools/check-integer-texel-buffers.py` applies the complete patch stack to the
verified pinned archive and exercises production declaration/selection code
under ASan/UBSan: mixed float/uint buffers, correct image load types, integer
bit preservation, default-host behavior, existing array refusal and cache
migration. Indexed storage-image regression checks also pass. The user runs
the full Docker build. For the next controlled FF test, keep reactive flushing
off initially and confirm sampled `EDEN_COUNTER_BINDING` lines now report
`shader_scalar=uint` for the R32_UINT buffers if the watch is armed.

## Guest panic recovery and failed-call evidence

The integer-buffer console retest still has intermittent visual artifacts and a
later guest GameThread jump to `0x4`, preceded by RenderThread near-null reads.
No Vulkan device loss accompanies that capture. The invalid pointer's origin
remains unresolved; the draw guard and integer-buffer change are not a complete
FF compatibility fix.

Fatal non-notification guest Panic, Assert and CppException now publish a session
failure after the report/backtrace has been captured. With no debugger attached,
the frontend stops the game and returns to the launcher instead of leaving an
otherwise live session with audio and a frozen picture. Shutdown breaks and
notification breaks retain their behavior. Panics are excluded from early guest
jump retries. This recovers the failed session; it does not repair guest state.

Unmapped jumps also emit eight bounded `EDEN_GUEST_CALL_SITE` instruction words
around LR to stderr, validating each word before reading and before notifying
the frontend. `tools/check-guest-panic.py` tests the actual generated panic hook,
nonfatal/shutdown/debugger exclusions, first-fault retention, concurrent recording,
retry policy and bounded instruction reads under ASan/UBSan. Both changed engine
fault handlers compile using the actual PS5 target flags. The full application
build and console test remain the developer's next step.

## Guard the native indirect path for FF Resonance

The 2026-11-19 23:16:27 device-loss capture contains a native GPU indirect draw
with 192 indices and 2,147,484,943 instances. That path never entered the existing
CPU argument guard. For PS5 title `0100B8A026F14000`, the arrays, indexed and
counted multi-indexed indirect macros now enter their existing CPU fallback
before setting native indirect state. The fallback refreshes GPU-written macro
parameters, retries suspicious values through the existing forced refresh, and
issues direct draws only for validated values. Persistent implausible values
are dropped; zero-work draws retain their no-op behavior. Byte-count transform
feedback is unchanged; it is not the instanced indirect path in this capture.

`headless/indirect_draw_policy.h` scopes this compatibility workaround to that
PS5 title. Other titles and non-PS5 hosts keep their original native path. A
bounded, once-per-macro `EDEN_INDIRECT_VALIDATION ... mode=refreshed-cpu-fallback`
line confirms routing on the console. Existing `EDEN_DRAW_ARGS` and producer
probes capture the queued, refreshed and retried arguments on this path.

This closes the observed validation bypass; it does not establish who corrupted
the counters, fix the separate guest CPU fault, or restore geometry discarded
for invalid counts. Extra GPU readbacks may lower FF performance. Console
retesting is required to assess stability and visual artifacts.

`tools/check-native-indirect-guard.py` runs the actual generated routing and
fallback guard code with ASan/UBSan, including the recorded 2,147,484,943-instance
case, repair on refresh, normal and zero-work values, mixed multi-draw lists,
and other-title/non-PS5 exclusions. Existing draw provenance regressions pass.
The generated macro translation unit is checked with the actual PS5 compiler;
the developer runs the full application build.

## Console checkpoint (2026-11-19)

The developer reports FF Resonance remains playable with the validated indirect
fallback, but flicker and black lines persist. This is a working checkpoint,
not a complete compatibility fix. Keep it on the development branch pending
further testing; the guest object fault and the origin of corrupt draw counts
remain unresolved. Private console logs and offline game analysis are retained
locally under ignored `debug/` and are not part of this change.

## GPU read ownership and asynchronous readback lifetime review (2026-11-20)

The captured previous session has `EDEN_FF_RENDER_REQUEST_GUARD applied=1`,
validated CPU indirect routing, reactive flushing OFF, and indirect compute-read
ownership diagnostics from patch 25. It later records a guest panic with context
and frames in stderr; no device-loss marker appears. The current session is the
launcher/library scan. This capture does not establish the precise origin of
the frozen picture, and zero-count draws with large unused instance words are
no-op draws, not evidence of a newly submitted billion-instance draw.

Patch `25-buffer-read-ownership.diff` preserves GPU ownership for indirect compute
arguments and marks reads of reused vertex bindings, indirect commands/counts and
compute arguments as used, so overlapping uploads cannot move ahead of them.
The existing title/build-guarded guest workaround and earlier engine fixes remain.

Patch `26-buffer-readback-lifetimes.diff` completes the readback bookkeeping:

- Canceling a download removes or splits its queued copy records too. Otherwise
  queuing another download of the same address makes the old canceled staging copy
  eligible again, allowing it to overwrite guest memory and retire newer work.
- Completing an old download retains dirty tracking for newer writes in BOTH the
  uncommitted set and the committed-but-not-yet-staged queue. A fence can move a
  new write into the committed queue before its own download has been staged.

`tools/check-buffer-readback-lifetimes.py` executes the real cancellation and
completion functions with the real engine RangeSet/OverlapRangeSet containers
under ASan/UBSan. It covers full and partial cancellation, address reuse,
nonuniform staging offsets, multiple batches, overlapping pending downloads,
committed/uncommitted rewrites and empty completions. Old-code negative controls
reproduce both failures. Ownership, indirect/provenance, integer-buffer,
guest-panic and FF render-request checks pass. Vulkan and OpenGL rasterizer
translation units compile with the actual PS5 flags and newly generated cache
headers. The new checks are wired into normal build validation; full release
build and PS5 retest are left to the developer.

Upstream mirror master was checked at `8a482830170bfe5ae041817cc12c233a9f0c9d2e`.
Its two commits after our pin concern gamescope dialog layout and Android disk
shader-cache startup; neither affects the PS5 renderer. The pinned Eden revision
remains `d85bad89248fcae68f812d7e1c937436261404cb` (no downgrade). These source-proven
fixes are candidates for the remaining freeze/artifacts, not a verified complete
FF compatibility fix. No new app version, deployment or shader-cache reset is
required by patch 26 itself.

## Per-allocation synchronous readback bounds (2026-11-20)

Review after the patch-26 console build identified another independent engine
bug. `DownloadMemory` visits each cached buffer intersecting a CPU read, but
passed the entire CPU read range to each `DownloadBufferMemory` call. That
function cleared the shared page tracker and iterated all GPU-dirty ranges
before checking whether they belonged to the selected buffer. A read spanning
two allocations could therefore build out-of-bounds source offsets against the
first allocation and consume the second allocation's dirty tracking too soon.

`27-buffer-download-bounds.diff` clips a synchronous download to its buffer's
actual allocation before tracker iteration, metadata cancellation or source-offset
calculation. Disjoint/empty queries return immediately; the clipping avoids an
overflow-prone requested-end calculation. The existing page-granular download
behavior inside the allocation is preserved. Full-buffer eviction and ordinary
single-buffer reads retain their existing paths.

`tools/check-buffer-download-bounds.py` executes the production download functions
and page-table iterator with real engine interval containers and controlled
page/staging/guest memory. Cases cover separate allocations with an unmapped gap,
offset underflow, preserved dirty metadata outside the selected allocation,
page-rounded partial reads, empty/disjoint requests and a huge requested size.
The old-code negative control reproduces the invalid GPU copy. Tests use
ASan/UBSan and run in normal build validation. Adjacent lifetime/ownership
regressions and actual Vulkan/OpenGL PS5 compilation are checked as well.

This source-proven bounds defect can produce invalid GPU copies or missing
readbacks. It is not established as the cause of FF's particular freeze. The
running patch-26 console test is unchanged; patch 27 is a separate candidate for
a subsequent build. No engine pin/version update, console setting change,
deployment or full application build was performed during this review.

## Related external FF reports reviewed (2026-11-20)

- https://github.com/eden-emulator/Issue-Reports/issues/751 reports an out-of-range
  texture-handle assertion followed by `SurfaceFormat` rejecting `Invalid` on
  Windows Vulkan. Our pinned `GenericEnvironment::ReadTextureInfo` still asserts
  the TIC limit and then reads the descriptor unconditionally. Runtime texture
  lookup (`VisitImageView`) already rejects out-of-range indices. This mismatch
  is a separate hardening candidate; the preserved PS5 freeze capture does not
  contain that assertion/format-error sequence, so it is not established as this
  freeze's cause. No arbitrary format substitution was introduced in this review.
- https://github.com/eden-emulator/Issue-Reports/issues/753 reports an Android
  device/build-specific improvement from disabling asynchronous GPU emulation,
  with outdoor flicker persisting. That option differs from async shader
  compilation. This port currently sets `use_asynchronous_gpu_emulation=true`
  in `headless/main.cpp`; switching off async shaders does not test the Android
  workaround. The original report's final baseline has reactive flushing OFF;
  turning it on did not resolve flicker in that report. Adreno/Turnip driver
  choices do not apply to the PS5 AGC/RADV backend.

These reports guide the next descriptor/synchronization investigation; they do
not establish a shared cause for bad counters, invalid guest objects, visual
artifacts and presentation freezes. The running console test/settings were left
unchanged. The separately reproduced cross-allocation readback fix (patch 27)
is ready for a later build after the current patch-26 test is assessed.

## SMMU reclaim progress and lock ordering (2026-11-20)

A subsequent no-crash-report exit captured a fatal guest panic in stderr after
the engine log filled with 850,955 `Ran out of SMMU address space!` messages.
This is guest GPU address-space mapping exhaustion, not evidence of physical RAM
exhaustion. The engine log reached its limit before the final panic, so the exact
fatal service call is not established by that file alone.

`28-nvmap-smmu-reclaim.diff` corrects the allocator retry loop in `NvMap::PinHandle`.
It previously checked the requesting handle's `d_address` before unmapping a
queued candidate. New handles normally have zero there, so reclaim never ran.
The loop also read `front()` without an empty check and had no exhaustion exit.
It now reclaims the candidate mapping, removes stale unmapped entries, and returns
failure when the queue is empty. Candidate selection releases the queue mutex
before waiting for the handle mutex, then reacquires the queue mutex and checks
that the candidate is still unpinned and queued. This preserves the handle->queue
lock ordering used by unpin/free and avoids unmapping a concurrently repinned
handle. Existing mapping reuse, low-area pins and preallocated heap paths remain.

`tools/check-nvmap-smmu-reclaim.py` executes the actual pin/unmap functions under
ASan/UBSan, including deterministic concurrent-repin validation and an old-code
livelock control. Reclaim/retry, finite exhaustion, stale entries and fast paths
pass; `nvmap.cpp` compiles with the real PS5 flags. The test is wired into normal
build validation. This addresses a defect directly relevant to the new log;
console retesting is required, and flicker/black lines remain unresolved.

## Failed-map propagation and unbound DMA channels (2026-11-20)

The 15:32:22 console crash occurred after 45m27s of app uptime: a host GPU-thread
SIGSEGV at address `0x3a0`, symbolized as `DmaPusher::CallMethod`. Three 64 MiB
SMMU allocations had returned failure shortly before it. The bounded patch-28
failure path ran, but its callers accepted zero as a device address, followed by
unmapped low-address device reads/writes. This is a different failure from GPU
device loss, and physical-memory exhaustion is not established by this report.

`29-nvmap-mapping-failure.diff` rejects zero pinned bases in GPU MapBufferEx,
sparse Remap and video MapBuffer before installing mappings or adding offsets.
Ordinary GPU mapping setup releases its pin if later validation/allocation fails
or throws. A partially failed video batch unpins its earlier entries and clears
their returned addresses. These operations return InsufficientMemory rather than
claiming success with an invalid address.

`30-dma-unbound-channel.diff` validates the engine pointer before either single
or multi DMA dispatch accesses it. Invalid commands log their subchannel, method
and command-list address, then throw a runtime_error. The existing GPU worker
exception boundary reports a session failure; valid command handling remains.

Production-code ASan/UBSan tests cover failed bases with nonzero offsets,
normal/error/exception pin ownership, remap checks, partial video batch rollback,
all eight unbound DMA channels, and valid sink/direct/puller dispatch. The SMMU
reclaim regression continues to pass, and all three changed units compile with
real PS5 flags. Checks are wired into normal build validation. The full build and
console test remain the developer's step.

The underlying eventual exhaustion of active mappings remains under investigation.
These corrections prevent unsafe use of failure results and host null crashes;
a genuine allocation failure can still stop the guest game. They do not establish
a fix for FF's remaining flicker or black lines.

## Fixed-map pin replacement lifetime (2026-11-20)

The next capture records a 128 MiB mapping failure at 611.045 s followed by a
guest panic and return to the launcher, without the prior host null crash.
The failed-map protections work, but mapping space still becomes exhausted.

`31-fixed-mapping-pin-replacement.diff` addresses another source-proven lifetime
bug in MapBufferEx: successful fixed mappings overwrite the record at a GPU
address using insert_or_assign, but the old record's handle pin was never
released. They also appended duplicate offsets to the allocation's mapping list.
Replacement now releases the old pin after successful GMMU mapping and retains
one allocation-list entry. Same-handle replacements retain one reference; another
independent GPU mapping still owns its own reference. Existing post-pin failure
rollback remains in place and does not release an unchanged old mapping.

`tools/check-fixed-mapping-pins.py` runs the actual ownership block with
ASan/UBSan: 1000 replacements, same/different handles, independent mappings,
unique FreeSpace iteration and an old-code leak control. Failed-map and reclaim
regressions continue to pass; the mapping unit is compiled with PS5 flags.
This fixes a plausible source of progressive pinned-address exhaustion, but
that exact sequence is not established in the console log. Sparse remap ownership
and other mapping lifetimes may still need investigation. No full application
build, deployment, pin/version change, commit or push was performed here.

### Follow-up: mapping teardown indexes (patch 32)

A live FF session snapshot on 2026-11-20 continued through at least 778 seconds
with save activity and no recorded SMMU exhaustion, device loss or guest panic.
It still reported invalid shader instructions around 290 seconds, an unsupported
constant-buffer binding 31, and intermittent unmapped device reads at 0x7da01000.
Those are unresolved rendering evidence; this patch does not claim to fix their
origin or the remaining flicker/black lines.

Code review found that explicit UnmapBuffer removed the mapping record but left
its address in the parent allocation's mappings vector. FreeSpace could then
return early on that stale address, leaving other mappings and their pins alive.
A remap at the same address also appended another vector entry. Conversely,
FreeSpace removed mapping records without clearing map_buffer_offsets, so a
later UnmapBuffer could dereference a missing record.

Patch 32 uses the shared FreeMappingLocked teardown for explicit unmaps, removes
fixed addresses from their allocation vector, and clears the offset index with
the record. FreeSpace already iterates a copy of the allocation, so pruning the
original vector does not invalidate its loop. The sanitizer regression executes
production cleanup functions through 1,000 unmap/remap cycles, allocation release,
redundant unmaps and dynamic mappings; a control retaining the old stale list is
rejected. The affected PS5 compilation unit and earlier pin/failure checks pass.
This is a proven bookkeeping defect, not proof that FF exercised that sequence.
Sparse Remap pin accounting remains a separate unresolved review item.

### Follow-up: GPU backing range validation (patch 33)

MapBufferEx's subregion-remap path compared only mapping_size against the
original mapping size, ignoring buffer_offset. A positive offset plus a valid
length could therefore extend outside the backing mapping; negative offsets
were also accepted. Ordinary mappings did not validate buffer_offset and size
against the nvmap handle's original size before pinning. Patch 33 rejects these
invalid requests with BadValue using subtraction-based checks that cannot wrap.
It preserves the existing zero-size convention (the full original handle size).

The sparse Remap ioctl also omitted the address-space mutex despite accessing
the same allocation and GMMU state as AllocateSpace/FreeSpace/MapBufferEx.
It now takes that mutex before checking or modifying address-space state.

The bounds regression executes the production guards with exact-end ranges,
negative offsets, oversized subregions and overflowing lengths under ASan/UBSan.
Earlier mapping-failure and teardown tests also pass, with the former fixture
corrected to use the ioctl's actual signed buffer_offset and a valid partial
mapping size. The changed PS5 compilation unit builds. These source defects
could permit invalid GPU reads but are not yet proven to be the source of FF's
invalid shader words. No shader instruction is replaced with a guessed value,
and no warning is suppressed by this patch.

### Follow-up: compiler environment bounds and error reporting (patches 34–35)

Shader environment graphics and compute constant-buffer reads indexed their
host arrays before checking the requested bank; the compute path also shifted
its enable mask by the unchecked bank. Patch 34 validates the index before either
operation and raises Shader::LogicError on invalid banks. Reads preserve the
existing zero result outside a buffer but now require a whole four-byte word
inside its advertised size. Texture information reads explicitly reject indexes
above tic_limit rather than continuing past an assertion into unrelated data.
These changes prevent unsafe compiler-side reads, not the origin of bad indexes.

The Vulkan graphics pipeline exception handler previously constructed a second
CFG for every stage before dumping captured shader bytes and logging the first
exception. DumpImpl does not use its read-range parameters, so that reconstruction
was unnecessary. It could produce further invalid-instruction reports and throw
again while handling the original error. Patch 35 logs the first error first,
dumps existing bytes without re-decoding, and catches individual dump exceptions
so later dumps and the normal null-pipeline return still execute. The PS5 adapter's
CFG instrumentation anchor count is updated accordingly. This can explain some
secondary diagnostic noise; it does not prove that the underlying shader was valid.

Production-function ASan/UBSan checks cover both constant-buffer environments,
valid final entries, invalid banks including huge indexes, partial words, TIC
limits, and no GPU reads on rejection. The production exception-handler test
injects a failed first dump and verifies the original error is retained, remaining
dumps are attempted, and no second exception escapes. Tests are part of ordinary
source checks. No console build, deployment, engine pin or version change is made.

Sparse Remap still acquires pins without recording per-subrange ownership. A
correct repair must preserve overlapping/partial remaps and release pins only
when the last live subrange is removed. Simply unpinning after each Map would
allow the SMMU to reclaim live GPU backing, so that shortcut is intentionally not
applied. This remains a separate lifecycle defect under review.

### Follow-up: sparse remap backing and allocation lookups (patch 36)

Sparse Remap checked its destination but not whether handle_offset_big_pages
plus the requested size fit the nvmap handle. Patch 36 checks source bounds before
PinHandle, rejects invalid requests with BadValue and preserves valid exact-end
mappings. Destination checks for sparse and ordinary fixed mappings now use
subtraction rather than overflowing offset-plus-size arithmetic. Both lookups
check upper_bound against begin before decrementing: the previous post-decrement
condition could decrement begin/end in an empty allocation map even on rejection.

HeapMapper::IsInBounds similarly used start + size and heap_base + heap_size;
a wrapping requested end could incorrectly qualify for the preallocated mapping
path. It now checks the offset and remaining capacity without forming either end.

A production-snippet regression covers sparse backing bounds, empty/below-first
allocation lookups, exact-end mappings, huge overflowing requests and heap ranges
with debug iterators plus ASan/UBSan. This protects bad-input paths; the current
FF logs do not prove that any of these exact requests were made. Sparse pin
subrange ownership remains unresolved rather than being prematurely unpinned.

### Console result: FF Vulkan allocation failure after about 23 minutes

A later snapshot of the same pre-patches32–36 test session ended with CreateBuffer
VK_ERROR_OUT_OF_DEVICE_MEMORY: 310444032 bytes (~296 MiB), usage 0xbff. Outside-budget
retry and a retry after giving back 144 MiB both failed. The pool's reported largest
free block at refusal was 260 MiB; VMA held 4184 MiB, 2778 MiB allocated. A preceding
sample still had 2524 MiB total free across 99 runs. This supports fragmentation or
a temporary allocation peak, not a conclusion that all physical memory was used.
The session caught the error, shut down and reopened the launcher; no new host
crash file was listed and no SMMU exhaustion was observed.

Buffer cache merges allocate the combined buffer before retiring the originals,
and may add streaming expansion. The current log does not identify the failed
buffer's creator or whether it was such a merge. Further diagnostics must measure
requested/merged spans and retained overlap sizes before treating that hypothesis
as established. Patches32–36 have not been tested on this console session and are
not claimed to fix this allocation failure.

### OOM recovery: synchronized retirement queue release (patch 37)

The ~296 MiB buffer refusal exposed a recovery gap: replaced buffers remain in
the cache's destruction ring for six/eight frame ticks, while the allocator's
existing OOM relief releases idle staging buffers and CPU heap memory only.
A cache merge needs its live source buffers and the destination simultaneously;
retired buffers from earlier merges can unnecessarily increase that peak.

On PS5 Vulkan device-memory allocation failure, buffer creation now waits for
scheduler.Finish (submission and GPU completion), clears only that retired-buffer
ring, and retries creation once if objects were released. Live overlapping
buffers are not evicted or overwritten, GPU-written contents are preserved, and
the ordinary copy/join path still runs after successful allocation. No retired
objects means no additional allocation attempt. Device loss, other exceptions,
or a failed GPU wait do not trigger release; a second allocation failure follows
the existing controlled session shutdown. The recovery log reports requested and
merged spans, live overlap count and the number of retired objects released.

The runtime classifies an exception_ptr through typed exception handling, so this
works with the PS5's -fno-rtti configuration. The existing PS5 SlotVector recovery
returns a failed constructor's slot before retrying. The new sanitizer regression
executes the production retry and classifier with that real generated container
and the real destruction ring: successful recovery, first-attempt success, second
failure, empty ring, device loss and failed wait are covered. It asserts that
retired destructors run after synchronization and live payloads stay unchanged.

This fixes missing emergency reclamation, not a promise that every fragmented
pool can satisfy a large contiguous allocation. The console session must confirm
whether retired buffers were contributing to this particular FF failure. No
resolution reduction, discarded live data, unlimited retry or engine downgrade
is used. Full application build and console testing remain with the user.

### Startup compatibility correction: aligned nvmap backing

The first console build of patches32–37 reached initialization but the guest
panicked twice within startup (result 0x2a2); no OOM recovery ran. Review found
that patches33/36 compared explicit GPU mapping ranges to Handle::orig_size.
That is the payload length, while Alloc and PinHandle align and map aligned_size.
A valid page-sized mapping of the final padded page can exceed orig_size.
The guards now compare against aligned_size; the original default mapping-size
semantics remain unchanged. Tests cover non-page-sized payloads with valid padded
mappings and reject one byte beyond the aligned backing. Original-size negative
controls reproduce the compatibility rejection. The affected PS5 unit compiles.

The deployed build did not log the rejected range, so this source defect is
confirmed but its exact link to the two guest panics still needs a console test.
Patch38 logs handle, offset, size, original and aligned lengths on range rejection.
The OOM retirement recovery is retained. Earlier references to original-size
bounds describe the initial implementation and are superseded by this correction.

### Buffer usage tracker masks (patch 39)

UsageTracker is the real Vulkan buffer's read/usage tracker; CanReorderUpload
uses it to decide whether a transfer can be placed on the earlier upload command
buffer. Its original mask used min(size,4096) / 64, rounded down and independent
of the offset within a unit. A range shorter than 64 bytes gave zero bits and
shifted a 64-bit value by 64, undefined behavior. Unaligned tails were not fully
covered; zero-sized page tails also reached that shift. Same-page queries then
unnecessarily tested a prefix from the page's start rather than just their units.

Patch39 computes the first/last touched units after clipping to the current page,
uses shifts only in [0,63], makes empty ranges no-ops, avoids that extra same-page
prefix check, and conservatively refuses reordered uploads for invalid query
ranges. The existing 12-byte indirect compute usage marker now has a well-defined
mask. Valid accesses remain tracked at the existing 64-byte granularity.

The test uses the actual production tracker and CanReorderUpload, checks short
indirect arguments and unit/page boundaries, and compares 64,000 randomized
queries with independent byte-to-unit coverage. Reversing the exact patch restores
the original header and UBSan reproduces its shift-by-64 on the short argument
case. This establishes a tracker defect, not proof that it caused a particular
FF crash. In particular, the original undefined behavior could also over-mark
usage and cause needless serialization; its observed effects depend on compiler
and input. Console confirmation remains required.

### Verified middleware and invalid shader fallback (patch 40)

The locally supplied FF executable, with the same build ID as the console log,
identifies its middleware as Unreal Engine 5.6.1. This confirms newer middleware,
but compatibility is determined by the Switch CPU/GPU operations the executable
uses; the version marker alone does not identify a missing emulator feature.
Only the extracted executable segment hashes were checked, not all assets or
full-game behavior. The game container and keys remain private and unchanged.

Maxwell::Decode previously logged/asserted on an invalid instruction and returned
Opcode::NOP anyway. The prior FF logs exercised that path with invalid words,
including all-one data. Patch40 raises Shader::LogicError instead, using the
existing Vulkan/OpenGL shader compilation exception boundaries. It prevents an
invalid instruction stream from silently becoming a runnable shader. It does
not implement an unknown valid instruction or replace invalid game state with a
fabricated result. A refused shader may still leave missing rendering until its
input data or actual missing operation is fixed.

A sanitizer test compiles the real decoder, visits the real instruction table's
canonical encodings, rejects the invalid words observed in FF, and verifies that
the prior NOP fallback accepted those words. The changed PS5 decoder compiles.
The Vulkan error-handler test also passes. Full compatibility is not claimed:
startup after the aligned-backing correction, long play beyond the prior OOM,
restarts and later scenes still require console testing. Sparse remap pin
ownership and the origin of invalid shader/indirect data remain open issues.

### SMMU exhaustion: sparse remap pin ownership (patch 41)

The subsequent FF session ended at 1003.755 s with a 64 MiB SMMU allocation
failure and no unpinned handles to reclaim, followed by guest panic. This differs
from the earlier Vulkan buffer OOM. Source review confirms a separate lifetime
leak: the sparse Remap ioctl called PinHandle for every nonzero entry, but stored
no ownership record and never released those pins on replacement or MapSparse.
FreeSpace likewise could not release them. Repeated remaps therefore kept the
backing mappings permanently pinned and unavailable to the SMMU reclaim queue.

Patch41 associates each successful sparse pin with shared ownership of its live
GPU-address intervals. Partial replacements preserve left/right fragments using
the same pin; the pin is released once the last fragment is gone. Independent
mappings of the same handle retain independent pins. Sparse clearing, allocation
release, fixed mappings overwriting sparse regions and address-space destruction
all retire affected owners. The GPU mapping is updated before old pins are
released. Up to three replacement nodes are allocated before changing mappings;
if preparation or the GPU update throws, the old owners remain and the new pin
is released. Zero-length sparse remaps acquire no pin. The aligned backing
bounds and earlier failure checks remain in force.

FreeMappingLocked no longer claims noexcept: ownership preparation and existing
GPU mapping operations may throw, and those errors must reach the normal session
boundary instead of terminating the host. GPU page tables are destroyed before
remaining sparse owners, and NvMap outlives the owning address-space devices.

The production Remap/FreeSpace regression runs 1000 replacements under a two-live-
handle budget, checks split survivors, independent mappings, failed pins and GPU
updates, zero-length remaps, FreeSpace and destruction. Another 1500 randomized
interval changes are compared against an independent per-page lifetime model.
Reversing the exact patch restores the original Remap and reproduces its leaked
pin on sparse clearing. ASan/UBSan and checked iterators pass, as do earlier fixed
pin, mapping cleanup/failure, aligned backing and SMMU reclamation tests. The
changed GPU address-space and owning NVDRV module PS5 units compile.

This is a confirmed pin leak that can cause the observed class of exhaustion.
The deployed log does not name the pin owners, so it is not proof that this was
the only contributor in that FF run. No live pinned backing is forcibly reclaimed
and no address-space limit is increased. Long-running PS5 testing remains needed.

### Long-session slowdown: GC lookahead budget mismatch

A later idle/live-session snapshot reached about212 minutes of presentation
windows, with the last60 five-second windows at a median30 FPS. Free direct
memory was5287 MiB, largest free5134 MiB, graphics held1918 MiB/used1696 MiB,
and no allocation failure was recorded. This does not demonstrate an active-play
leak or rule out scene-dependent stuttering; the previous active run had increasing
stalls. The HUD counts retained capacity as used memory, so it cannot alone prove
that memory is unreleasable.

Code review found a mismatch between the port's GC scan-liveness fix and its
batched readback lookahead. Actual cleanup budgets evictions and skips retained
images without consuming that budget. PrefetchDownloads still consumed its
allowance on each visit. Enough decoding/costly retained entries at the front of
the LRU therefore prevented dirty images farther along from entering a batch;
actual cleanup reached them but fell back to individual GPU waits.

Lookahead now follows the same eviction/optional-upstream-visit counting policy,
with an independent8192-visit bound. Clean and oversized unbatched evictions
also reduce its simulated usage, so it stops copying at the pressure threshold
rather than scheduling readbacks for images cleanup would retain. A refill from
inside cleanup includes the current image whose allowance was already consumed.
Staging stays bounded to64 MiB/64 images and the actual eviction policy is unchanged.

A production-include test uses the actual LRU implementation and reproduces the
old retained-prefix starvation. The corrected pass batches20 eligible images
behind60 retained entries with one simulated GPU wait; it also covers scan bounds,
clean-image accounting, pressure transitions, refill allowance, byte limits and
the upstream counting switch under ASan/UBSan. No claim is made that a simulated
wait count establishes a console speedup. The affected generated PS5 Vulkan
rasterizer/texture-GC compilation check passes; a full build and active-play
comparison remain with the user. No live game, settings or console file changed.

### Low-address video alias failure handling (patch 42)

NvMap's low-area pin helper did not check the 32-bit Host1x allocator's result.
A zero result still reached gmmu_manager.Map at GPU address0 and incremented the
handle's pin count. The caller received0 and treated the map as failed, leaving
the newly consumed pin and potentially a zero-address GPU mapping behind. Large
aligned lengths were also truncated to32 bits before allocation.

Patch42 refuses an unavailable or unrepresentable low alias before mapping or
consuming a pin. A reused queued handle remains queued on failure, and already
live high-area users retain their pins. If the request created new high backing
first, that backing is unmapped and returned on low-alias failure. If mapping
the alias throws, its reserved low-address range is unmapped/freed as well.
Successful queued, live, heap and ordinary high-area paths retain their behavior.
A real address-space shortage can still reach the guest as allocation failure;
this patch does not fabricate an address or reclaim still-live backing.

The existing actual PinHandle/UnmapHandle sanitizer test now covers fresh, queued
and live low-alias failures, retry after failure, mapping exceptions and oversized
lengths. Reversing the exact patch reproduces the original zero-map/consumed-pin
behavior; the earlier SMMU reclaim-loop negative control is retained. Tests pass
with ASan/UBSan and the affected PS5 units compile. The observed video-stream
activity in FF makes this path relevant, but no current FF log proves that this
particular low-alias allocator failure occurred. It is a confirmed source defect,
not a newly diagnosed console crash.

### Shader cache six-input support and bounded reads (patch 43)

The engine supports six Maxwell graphics program inputs (including both vertex
inputs), but the Vulkan and OpenGL disk-cache workers collected environments in
a static_vector with capacity5. Runtime serialization already allows all six.
A valid six-input pipeline could therefore be saved successfully but fail when
loaded. Both worker containers now use Maxwell::MaxShaderProgram, matching the
producer and the graphics keys; no cache layout/version or valid shader changes.

LoadPipelines now rejects zero or out-of-range environment counts before vector
allocation/front(), and compute records must contain one environment. Renderer
callbacks verify that the environment count matches the key's active hashes
before scheduling work. Invalid counts use the existing cache-error path; valid
records continue loading normally. Cached instruction reads additionally check
the captured code vector, not only its advertised address range. Diagnostic
dumps reject offsets outside captured bytes before subtracting their length.
These are targeted count/read guards, not a claim of complete cache-format
validation or a diagnosis of the observed FF crashes.

The sanitizer regression uses the production loader, key/read/dump guards and
real Boost static_vector, with a valid six-input graphics record, compute,
zero/oversized counts, mismatched keys and short captured data. Restoring the
old five-entry capacity reproduces the failure. The existing shader error-handler
and environment-bound tests pass. PS5 shader_environment, Vulkan pipeline cache
and OpenGL shader cache compilation checks pass. No running game, saved data,
console cache, engine pin or app version was modified during this work. Full app
build and PS5 gameplay confirmation remain with the user.
