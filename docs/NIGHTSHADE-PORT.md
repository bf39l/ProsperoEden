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
