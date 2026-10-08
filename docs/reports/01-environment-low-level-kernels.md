# Report 1 — Environment + low-level kernels

## What we did

Stand up a reproducible, hardware-free AscendC development environment, then
write three kernels at the lowest public API level and validate them in CPU
twin-debug and simulator modes on two targets.

- **`vector_add`** — element-wise add. On Ascend 950 (`dav-3510`) it uses the
  RegBase register API (`Reg::RegTensor`, `Reg::LoadAlign`, `Reg::Add`,
  `Reg::StoreAlign` via `asc_vf_call`); on Ascend 910B (`dav-2201`, MemBase) it
  uses UB staging + `AscendC::Add`.
- **`direct_mmad`** — matrix multiply through the raw data path, with no
  `AscendC::Matmul` object, no `IterateAll`, no `REGIST_MATMUL_OBJ`. GM ND →
  L1 NZ → L0A/L0B → `AscendC::Mmad` → L0C → `Fixpipe` → GM ND.
- **`add_mmad_add`** — one fused `__mix__(1, 2)` launch: AIV pre-add, AIC MMAD,
  AIV post-add, synchronized with `CrossCoreSetFlag`/`CrossCoreWaitFlag`.

## Why

The user wanted a Dockerized AscendC kernel-development environment with no NPU
hardware (CPU execution), strictly low-level APIs, and visibility into every
operation. The point was to confirm that the whole toolchain — compiler,
CPU-debug libraries, and simulator — works from a locally installed, checksum
pinned CANN toolkit, and that low-level MMAD / RegBase programming is actually
expressible and runnable.

## What we wanted to check

1. That a digest-pinned Docker image with a local CANN 9.2.0-beta.2 `.run`
   installer builds and provides `bisheng`, CMake ASC integration, CPU-debug
   libraries, and the simulator.
2. That direct `AscendC::Mmad` (not the high-level Matmul framework) works on
   both `dav-2201` and `dav-3510`.
3. That RegBase register add works on 950 and that MemBase add is the 910B path.
4. That a single fused MIX kernel (add → MMAD → add) launches once and passes.

## Result

All **12** configurations pass: `{cpu, sim} × {dav-2201, dav-3510} ×
{vector_add, direct_mmad, add_mmad_add}`.

Simulator `Total tick` (CA-model cycle count, lower is better). **Tick is not
comparable across architectures**: `Ascend910B1` (dav-2201) and
`Ascend950PR_9599` (dav-3510) are different simulator models with their own
cycle accounting and clock scaling, so the two columns confirm each kernel
*runs* on each SoC but must not be compared left-to-right (a higher 3510 tick
does not mean 950 is slower — `vector_add` shows the same ~1.8x even though it
has no MMAD and no AIV↔AIC sync):

| kernel | dav-2201 tick | dav-3510 tick |
|---|---:|---:|
| `vector_add` | 2807 | 5005 |
| `direct_mmad` | 3898 | 6920 |
| `add_mmad_add` | 7728 | 16713 |

The environment provides `ASCEND_HOME_PATH`, `bisheng`, `msobjdump`, `msprof`,
`mssanitizer`, and simulator directories for `dav_2201`, `dav_3510`,
`Ascend910B1`, and `Ascend950PR_9599`.

## Reproduce

```bash
# 1. Fetch the checksum-pinned CANN installer (requires license acceptance).
./scripts/fetch-cann.sh --accept-license
#   downloads/Ascend-cann-toolkit_9.2.0-beta.2_linux-x86_64.run  (~1.4 GB)

# 2. Build the Docker image (flag = explicit EULA acceptance).
./scripts/docker-build.sh --accept-eula
#   -> ascendc-low-level:9.2.0-beta.2

# 3. Verify the toolchain inside the image.
./scripts/docker-run.sh ./scripts/check-environment.sh
#   ASCEND_HOME_PATH=/usr/local/Ascend/cann-9.2.0-beta.2
#   bisheng ...  cmake ...  msobjdump ...  msprof ...  mssanitizer ...
#   simulator: dav_2201 dav_3510 Ascend910B1 Ascend950PR_9599

# 4. CPU twin-debug functional tests (no timing).
./scripts/docker-run.sh ./scripts/test.sh cpu dav-2201
./scripts/docker-run.sh ./scripts/test.sh cpu dav-3510
#   vector_add ... PASS
#   direct_mmad ... PASS
#   add_mmad_add ... PASS

# 5. Simulator tests (timing via "Total tick").
./scripts/docker-run.sh ./scripts/test.sh sim dav-2201
./scripts/docker-run.sh ./scripts/test.sh sim dav-3510
#   vector_add ... PASS
#   direct_mmad ... PASS
#   add_mmad_add ... PASS

# 6. Timing (run each kernel directly; "Total tick" is the CA-model cycle count).
./scripts/docker-run.sh bash -lc 'cd /workspace && for k in vector_add direct_mmad add_mmad_add; do ./build/sim-2201/$k; done'
#   vector_add:    Total tick: 2807
#   direct_mmad:   Total tick: 3898
#   add_mmad_add:  Total tick: 7728
./scripts/docker-run.sh bash -lc 'cd /workspace && for k in vector_add direct_mmad add_mmad_add; do ./build/sim-3510/$k; done'
#   vector_add:    Total tick: 5005
#   direct_mmad:   Total tick: 6920
#   add_mmad_add:  Total tick: 16713

# 7. Inspect the generated device ELF for one kernel.
./scripts/docker-run.sh ./scripts/extract-elf.sh vector_add
#   out/device-elf/vector_add/vector_add.aicore.o  (elf64-hiipu)
```
