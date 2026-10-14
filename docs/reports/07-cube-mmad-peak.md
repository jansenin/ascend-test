# 07 — Cube (MMAD) peak throughput: dtype × architecture sweep

## What we did

Built a single-core **low-level MMAD microbenchmark** (`apps/cube_peak.asc`) and swept
its tile size over every 16-multiple `m,n,k` that fits the on-core buffers, for all four
dtypes (`half`, `float`, `int8`, `bfloat16`) and both architectures (`dav-2201` = 910B,
`dav-3510` = 950).

The kernel is a direct `AscendC::Mmad` loop (no `Matmul` object, no `IterateAll`):

* **B is static** (a `[K,N]`-transposed weight, loaded once into L0B) — weight-stationary,
  the inference pattern.
* **A is streamed** as 16 different `[M,K]` tiles, double-buffered through L1 → L0A,
  so the next A-tile is loaded while the current MMAD runs.
* **16 MMADs accumulate** `C[M,N] = Σ_t A_t · B`, then a `Fixpipe` writes C back to GM.
* The **only thing timed** is the MMADs: from the simulator instruction log we take the
  first-MMAD-issue cycle and the last-MMAD-issue cycle, and report
  `interval = (last − first) / 15` cycles per MMAD. FLOPS = `2·m·n·k / interval`.

The sweep is driven by several scripts (all committed):

| script | purpose |
|---|---|
| `scripts/cube-sweep.sh <arch> <dtype>` | patch the CA-model to a single AIC, run `cube_peak` over every size, emit a CSV |
| `scripts/cube-sweep-all.sh` | loop all 8 {arch} × {dtype} combos sequentially |
| `scripts/cube-graph.py [--x sorted\|mkn\|mn\|mk\|kn]` | plot FLOPS vs a size metric (or rank) from the CSVs |
| `scripts/cube_view3d.py` | interactive 3D FLOPS-vs-(m,n) surface (per-k slider) |
| `scripts/cube_volume.py` | 3D scatter of under-utilized (m,k,n) volume |

## Why we did it

The Cube unit (MMAD) is where an Ascend NPU's headline FLOPS come from. We wanted to
measure that ceiling directly — dtype by dtype and architecture by architecture — instead
of trusting a datasheet number. The sweep over tile size also separates the two regimes
every matmul lives in: **latency-bound** at small tiles and **throughput-bound** at large
tiles.

## What we wanted to check

1. **Does a hand-written MMAD loop hit the theoretical Cube peak?** The Cube issues one
   `16×16×K₀` fractal per cycle (`K₀ = 32/sizeof(T)`: half/bf16 → 16, float → 8, int8 → 32),
   so the ideal fp16 rate is `16·16·16 = 4096 MAC/cycle` = `8192 FLOP/cycle` = 14.75 TFLOPS
   at the 1.8 GHz simulator clock (see the Clock note in `REFERENCE.md` for where that
   clock comes from; it is distinct from the PTO cost model's 1.85 GHz constant).
2. **How does dtype scale?** Is fp16 the peak, is int8 ~2× fp16, and how much slower is fp32?
3. **Does the architecture matter** (910B vs 950) for a single MMAD?
4. **Where is the latency-bound region**, and how big does a tile need to be to saturate?

## Results

20,999 configurations are committed — all `PASS` (bit-exact against a host
reference). An earlier sweep had also emitted 7,176 `int8` rows with `K` not a
multiple of the int8 K-fractal (`K₀ = 32`), which `FAIL`ed at runtime (the
`LoadData` tile count truncates `K/K₀`); that enumeration bug is fixed in
`cube_sweep.py` (the `K` loop steps by `K₀`) and the int8 CSVs were re-swept
clean. Peak throughput (largest valid tile per combo, single-core simulator,
1.8 GHz clock):

| dtype | `dav-2201` (910B) | `dav-3510` (950) | MAC/cycle | ratio vs fp16 |
|---|---:|---:|---:|---:|
| `half` | **14.71 TFLOPS** | **14.73 TFLOPS** | 4096 | 1.0× |
| `bfloat16` | **14.71 TFLOPS** | **14.73 TFLOPS** | 4096 | 1.0× |
| `int8` | **29.43 TOPS** | **29.47 TOPS** | 8192 | 2.0× |
| `float` | **3.68 TFLOPS** | **0.92 TFLOPS** | 1024 / 256 | 0.25× / 0.0625× |

Findings:

1. **half/bf16 hit the Cube peak on both architectures** — the MMAD issue interval matches
   the ideal `(m/16)(n/16)(k/16)` within ~0.2% (ratio ≈ 1.002; the residual is the fixed
   MMAD issue latency). Example: 128×128×256 half on 2201 has interval 1026 vs ideal 1024 →
   14.72 TFLOPS.
2. **int8 is 2× fp16** (8192 MAC/cycle = 29.5 TOPS), also ratio ≈ 1.002 on both archs.
3. **fp32 is dramatically slower and architecture-dependent**: 1024 MAC/cycle on the 910B
   (3.68 TFLOPS, 4× slower than fp16) but only **256 MAC/cycle on the 950** (0.92 TFLOPS,
   16× slower than fp16). The 950's float MMAD is ~4× slower than the 910B's. This is a
   CA-model result and may not match real silicon, but it is a large, reproducible gap.
4. **Small tiles are latency-bound.** At 16×16×160 (the smallest valid tile) the interval
   is ~263 cycles vs an ideal 10 — a 26× overhead — because the fixed MMAD issue latency
   dwarfs the actual work. Throughput rises ~25× from the smallest to the largest tile
   before flattening at the peak.

### A correction worth recording

Our first MTE2 analysis claimed the GM→L1 A-streaming was a ~2× bottleneck ("MTE2 2045 cyc
> MMAD 1049 cyc"). The sweep **disproved** that: half/bf16/int8 already reach ratio 1.00,
   so the per-tile MTE2 transfer is fully hidden by the 2-tile double-buffer (the MTE2 for
   tile *t+1* overlaps MMAD *t*). The naive per-tile latency comparison overstates the DMA
   cost because it ignores pipelining. This is recorded in `docs/LESSONS.md`.

## Graphs

`scripts/cube-graph.py` reads the committed CSVs from `results/cube-sweep/` and
writes its PNGs there too. For each size metric `x ∈ {mkn, mn, mk, kn}` (plus the
default `sorted` rank view used in report 08):

* `results/cube-sweep/flops_by_dtype_x-<m>.png` — 2×2 grid, one subplot per dtype,
  two lines (2201 vs 3510) of TFLOPS vs size (log-log, ideal 14.75 TFLOPS shown as
  a dashed line).
* `results/cube-sweep/flops_by_device_x-<m>.png` — 1×2 grid, one subplot per device,
  one line per dtype.

`mkn` (= m·n·k, the work per MMAD) is the most useful x-axis: FLOPS rises monotonically
with it and plateaus at the dtype peak, cleanly showing the latency-bound → throughput-bound
transition and the dtype ceilings. The `mn`/`mk`/`kn` variants are provided for comparison.

## Reproduce

Everything runs in the CANN dev container; the `#` comments show expected output and do not
need to be run.

```bash
# Build the simulator targets for one architecture.
./scripts/docker-run.sh ./scripts/build.sh sim dav-3510

# Full sweep for one arch + dtype (single-AIC patched inside a throwaway container).
# Produces out/cube-sweep/<arch>/<dtype>.csv with one row per (m,k,n).
./scripts/cube-sweep.sh dav-3510 half
# patched .../config_stars.json -> num_aic=1 num_aiv=2
# arch=3510 dtype=half sizes=3694 workers=8
# wrote /workspace/out/cube-sweep/3510/half.csv (3694 rows)

# Run all 8 combos back-to-back (logs to out/cube-sweep/sweep.log).
./scripts/cube-sweep-all.sh

# A single spot-check run (prints "Total tick" + PASS and dumps core0.cubecore0.instr_log.dump):
./scripts/docker-run.sh bash -lc 'cd /workspace/out/run && /workspace/build/sim-3510/cube_peak 256 64 256 half'
# cube_peak M=256 K=64 N=256 : PASS (maxErr=0.00091)
# Total tick: 28799

# Build the graphs from the committed CSVs (host-side, needs matplotlib). The
# graph/view/volume scripts read results/cube-sweep/, so after a fresh sweep copy
# the CSVs in first: cp -r out/cube-sweep/* results/cube-sweep/.
python3 scripts/cube-graph.py --x mkn
# wrote results/cube-sweep/flops_by_dtype_x-mkn.png
# wrote results/cube-sweep/flops_by_device_x-mkn.png
```
