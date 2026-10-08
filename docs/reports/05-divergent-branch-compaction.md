# 05 — Divergent branch: naive SIMD vs SIMT vs stream-compaction SIMD

## What we did

Benchmarked a **data-dependent divergent branch** — the workload SIMT is officially
positioned for — under three implementations:

| kernel | file | approach |
|---|---|---|
| `branch_simd` | `apps/branch_simd.asc` | SIMD RegBase, **masked but unskippable** expensive loop (runs for all 64 lanes) |
| `branch_simt` | `apps/branch_simt.asc` | SIMT native `if` (warps skip the expensive path) |
| `branch_simd_compact` | `apps/branch_simd_compact.asc` | SIMD **stream compaction**: gather → operate → scatter |

The workload is `y[i] = x[i] < thr ? contract(x[i]) : x[i]`, where `contract(e)` is 64
iterations of `e = e*0.5 + 0.5`. Only ~1% of elements (`i % 100 == 0`) are below `thr`,
so the expensive branch is **rare** and its cost dominates only for the rare elements.

* `branch_simd_compact` takes an argument: `sparse` (default, ~1% rare) or `dense` (~12.5% rare).

## Why we did it

SIMT's official motivation is "complex control flow and branch divergence". We wanted a
case where the divergent-branch penalty is real, to answer three questions:

1. Does SIMT actually beat a *naive* SIMD on divergence?
2. Is the naive SIMD form (mask that zeroes but cannot skip) the *only* SIMD option?
3. Can a well-tuned SIMD (**stream compaction**: compact the rare elements, run the
   expensive loop on the compacted subset, scatter back) beat both?

This is the only experiment in the series where a "SIMT wins" result first appeared —
and the point of the third kernel was to check whether that win is fundamental or an
artifact of comparing against an untuned SIMD.

## What we wanted to check

* **Divergence granularity**: a SIMD vector is 64 fp32 lanes; a SIMT warp is 32 lanes.
  When any SIMD lane diverges, the masked loop still executes for all 64 lanes; when any
  warp lane diverges, only 32 lanes pay. Hypothesis: SIMT wins over naive SIMD.
* **Compaction as the optimal SIMD form**: if we first *compact* the ~1% rare elements,
  the expensive loop runs on ~1 vector instead of 64. Hypothesis: compaction SIMD wins
  over both.

## Results

All three `PASS` (bit-exact against the host reference), dav-3510 simulator, single core,
`Total tick` (lower is better):

| kernel | rare count | tick | vs naive SIMD |
|---|---|---:|---:|
| `branch_simd` (naive masked) | 41 (~1%) | **32170** | 1.0x |
| `branch_simt` (native `if`) | 41 | **17102** | 1.88x faster |
| `branch_simd_compact sparse` | 41 | **4762** | 6.8x faster |
| `branch_simd_compact dense` | 512 (~12.5%) | **6820** | 4.7x faster |

Conclusions:

1. **SIMT does beat naive SIMD** (1.88x) — the only "SIMT wins" case in this whole study.
2. That win is against a **suboptimal** SIMD. **Compaction SIMD beats SIMT by 3.6x**
   (4762 vs 17102) and naive SIMD by 6.8x.
3. The instruction trace confirms the mechanism: `branch_simd` emits ~4096 `RV_VMULS` +
   ~4096 `RV_VADDS` (the 64-iteration loop runs unconditionally over all 64 vectors),
   while `branch_simt` emits `SIMT_FSETP`/`SIMT_BRANCH` and *no* `SIMT_FMUL`/`SIMT_FADD`
   (non-divergent warps skip the loop), and `branch_simd_compact` runs the loop on a
   single compacted vector.

## Reproduce

All commands run inside the CANN dev container; nothing needs to be run to read the
expected output shown in the `#` comments.

```bash
# Build the simulator targets for Ascend 950 (dav-3510).
./scripts/docker-run.sh ./scripts/build.sh sim dav-3510
# ... [ASC] Linking ... branch_simd, branch_simt, branch_simd_compact

# Naive SIMD: run in a clean CWD; the simulator prints "Total tick" and dumps core*.instr_log.dump here.
mkdir -p /workspace/out/branch_simd && cd /workspace/out/branch_simd
/workspace/build/sim-3510/branch_simd
# branch_simd: PASS (4096 elements)
# Total tick: 32170

# SIMT (native if).
mkdir -p /workspace/out/branch_simt && cd /workspace/out/branch_simt
/workspace/build/sim-3510/branch_simt
# branch_simt: PASS (4096 elements)
# Total tick: 17102

# Compaction SIMD, sparse (~1% rare) and dense (~12.5% rare).
mkdir -p /workspace/out/branch_compact_sparse && cd /workspace/out/branch_compact_sparse
/workspace/build/sim-3510/branch_simd_compact sparse
# branch_simd_compact[sparse]: PASS (4096 elements)
# Total tick: 4762

mkdir -p /workspace/out/branch_compact_dense && cd /workspace/out/branch_compact_dense
/workspace/build/sim-3510/branch_simd_compact dense
# branch_simd_compact[dense]: PASS (4096 elements)
# Total tick: 6820

# Instruction-level evidence (from the simulator dump of each run):
#   naive SIMD:   grep -c RV_VMULS  core0.veccore0.instr_log.dump   # 4096  (unskippable loop)
#   SIMT:         grep -c SIMT_BRANCH core0.veccore0.instr_log.dump  # ~136  (warps skip)
#   compaction:   grep -c RV_VMULS  core0.veccore0.instr_log.dump   # 64    (loop on 1 compacted vector)
```
