# Report 3 — SIMD vs SIMT: arith / gather / scatter

## What we did

Benchmarked identical workloads written in both models on a single core, in
fp32 and fp16: a dense arithmetic sequence, an independent gather, and an
independent scatter.

- **arith** — a sequence of vector add/mul/div (`a+=b; a=b; a/=b; b+=a; b*=a; b/=a; out=a+b`).
- **gather** — `out[i] = src[index[i]]` (reverse permutation).
- **scatter** — `dst[index[i]] = src[i]`.

SIMD uses low-level RegBase APIs (`Reg::Add/Mul/Div` for arith, the basic
`AscendC::Gather`/`AscendC::Scatter` for gather/scatter). SIMT uses native
array indexing. All are float `N=4096`, one block.

## Why

SIMT is marketed for "discrete/scattered memory access", and gather is the
canonical case where it should shine. We wanted to measure whether that is
real, or whether SIMD's dedicated hardware gather wins anyway.

## What we wanted to check

1. Dense arithmetic: does SIMD's 64-lane register beat SIMT's 32-lane warp?
2. Gather: does SIMT's per-thread address computation beat SIMD's hardware
   `RV_VGATHER2`?
3. fp16: does the gap widen (SIMD gets 128 half/register, SIMT stays 32 lanes)?

## Result (Total tick, lower is better)

| kernel | SIMD | SIMT | SIMD speedup |
|---|---|---:|---:|
| arith (fp32) | 4126 | 13049 | 3.16× |
| gather (fp32) | 4043 | 20896 | 5.17× |
| scatter (fp32) | 4046 | 12924 | 3.19× |
| arith (fp16) | 3346 | 12795 | 3.82× |
| gather (fp16) | 3502 | 20352 | 5.81× |
| scatter (fp16) | 3528 | 12870 | 3.65× |

- SIMD wins everywhere. The gather instruction histogram shows the difference:
  SIMD does **one `RV_VGATHER2` per 64 elements**; SIMT synthesizes each gather
  from `SIMT_LDG` + `SIMT_LEA` + `SIMT_LEA_HI_X` + `SIMT_IMAD_I` address math
  (32 lanes per instruction), with no hardware gather.
- fp16 widened the gap (SIMD went from 64 to 128 lanes/register; SIMT is fixed
  at 32 lanes/warp).

## Reproduce

```bash
./scripts/docker-run.sh ./scripts/build.sh sim dav-3510

for k in arith_simd arith_simt gather_simd gather_simt scatter_simd scatter_simt \
         arith_simd_half arith_simt_half gather_simd_half gather_simt_half \
         scatter_simd_half scatter_simt_half; do
  ./scripts/docker-run.sh bash -lc "mkdir -p /workspace/out/run && cd /workspace/out/run \
    && /workspace/build/sim-3510/$k"
done
#   arith_simd:   Total tick: 4126   PASS
#   arith_simt:   Total tick: 13049  PASS
#   gather_simd:  Total tick: 4043   PASS
#   gather_simt:  Total tick: 20896  PASS
#   scatter_simd: Total tick: 4046   PASS
#   scatter_simt: Total tick: 12924  PASS
#   (half variants similar, see table)

# Confirm SIMD gather is a single hardware instruction per 64 elements.
./scripts/docker-run.sh bash -lc 'grep -c RV_VGATHER2 /workspace/out/run/core0.veccore0.instr_log.dump'
#   64
```
