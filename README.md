# AscendC Low-Level Lab

A reproducible Docker monorepo for low-level AscendC development targeting
Ascend 910B (`dav-2201`) and Ascend 950 (`dav-3510`). No NPU is needed for CPU
twin debugging or simulator profiling.

The lab contains three checked executables:

- `vector_add`: UB basic-vector add on 910B; explicit RegTensor add on 950.
- `direct_mmad`: GM/L1/L0A/L0B/L0C programming with direct `AscendC::Mmad`.
- `add_mmad_add`: one fused MIX kernel launch with AIV add, AIC MMAD, and AIV add.

See `docs/ARCHITECTURE.md` for exact memory paths and synchronization.

## Fresh clone

Requirements are Docker on an x86_64 Linux machine and enough disk space for
the approximately 1.4 GB toolkit download plus the built image.

1. Review CANN Software User License Agreement 2.0:
   https://www.hiascend.com/legal/cannua-download?isNewCon=true
2. Download the checksum-pinned installer:

```bash
./scripts/fetch-cann.sh --accept-license
```

3. Build the digest-pinned image. The explicit flag is required because the
   vendor installer's quiet mode constitutes EULA acceptance:

```bash
./scripts/docker-build.sh --accept-eula
```

4. Run all CPU functional tests for each target:

```bash
make test-cpu-2201
make test-cpu-3510
```

The installer, build trees, traces, and external reference clones are ignored
by Git. `dependencies.lock` records the URL, exact SHA-256, base-image digest,
and source commits needed to reconstruct the environment on another machine.

## Build matrix

Each run mode and architecture gets a separate CMake tree:

```bash
./scripts/docker-run.sh ./scripts/build.sh cpu dav-2201
./scripts/docker-run.sh ./scripts/build.sh sim dav-2201
./scripts/docker-run.sh ./scripts/build.sh cpu dav-3510
./scripts/docker-run.sh ./scripts/build.sh sim dav-3510
```

Do not reuse a CMake cache across modes or architectures. Enter an interactive
development shell with:

```bash
make shell
```

Run `./scripts/check-environment.sh` inside the container to show installed
compiler and analysis tools. More workflows are documented in `docs/TOOLS.md`.

## Scope and limitations

- CPU twin mode validates basic behavior but does not model NPU timing.
- Simulator profiling estimates instruction behavior but is not a hardware benchmark.
- Final performance, race, and memory qualification requires actual target hardware.
- The repository does not grant rights to redistribute Huawei CANN binaries or built images.
- CANN 9.2.0-beta.2 is pinned because it provides the documented 950 RegBase APIs.

No project-wide source license has been selected. Add one appropriate for your
intended distribution before publishing this repository.
