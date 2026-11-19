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
| Shutdown | Request timing-thread stop before waking its waits, preventing a consumed wake from hanging join. |
| Update selection | Keep code/control/version entries from the newest update regardless of directory scan order; retain the other versions in the version list. |
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
ZIP SHA-256: `7f1f3b1d9d1d98e2311dac46a767176162499646579b62b4a1e3a16179112164`.

Supported focused regressions passed for the new engine behavior and retained
settings/history, NSO loading, audio/cheat shutdown, failed-load/content teardown,
repeated COW recovery, JIT aliases, and Home behavior. The whole host source suite
was not run as the final package gate; native-x86 race checks and PS5 tests remain
separate. The memory model limitation above remains.

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
