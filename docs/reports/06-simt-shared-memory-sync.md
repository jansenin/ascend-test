# Report 6 — SIMT shared-memory barriers are not optional

## What we did

Took the SIMT chained-gather kernel (`chained_gather_simt`) and made the
`asc_syncthreads()` barriers between gather levels optional (a `kSync` template
flag + `argv[3]=nosync`), then ran the permutation and random index variants
with and without barriers.

## Why

A reasonable-looking intuition: in the *permutation* case each thread's index
is unique, so — unlike the random case — nobody "collides" on a shared-memory
slot, and the barriers might be droppable. The point was to test that idea
directly rather than reason about it in prose.

## What we wanted to check

Is the barrier only needed for *repeating* (random) indices, or also for a
bijection (permutation)?

## Result

**Barriers are required in both cases.** Without them the kernel fails with
`mismatch at 0: expected 10.5, got 0` — the "got 0" is a read of shared memory
*before* the producing thread's write became visible (a data race).

| variant | sync | result | Total tick |
|---|---|---|---|
| perm | yes | PASS | 8982 |
| perm | no | FAIL | 8100 |
| random | yes | PASS | 8989 |
| random | no | FAIL | 8100 |

Why the permutation case is no different: `smem[1][pos] = smem[0][idx]` reads
slot `idx = index[pos]`, which is a *different* thread's slot whenever `idx !=
pos`. A permutation is a bijection, not the identity, so almost every read is
cross-thread and needs the block-wide barrier to make the other thread's write
visible. The barrier is about *visibility across threads*, not about write
collisions.

Two side notes worth keeping:

- Dropping the barriers is ~10% faster (8100 vs 8982 ticks), but produces
  garbage — a classic "fast and wrong" trap.
- The CA-model simulator **did** catch this race (it did not serialize warps in
  a way that masked it), but do not take that as a guarantee that it catches
  every race on real hardware.

## Reproduce

```bash
./scripts/docker-run.sh ./scripts/build.sh sim dav-3510

# argv[1]=perm|random, argv[2]=repeats, argv[3]=nosync (optional)
./scripts/docker-run.sh bash -lc 'cd /workspace && ./build/sim-3510/chained_gather_simt perm 1'
#   Total tick: 8982
#   chained_gather_simt[perm]: PASS (1024 elems x 4 levels)

./scripts/docker-run.sh bash -lc 'cd /workspace && ./build/sim-3510/chained_gather_simt perm 1 nosync'
#   chained_gather_simt[perm] mismatch at 0: expected 10.5, got 0
#   chained_gather_simt[perm,nosync]: FAIL (1024 elems x 4 levels)
#   Total tick: 8100
```
