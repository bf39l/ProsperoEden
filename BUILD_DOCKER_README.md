# Build ProsperoEden Fork with Docker

Build ProsperoEden for PlayStation 5 on an Apple Silicon Mac using an Ubuntu AMD64 Docker container.

This guide is based on the **`v1.000.111-fork`** branch, derived from the official upstream `v1.000.111` prerelease.

The fork preserves the upstream prerelease UI and emulator implementation while adding per-game directory scanning, including support for games with updates and DLC stored in individual folders.

## Requirements

- macOS with Apple Silicon
- Docker Desktop with AMD64 emulation enabled (Rosetta where available)
- Git
- Sufficient disk space for SDK dependencies, FFmpeg, emulator source, and build artifacts
- Repository checked out to `v1.000.111-fork`

Repository: https://github.com/bf39l/ProsperoEden

## 1. Clone the repository

On your Mac:

```bash
git clone https://github.com/bf39l/ProsperoEden.git

cd ProsperoEden

git switch v1.000.111-fork
```

Verify the branch:

```bash
git branch --show-current
```

Expected:

```text
v1.000.111-fork
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

`make deps` fetches the dependencies required by ProsperoEden, including the Mihawk Vulkan and SDK source repositories.

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

## 7. Build ProsperoEden Fork

Run:

```bash
cd /workspace

EDEN_SKIP_SOURCE_CHECKS=1 make JOBS=4
```

### Build parameters

**`JOBS=4`**

Limits build parallelism to four jobs. This can reduce memory pressure when running an AMD64 container on Apple Silicon.

**`EDEN_SKIP_SOURCE_CHECKS=1`**

Skips host-side source checks that failed under AMD64 emulation, particularly the JIT allocator execution checks.

The build still performs its normal compilation, linking, and applicable package validation steps.

However, skipping these checks means the result has not passed the complete upstream validation procedure.

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
EDEN_SKIP_SOURCE_CHECKS=1 make JOBS=4
```

Ninja and the other build tools should reuse completed artifacts where possible.

Do not delete the entire cache or run a full clean unless necessary.

## 8. Build outputs

After a successful release build, the expected output structure is:

```text
dist/
├── ProsperoEden-v1.000.111-fork.zip
└── SHA256SUMS

build/
└── release/
    └── PPSA99016/
        ├── eboot.bin
        ├── core-homebrew.nro
        ├── lapy.elf
        ├── lapy-manifest.json
        ├── sce_module/
        ├── sce_sys/
        └── ...
```

Additional files and directories may be present depending on the build configuration.

The release ZIP contains the `PPSA99016` application folder.

## 9. Verify the release

First verify the SHA-256 checksums:

```bash
cd /workspace

sha256sum -c dist/SHA256SUMS
```

Expected:

```text
ProsperoEden-v1.000.111-fork.zip: OK
```

Verify ZIP integrity:

```bash
unzip -t \
  dist/ProsperoEden-v1.000.111-fork.zip | tail -1
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

archive = "dist/ProsperoEden-v1.000.111-fork.zip"

with ZipFile(archive) as z:
    data = json.loads(
        z.read("PPSA99016/sce_sys/param.json")
    )

assert data["titleId"] == "PPSA99016"
assert data["contentVersion"] == "01.000.111"
assert (
    data["localizedParameters"]["en-US"]["titleName"]
    == "ProsperoEden Fork"
)

print("PASS: Fork metadata verified")
PY
```

Check the executable in the ZIP:

```bash
unzip -l \
  dist/ProsperoEden-v1.000.111-fork.zip \
  | grep 'PPSA99016/eboot.bin'
```

These tests verify the generated artifact and application metadata. They do not prove that the emulator runs correctly on PS5 hardware.

## 10. Install on PS5

Extract the release archive.

The application folder inside the ZIP is:

```text
PPSA99016/
```

For a homebrew folder installation, the expected destination is:

```text
/data/homebrew/PPSA99016/
```

Copy the application files to the PS5 using your existing homebrew file-transfer setup.

Ensure ProsperoEden is closed before replacing files.

Depending on your ShadowMount+ setup, a rescan or PS5 restart may be required for application registration.

**Important:** The fork uses the same title ID as the official `v1.000.111` prerelease. Installing it may replace that prerelease's registration rather than create a separate PS5 Home screen entry.

The original `PPSA99008` installation uses a different title ID.

## 11. Reuse the Docker container

From a Mac terminal:

```bash
docker start -ai prosperoeden-build
```

Inside Docker:

```bash
cd /workspace

EDEN_SKIP_SOURCE_CHECKS=1 make JOBS=4
```

The Docker volume retains `/root/.cache`, while the stopped container retains other files created inside it.

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
EDEN_SKIP_SOURCE_CHECKS=1 make JOBS=4
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
| Branch | `v1.000.111-fork` |
| Upstream release | `v1.000.111` |
| PS5 title ID | `PPSA99016` |
| Content version | `01.000.111` |
| Display name | `ProsperoEden Fork` |
| Release archive | `ProsperoEden-v1.000.111-fork.zip` |
| Docker platform | `linux/amd64` |
| Docker base image | `ubuntu:26.04` |

### Fork-specific changes

- Retains the upstream `v1.000.111` UI and emulator code as the base
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