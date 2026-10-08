# Report 4 — Chained gather: dependency chains

## What we did

Built a gather whose *output feeds the next gather*: split data into 128-element
chunks and apply the same index array four times in sequence
(`arr1 = gather(chunk, idx); arr2 = gather(arr1, idx); ...`). Compared SIMD
(low-level `AscendC::Gather`) vs SIMT (shared memory + `asc_syncthreads()`),
then tried to software-pipeline the SIMD chain and, finally, swept the repeat
count to separate fixed launch cost from per-pass work.

## Why

After Report 3 showed SIMD wins on *independent* gather, the question was
whether a *dependent* chain changes the picture — SIMD's hardware gather has
nothing to overlap when each level waits on the previous, while SIMT's shared
memory intermediates are cheap.

## What we wanted to check

1. Does a chained (dependent) gather make SIMD ≈ SIMT?
2. Does software-pipelining the SIMD chain help, or does the hardware already
   hide the RAW hazard?
3. Is the single-pass gap between the two models real work or launch overhead?

## Result

- **Chained gather is a tie** in steady state (kRepeats=8): SIMD 50769/51026
  (random/perm) vs SIMT 51180/51209.
- **Software pipelining made SIMD slower** (53491 vs 50769, ~5%). The
  instruction histogram is identical between the two, so the loss is
  scheduling, not code. Ascend 950's hardware vector-pipe scoreboard already
  hides the dependent-`vgather2` RAW hazard, so there is nothing to hide; the
  diagonal schedule + rotating buffers just add scalar/DMA overhead.
- **kRepeats sweep `{1,2,4,8,16}`** (fit `T(k) = F + k·W`):

| | fixed cost F | per-pass work W |
|---|---:|---:|
| SIMD | 2311 | 6075 |
| SIMT | 3052 | 6023 |

  So SIMT's per-pass work is actually ~1% *lower*, but its launch overhead is
  ~32% higher (128-thread block + warp setup vs a single vector worker). The
  earlier "SIMD wins 13% single-pass" was entirely fixed overhead, not compute.

## Reproduce

```bash
./scripts/docker-run.sh ./scripts/build.sh sim dav-3510

# kRepeats is argv[2] (default 8); argv[1] is random|perm.
for k in chained_gather_simd chained_gather_simt chained_gather_simd_pipe; do
  ./scripts/docker-run.sh bash -lc "cd /workspace && ./build/sim-3510/$k random 8"
done
#   chained_gather_simd:      Total tick: 50769   PASS
#   chained_gather_simt:      Total tick: 51180   PASS
#   chained_gather_simd_pipe: Total tick: 53491   PASS

# Sweep the repeat count to separate fixed vs per-pass cost.
./scripts/docker-run.sh bash -lc '
  for k in chained_gather_simd chained_gather_simt; do
    for r in 1 2 4 8 16; do
      mkdir -p /workspace/out/sweep/$k/r$r && cd /workspace/out/sweep/$k/r$r \
        && /workspace/build/sim-3510/$k random $r | grep -i "total tick"
    done
  done'
#   chained_gather_simd r=1  tick=8445   ... r=16 tick=99538
#   chained_gather_simt r=1  tick=9089   ... r=16 tick=99450
#   (fit T(k)=F+k*W: SIMD F=2311 W=6075; SIMT F=3052 W=6023)
```
