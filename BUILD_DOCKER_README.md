# Build ProsperoEden Fork with Docker

Build ProsperoEden for PS5 on an Apple Silicon Mac using an Ubuntu AMD64 Docker container.

This guide is based on the `fork-v1.000.111` branch, derived from the upstream `v1.000.111` prerelease.

## Requirements

- macOS with Apple Silicon
- Docker Desktop with AMD64 emulation enabled
- Git repository checked out to `fork-v1.000.111`

## 1. Create the Docker container

From the root of the ProsperoEden repository on your Mac:

```bash
docker run -it \
  --name prosperoeden-build-v111 \
  --platform linux/amd64 \
  -v "$PWD:/workspace" \
  -v prosperoeden-cache-v111:/root/.cache \
  -w /workspace \
  ubuntu:26.04 \
  bash
```

The repository is mounted at `/workspace`, and the Docker volume preserves the build cache across container restarts.

## 2. Install build dependencies

Inside the Docker container:

```bash
apt-get update

apt-get install -y --no-install-recommends \
  $(grep -v '^#' tools/ci/ubuntu-packages.txt)

apt-get install -y --no-install-recommends \
  libarchive-tools nasm yasm ccache
```

The additional packages address issues encountered while building under AMD64 emulation on Apple Silicon.

## 3. Apply the tar compatibility workaround

GNU tar encountered `Function not implemented` errors when extracting dependencies under Docker AMD64 emulation.

Use `bsdtar` instead:

```bash
cat > /usr/local/bin/tar <<'EOF'
#!/bin/sh
exec /usr/bin/bsdtar "$@"
EOF

chmod +x /usr/local/bin/tar
hash -r
```

Verify:

```bash
tar --version
```

The wrapper applies only inside this Docker container.

## 4. Prepare the toolchain

```bash
cd /workspace
make toolchain
```

## 5. Build ProsperoEden

```bash
EDEN_SKIP_SOURCE_CHECKS=1 make JOBS=4
```

`JOBS=4` limits parallel build jobs.

`EDEN_SKIP_SOURCE_CHECKS=1` skips host-side source checks that failed under AMD64 emulation, including the JIT allocator check. This does not disable every packaging check, but it means the build has not passed the full upstream validation process.

If AddressSanitizer leak detection causes problems during host-side execution, the following may help:

```bash
ASAN_OPTIONS=detect_leaks=0 \
EDEN_SKIP_SOURCE_CHECKS=1 \
make JOBS=4
```

This disables leak detection for the affected processes; it does not fix memory errors.

## 6. Build outputs

After a successful build:

```text
dist/
├── ProsperoEden-v1.000.111-fork.zip
└── SHA256SUMS

build/
└── release/
    └── PPSA99016/
        ├── eboot.bin
        ├── sce_sys/
        ├── sce_module/
        └── ...
```

Additional release files may be generated depending on the build configuration.

## 7. Verify the release

```bash
sha256sum -c dist/SHA256SUMS

unzip -t \
  dist/ProsperoEden-v1.000.111-fork.zip
```

Check the package title ID:

```bash
unzip -l \
  dist/ProsperoEden-v1.000.111-fork.zip \
  | grep 'PPSA99016/eboot.bin'
```

The expected title ID is `PPSA99016`.

## 8. Reuse the container

From macOS:

```bash
docker start -ai prosperoeden-build-v111
```

Inside Docker:

```bash
cd /workspace
EDEN_SKIP_SOURCE_CHECKS=1 make JOBS=4
```

To leave the container without deleting it:

```bash
exit
```

## Notes

- The application name is `ProsperoEden Fork`.
- The PS5 content version is `01.000.111`.
- The fork