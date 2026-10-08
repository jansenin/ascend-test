# Experiment reports

Chronological record of every experiment in this lab, each with four parts:
**what we did**, **why**, **what we wanted to check**, and **how to reproduce**
(executable commands with commented expected output — no need to actually run
them).

| # | Report | Kernel(s) |
|---|---|---|
| 1 | [Environment + low-level kernels](01-environment-low-level-kernels.md) | `vector_add`, `direct_mmad`, `add_mmad_add` |
| 2 | [SIMT add + instruction inspection](02-simt-add-assembler.md) | `simt_add` |
| 3 | [SIMD vs SIMT: arith / gather / scatter](03-simd-vs-simt-arith-memory.md) | `arith_*`, `gather_*`, `scatter_*` (+ `_half`) |
| 4 | [Chained gather: dependency chains](04-chained-gather.md) | `chained_gather_*`, `chained_gather_simd_pipe` |
| 5 | [Divergent branch + stream compaction](05-divergent-branch-compaction.md) | `branch_simd`, `branch_simt`, `branch_simd_compact` |
| 6 | [SIMT shared-memory barriers are not optional](06-simt-shared-memory-sync.md) | `chained_gather_simt` (nosync variant) |

## Common workflow

Everything runs inside the Docker image `ascendc-low-level:9.2.0-beta.2`
(CANN 9.2.0-beta.2). `docker-run.sh` mounts the repo at `/workspace` and
sources the toolkit environment, so toolchains and the simulator are always
available.

```bash
# Build the simulator targets for Ascend 950 (the SIMD/SIMT kernels are
# dav-3510 only). Produces build/sim-3510/<target>.
./scripts/docker-run.sh ./scripts/build.sh sim dav-3510

# Run one simulator binary directly. It prints "Total tick: N" (the CA-model
# cycle count) and PASS/FAIL, and dumps per-core instruction traces into CWD.
./scripts/docker-run.sh bash -lc 'cd /workspace && ./build/sim-3510/branch_simd'
#   Total tick: 32170
#   branch_simd: PASS (4096 elems, 64 iters)

# Run a kernel in a clean directory so core*.instr_log.dump files don't land in
# the repo root (they are gitignored either way).
./scripts/docker-run.sh bash -lc 'mkdir -p /workspace/out/run && cd /workspace/out/run \
  && /workspace/build/sim-3510/gather_simd'
#   Total tick: 4043

# Full CTest suite for the simulator + one architecture.
./scripts/docker-run.sh ./scripts/test.sh sim dav-3510

# CPU twin-debug build/run (functional check only, no timing; SIMT has no CPU
# mode).
./scripts/docker-run.sh ./scripts/test.sh cpu dav-3510
```

The single number to compare across kernels is **`Total tick`** (lower is
better). It is the CA-model simulator's cycle counter for the whole launch, not
wall-clock time.

The per-core instruction trace is `core*.veccore*.instr_log.dump` (ASCII, one
line per instruction with a `[%08d]` cycle stamp). Count an instruction's
occurrences to understand what actually ran, e.g.:

```bash
./scripts/docker-run.sh bash -lc 'grep -c RV_VGATHER2 /workspace/out/run/core0.veccore0.instr_log.dump'
#   64
```
