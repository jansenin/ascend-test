# 12 — Scatter is barrier-free where gather isn't

## What we did

Built the transpose of the chained gather: `apps/chained_scatter_simt.asc`
(SIMT) and `apps/chained_scatter_simd.asc` (SIMD). Instead of `a_{k+1}[i] =
a_k[index[i]]` (gather), each level *scatters* the previous buffer through a
distinct permutation:

```
idx = thread_id
nidx = perm[0][idx];  smem[0][nidx] = src[idx]
idx, nidx = nidx, perm[1][nidx];  smem[1][nidx] = smem[0][idx]
idx, nidx = nidx, perm[2][nidx];  smem[2][nidx] = smem[1][idx]
idx, nidx = nidx, perm[3][nidx];  out[nidx]     = smem[2][idx]
```

Four levels, four distinct permutations of 0..127 (`kChunk = 128`). The SIMT
kernel carries the same `template <bool kSync>` flag as the gather, so
`argv[3]=nosync` drops the `asc_syncthreads()` barriers. The SIMD kernel is
four `AscendC::Scatter` calls with no barrier concept. Only the *permutation*
variant is meaningful — scatter with repeating (random) indices is ill-defined
(write–write collision on the same slot).

## Why

Report 06 established that a chained **gather** needs a block barrier even for a
permutation, because a gather reads a *different* thread's slot and the barrier
is what makes that other thread's write visible. The scatter flips which side of
the permuted access is a read and which is a write, so we wanted to see whether
that changes the barrier requirement.

## What we wanted to check

Does a chained scatter over a permutation still need the block barrier, or does
it become barrier-free?

## Result

| variant | barrier | result | Total tick |
|---|---|---|---|
| `chained_scatter_simt perm` | yes | PASS | 13999 |
| `chained_scatter_simt perm,nosync` | no | **PASS** | 9259 |
| `chained_scatter_simd perm` | — | PASS | 7799 |

**Scatter is barrier-free.** Without `asc_syncthreads()` the kernel is both
correct *and* faster (9259 vs 13999 ticks, ~34%), the exact opposite of the
gather, where dropping the barrier produced garbage.

Why: at level *k*, thread *t* reads slot `c_k(t)` and writes
`c_{k+1}(t) = perm[k](c_k(t))`. Because `perm[k]` is a bijection, the slot
`c_k(t)` that thread *t* reads at level *k* is exactly the slot it wrote at
level *k−1` (`c_k(t) = perm[k−1](c_{k−1}(t))`). Each thread's read is its *own*
write, so the whole per-thread data flow is self-contained — there is no
cross-thread read to make visible, and hence no barrier. The gather has the
read and write in the opposite order (`smem[1][pos] = smem[0][index[pos]]` reads
another thread's slot), so it needs the barrier.

The composite effect is `out[P(t)] = src[t]` with
`P = perm[3] ∘ perm[2] ∘ perm[1] ∘ perm[0]`, verified against a host reference
computed by applying the four permutations in sequence.

## Reproduce

```bash
./scripts/docker-run.sh ./scripts/build.sh sim dav-3510

# argv[1]=perm, argv[2]=repeats, argv[3]=nosync (optional)
./scripts/docker-run.sh bash -lc 'cd /workspace && ./build/sim-3510/chained_scatter_simt perm 1'
#   chained_scatter_simt[perm]: PASS (1024 elems x 4 levels)
#   Total tick: 13999

./scripts/docker-run.sh bash -lc 'cd /workspace && ./build/sim-3510/chained_scatter_simt perm 1 nosync'
#   chained_scatter_simt[perm,nosync]: PASS (1024 elems x 4 levels)
#   Total tick: 9259

./scripts/docker-run.sh bash -lc 'cd /workspace && ./build/sim-3510/chained_scatter_simd perm 1'
#   chained_scatter_simd[perm]: PASS (1024 elems x 4 levels)
#   Total tick: 7799
```
