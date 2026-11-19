# Build ProsperoEden with Docker

Build ProsperoEden for PlayStation 5 on an Apple Silicon Mac using an Ubuntu AMD64 Docker container.

This guide covers the **1.000.001** release line, pinned to Eden `d85bad89`.
For local integration testing, stay on the branch containing the changes you want to build.

The fork preserves the upstream prerelease UI and emulator implementation while adding per-game directory scanning, including support for games with updates and DLC stored in individual folders.

## Rebuild in the existing container

For the local FF provenance diagnostics branch, the repository is already on
`debug/ff-indirect-draw-provenance`. The running container mounts it at `/workspace`,
including local uncommitted changes. From your Mac terminal:

```bash
cd /Users/bo/ps5/ProsperoEden-dev
docker exec -it -w /workspace prosperoeden-build bash -lc \
  'EDEN_SKIP_SOURCE_CHECKS=1 make release JOBS=4'
```

This keeps the established Apple Silicon/Rosetta source-check exclusions; native
CI still runs the full checks. The new provenance checks can be run separately:

```bash
docker exec -it -w /workspace prosperoeden-build bash -lc \
  'python3 -B tools/check-indirect-draw-log.py "$(cat .local/headless-cache)/source"'
```

Outputs are `build/release/PPSA99018` and
`dist/ProsperoEden-v1.000.001.zip`. The previously built ZIP does not contain
new local changes until this build completes.

### Run in the background and follow build.log

To keep the build running after the terminal command returns, start it with
`docker exec -d`. Both standard output and errors go to `/workspace/build.log`.
Because `/workspace` is the mounted repository, the same file is available on
macOS at `/Users/bo/ps5/ProsperoEden-dev/build.log`.

From your Mac terminal:

```bash
cd /Users/bo/ps5/ProsperoEden-dev
docker exec -d -w /workspace prosperoeden-build bash -lc \
  'EDEN_SKIP_SOURCE_CHECKS=1 make release JOBS=4 > /workspace/build.log 2>&1' \
  && echo "started"
```

Follow the latest output live:

```bash
cd /Users/bo/ps5/ProsperoEden-dev
tail -n 80 -f build.log
```

Press **Ctrl+C** to stop following the log; the detached build keeps running.
Each new build using `>` replaces the previous `build.log`. Let the current build
finish before starting another one in the same workspace.

For a quick progress check after about 50 seconds, matching the development workflow:

```bash
sleep 50
cd /Users/bo/ps5/ProsperoEden-dev
E=$(grep -cE 'error:|FAILED:|Assertion|Traceback|Subprocess aborted|does not apply' build.log || true)
echo "errors=$E"
grep -nE '== Built|\.zip|eboot.bin' build.log | tail -5
```

To see the matching error lines rather than just their count:

```bash
grep -nE 'error:|FAILED:|Assertion|Traceback|Subprocess aborted|does not apply' build.log | tail -30
```

`started` means Docker accepted the detached command; `errors=0` only means those
patterns have not appeared yet. Neither confirms the build has finished. Check
for the final distribution ZIP path and SHA-256 line after `== Built` (the app
folder is packaged before the ZIP is created). After a successful build, verify
the ZIP checksum from your Mac:

```bash
cd /Users/bo/ps5/ProsperoEden-dev/dist
shasum -a 256 -c SHA256SUMS
```

## Requirements

- macOS with Apple Silicon
- Docker Desktop with AMD64 emulation enabled (Rosetta where available)
- Git
- Sufficient disk space for SDK dependencies, FFmpeg, emulator source, and build artifacts
- Repository checked out to the release or integration branch you want to build

Repository: https://github.com/bf39l/ProsperoEden

## 1. Clone the repository

On your Mac:

```bash
git clone https://github.com/bf39l/ProsperoEden.git

cd ProsperoEden

git switch main
```

Verify the branch:

```bash
git branch --show-current
```

Expected:

```text
main
```

For a completely fresh build, use a fresh clone rather than a working directory containing build artifacts from other branches.

## 2. Create the Docker container

From the repository root on your Mac:

```bash
docker run -it \
  --name prosperoeden-build \
  --platform linux/amd64 \
  -v "$PWD:/workspace" \
  -v prosperoeden-cache:/root/.cache \
  -w /workspace \
  ubuntu:26.04 \
  bash
```

This creates an Ubuntu AMD64 container.

- `/workspace` — repository mounted from macOS
- `/root/.cache` — persistent Docker build cache
- `prosperoeden-cache` — named volume automatically created if it doesn't exist

**Note:** Docker reuses an existing named volume. Use a new volume name if you need a completely fresh dependency cache.

## 3. Install build dependencies

Inside the Docker container:

```bash
apt-get update

apt-get install -y --no-install-recommends \
  $(grep -v '^#' tools/ci/ubuntu-packages.txt)
```

Install additional tools used during our Apple Silicon AMD64-emulation builds:

```bash
apt-get install -y --no-install-recommends \
  libarchive-tools \
  nasm \
  yasm \
  ccache
```

These packages address dependency extraction, FFmpeg assembly, and compiler-cache requirements encountered during the build.

The compiler is **LLVM 21** (`clang-21`), which `tools/ci/ubuntu-packages.txt` installs. Eden now needs Clang 19 or later (its `jacinth`/`hydrocarbon` C++20 modules), so an older clang is not enough.

## 4. Apply the tar compatibility workaround

GNU tar may fail under Docker AMD64 emulation on Apple Silicon with errors such as:

```text
tar: Cannot mkdir: Function not implemented
```

Use `bsdtar` instead:

```bash
cat > /usr/local/bin/tar <<'EOF'
#!/bin/sh
exec /usr/bin/bsdtar "$@"
EOF

chmod +x /usr/local/bin/tar
hash -r
```

Verify that the wrapper is installed:

```bash
command -v tar
tar --version
```

The wrapper is installed only inside the Docker container and does not affect macOS.

## 5. Prepare the toolchain and dependencies

From `/workspace`:

```bash
cd /workspace

make toolchain
make deps
```

`make toolchain` prepares or verifies the host toolchain.

`make deps` fetches the dependencies required by ProsperoEden, including the Mihawk Vulkan and SDK source repositories. Downloads and git snapshots are cached in the git-ignored `vendor/` folder (`vendor/git/*.bundle`, tracked source only), so a later `make deps` works offline and survives an upstream repository disappearing. `make clean` and `make distclean` leave `vendor/` alone (the latter backs it up to `.vendor-backup/` first); only `make clean-vendor` removes it.

The dependency process may prepare:

```text
/mihawk-vulkan-review
/mihawk-mesa-review
/mihawk-sdk-review
```

Verify that the repositories needed by the next step exist:

```bash
ls -ld \
  /mihawk-vulkan-review \
  /mihawk-sdk-review
```

If they do not exist, check the dependency-fetch output before proceeding.

## 6. Prepare the Mihawk Vulkan PS5 SDK

ProsperoEden's RADV Vulkan integration requires a custom PS5 Payload SDK containing:

```text
libps5platform.a
```

The Mihawk Vulkan dependency setup expects a custom SDK fork. In this Docker environment, the SDK fork is located at:

```text
/mihawk-sdk-review
```

Explicitly provide that location:

```bash
cd /mihawk-vulkan-review

PS5_PAYLOAD_SDK_FORK=/mihawk-sdk-review \
  bash tools/setup-native-dependencies.sh
```

The setup process should prepare the custom PS5 Payload SDK and its dependencies.

Our tested setup used:

```text
PS5 Payload SDK: v0.42
SDK fork commit: b83202be73e9
zlib: 1.3.2
```

These versions describe the tested dependency state; the project's pinned dependencies should remain authoritative.

### Verify the platform library

```bash
ls -lh \
  /mihawk-vulkan-review/.deps/native/ps5-payload-sdk/target/lib/libps5platform.a
```

In our test, the library was approximately 367 KB.

Also verify that the SDK linker exists:

```bash
ls -lh \
  /mihawk-vulkan-review/.deps/native/ps5-payload-sdk/bin/prospero-lld
```

Return to the project:

```bash
cd /workspace
```

**Why this is necessary**

Without the platform library, the final emulator link may fail with:

```text
missing /workspace/../mihawk-vulkan-review/.deps/native/ps5-payload-sdk/target/lib/libps5platform.a
```

Since `/workspace/..` resolves to `/`, this refers to the Mihawk dependency checkout at `/mihawk-vulkan-review`.

Do not create an empty placeholder library or substitute an unrelated SDK archive.

## 7. Build ProsperoEden

Run:

```bash
cd /workspace

EDEN_SKIP_SOURCE_CHECKS=1 make release JOBS=4
```

### Build parameters

**`JOBS=4`**

Limits build parallelism to four jobs. This can reduce memory pressure when running an AMD64 container on Apple Silicon.

**`EDEN_SKIP_SOURCE_CHECKS=1`**

The documented Apple Silicon Docker workflow skips host-side source checks
that are incompatible with translated x86 execution. Native Linux CI should leave
this switch unset. Run supported focused regressions separately.

The JIT allocator check recognizes Docker Desktop's
`VirtualApple` x86 translation and refreshes executable permissions after a test
rewrite, while still checking both aliases and the returned result. Native x86
CI keeps its original live-rewrite path.

**`EDEN_SELF_UPDATE` (default `OFF`)**

The self-update helper (`self-updater.elf`) is not built or shipped by default, because it needs a hosted signed catalog (`homebrew.page`). Set `EDEN_SELF_UPDATE=ON` to build and ship it.

If you explicitly set `EDEN_SKIP_SOURCE_CHECKS=1`, compilation, linking and package
validation still run, but the result has not passed the complete source-check suite.

### Optional AddressSanitizer workaround

If AddressSanitizer leak detection causes problems during host-side execution, try:

```bash
ASAN_OPTIONS=detect_leaks=0 \
EDEN_SKIP_SOURCE_CHECKS=1 \
make JOBS=4
```

This disables leak detection for affected processes; it does not correct memory-safety errors.

### Rebuilding after a failure

If a build fails due to a missing dependency, install or prepare the dependency and rerun:

```bash
EDEN_SKIP_SOURCE_CHECKS=1 make release JOBS=4
```

Ninja and the other build tools should reuse completed artifacts where possible.

Do not delete the entire cache or run a full clean unless necessary.

## 8. Build outputs

After a successful release build, the expected output structure is:

```text
dist/
├── ProsperoEden-v1.000.001.zip
└── SHA256SUMS

build/
└── release/
    └── PPSA99018/
        ├── eboot.bin
        ├── core-homebrew.nro
        ├── lapy.elf
        ├── lapy-manifest.json
        ├── sce_module/
        ├── sce_sys/
        └── ...
```

Additional files and directories may be present depending on the build configuration.

The release ZIP contains the `PPSA99018` application folder.

## 9. Verify the release

First verify the SHA-256 checksums:

```bash
cd /workspace

(cd dist && sha256sum -c SHA256SUMS)
```

Expected:

```text
ProsperoEden-v1.000.001.zip: OK
```

Verify ZIP integrity:

```bash
unzip -t \
  dist/ProsperoEden-v1.000.001.zip | tail -1
```

Expected:

```text
No errors detected in compressed data
```

### Verify application metadata

```bash
python3 - <<'PY'
import json
from zipfile import ZipFile

archive = "dist/ProsperoEden-v1.000.001.zip"

with ZipFile(archive) as z:
    data = json.loads(
        z.read("PPSA99018/sce_sys/param.json")
    )

assert data["titleId"] == "PPSA99018"
assert data["contentVersion"] == "01.000.001"
assert (
    data["localizedParameters"]["en-US"]["titleName"]
    == "ProsperoEden"
)

print("PASS: Application metadata verified")
PY
```

Check the executable in the ZIP:

```bash
unzip -l \
  dist/ProsperoEden-v1.000.001.zip \
  | grep 'PPSA99018/eboot.bin'
```

These tests verify the generated artifact and application metadata. They do not prove that the emulator runs correctly on PS5 hardware.

## 10. Install on PS5

Extract the release archive.

The application folder inside the ZIP is:

```text
PPSA99018/
```

For a homebrew folder installation, the expected destination is:

```text
/data/homebrew/PPSA99018/
```

Copy the application files to the PS5 using your existing homebrew file-transfer setup.

Ensure ProsperoEden is closed before replacing files.

Depending on your ShadowMount+ setup, a rescan or PS5 restart may be required for application registration.

**Important:** This build uses its own title ID (`PPSA99018`) so it installs beside, rather than over, other ProsperoEden builds.

## 11. Reuse the Docker container

From a Mac terminal:

```bash
docker start -ai prosperoeden-build
```

Inside Docker:

```bash
cd /workspace

EDEN_SKIP_SOURCE_CHECKS=1 make release JOBS=4
```

The Docker volume retains `/root/.cache`, while the stopped container retains other files created inside it.

The vendored dependency cache (`vendor/`, git-ignored) lives in the repository checkout, not in the container, so it persists across containers. `make distclean` backs it up to `.vendor-backup/` before cleaning; `make clean-vendor` removes both.

### Start a shell in an already running container

```bash
docker exec -it prosperoeden-build bash
```

### Stop the container

Inside Docker:

```bash
exit
```

You can also stop it from macOS:

```bash
docker stop prosperoeden-build
```

## 12. Troubleshooting

### GNU tar: Function not implemented

**Symptom**

```text
tar: Cannot mkdir: Function not implemented
```

**Solution**

Install `libarchive-tools` and configure the `bsdtar` wrapper described in Step 4.

### FFmpeg: NASM missing

**Symptom**

```text
nasm not found or too old
```

**Solution**

```bash
apt-get install -y nasm yasm
```

Then rerun the build.

### Runtime libc.prx: ccache missing

**Symptom**

```text
Install ccache or set USE_CCACHE=0
```

**Solution**

```bash
apt-get install -y ccache
```

Alternatively:

```bash
USE_CCACHE=0 \
EDEN_SKIP_SOURCE_CHECKS=1 \
make JOBS=4
```

### Missing libps5platform.a at final linking

**Symptom**

```text
missing /workspace/../mihawk-vulkan-review/.deps/native/ps5-payload-sdk/target/lib/libps5platform.a
```

**Solution**

```bash
cd /mihawk-vulkan-review

PS5_PAYLOAD_SDK_FORK=/mihawk-sdk-review \
  bash tools/setup-native-dependencies.sh
```

Verify:

```bash
test -f \
  /mihawk-vulkan-review/.deps/native/ps5-payload-sdk/target/lib/libps5platform.a \
  && echo "PASS: Platform library exists"
```

Then:

```bash
cd /workspace
EDEN_SKIP_SOURCE_CHECKS=1 make release JOBS=4
```

### SparseLargeVector: missing mirror_index

**Symptom**

```text
error: no member named 'mirror_index' in
'Common::SparseLargeVector<Common::PageTable::PageEntryData>'
```

This indicates an incompatibility between the sparse-vector interface and the page-table implementation being compiled.

Possible causes include incompatible generated headers, dependency revisions, or source changes.

Check the repository revision and the generated headers before modifying emulator code.

A fresh checkout and dependency cache can help rule out stale build artifacts, but will not fix an actual source incompatibility.

Do not remove JIT memory-management code just to bypass this error.

### Packaging validation: application name mismatch

If the fork uses `ProsperoEden Fork` but validation expects `ProsperoEden`, review these files:

```text
sce_sys/param.json
tools/package-headless-native.sh
headless/check_package.py
```

The application metadata and packaging assertions should agree.

Do not disable the validation checks to work around mismatched metadata.

### Build errors after switching Git branches

The repository is bind-mounted at `/workspace`.

Switching branches can leave generated files and dependency artifacts from a different source revision.

For a clean build, prefer:

1. A fresh Git clone
2. A new Docker cache volume
3. A fresh container
4. Regenerated build and dependency directories

Avoid deleting useful caches during routine rebuilds.

### Build finishes, but the game crashes on PS5

A successful build only proves that the host compilation and applicable packaging checks completed.

Runtime failures may involve:

- Graphics renderer or Vulkan integration
- PS5 memory allocation
- JIT execution
- Firmware and keys
- Game updates and DLC
- Emulator settings
- Game-specific compatibility

Test on PS5 hardware before treating the build as stable.

## 13. Fork information

| Property | Value |
|---|---|
| Repository | `bf39l/ProsperoEden` |
| Branch | `v26.011.018` |
| Upstream | Eden master (`d85bad89`) |
| PS5 title ID | `PPSA99018` |
| Content version | `01.000.001` |
| Display name | `ProsperoEden` |
| Release archive | `ProsperoEden-v1.000.001.zip` |
| Docker platform | `linux/amd64` |
| Docker base image | `ubuntu:26.04` |

### Fork-specific changes

- Tracks Eden's current master (`d85bad89`) as the emulator base
- Backports per-game folder scanning
- Supports discovering base NSP/XCI files one folder level below the ROM directory
- Includes update/DLC handling associated with the folder-scanning backport
- Uses custom fork branding and release naming
- Includes Docker build instructions for Apple Silicon

## Notes

- This guide documents the build configuration tested under Docker AMD64 emulation on Apple Silicon.
- The Mihawk SDK setup is necessary for the RADV build configuration encountered during testing.
- The build uses the upstream project's pinned dependencies.
- `EDEN_SKIP_SOURCE_CHECKS=1` reduces the validation coverage; it is not a general-purpose compatibility fix.
- The fork's recursive game scanning and runtime compatibility should be verified on PS5 hardware.
- Do not merge unrelated `main` changes into this release branch without evaluating their effect on game compatibility.