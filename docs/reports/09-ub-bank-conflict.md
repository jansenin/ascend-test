# 09 — UB memory-bank conflict: operand placement and strided access

## What we did

Built two vector-add kernels that perform **16 independent adds of the same two
1024-float inputs** (`dst[i] = lhs + rhs` for `i` in 0..15) and measured **only
the compute interval** — the first-ADD-issue cycle to the last-ADD-issue cycle,
exactly the metric the cube MMAD sweep uses. The single thing that varies is the
UB placement/access pattern of the operands:

* `apps/bank_add.asc` — **contiguous blocks with a controllable gap**. Layout
  (byte offsets, 32 B aligned): `lhs@0`, `rhs@4096 + rhsGapBytes`,
  `dst[i]@16384 + dstGapBytes + i·4096`. `kBlock*4 = 4096` B is a multiple of
  the 512-B group period, so `rhsGapBytes`/`dstGapBytes` (both `< 512 B`) set
  each operand's bank-group phase. Gaps are passed as runtime bytes: argv[1] =
  rhs gap (`"dense"` → 0), argv[2] = dst gap.
* `apps/bank_stride.asc` — **strided access** using the `BinaryRepeatParams`
  `srcBlkStride` sweep: `mask = 64` fp32 (= 256 B = 8 DataBlocks of 32 B),
  `repeatTime = 1`. This is the vendor doc's canonical "8 DataBlocks in one bank
  group → 8 beats" conflict case, and is the *definitive* way to expose the
  documented banking.

Both are MemBase only (`AscendC::LocalTensor` + `AscendC::Add`, no RegBase
code). `scripts/bank_sweep.py` drives `bank_add` across a `--gaps` list, parses
`core0.veccore0.instr_log.dump`, greps the add instruction, and reports
`interval = (last − first) / (count − 1)`.

## Why we did it

The Unified Buffer (UB) is organized as interleaved **banks**, and two
simultaneous accesses to the same bank / bank group serialize. We wanted to
measure that overhead directly: does operand placement (gap size) and access
stride change vector-add throughput?

## What we wanted to check

1. Is there a measurable bank-conflict penalty, and how big?
2. Is the CA-model simulator modelling bank conflicts at all?
3. Is "256 bytes = a full bank group" the right unit to reason with?

The answer to all three turned out to be "yes — but only once the access pattern
actually collides". The first test (dense vs 128-byte gap) picked a
**non-de-conflicting** offset, which is why it showed nothing. See below.

### Result 1 — dense vs 128-byte gap: no effect (the offset was wrong)

| arch | dense (gap 0) | sparse (gap 128 B) | Δ |
|---|---|---|---|
| dav-2201 | 54.87 cyc/VADD | 54.20 cyc/VADD | +0.67 (1.2%) |
| dav-3510 | 2.29 cyc/RV_VADD | 2.61 cyc/RV_VADD | −0.32 (dense *faster*) |

Each figure is perfectly reproducible (3 runs, min = mean = max). At first
glance this looked like "no bank effect, UB is flat bandwidth". It is not — a
128-byte gap leaves the source operands' 8-group read windows still overlapping
(see below), so this layout *does not de-conflict* and no delta was expected.

### Result 2 — gap sweep (2201): only a 256-byte gap is fast

Sweeping `rhsGapBytes` in 32-byte steps shows a single sharp minimum:

| gap (B) | VADD interval (cyc) |
|---|---|
| 0 | 54.87 |
| 128 | 54.20 |
| 256 | **38.87** |
| 512 | 54.80 |
| 1024 / 2048 | 54.67 / 54.53 |

Total ticks drop ~8% at gap 256 too (~3050 vs ~3300), so the whole kernel speeds
up, not just the VADD span. A 3-way grid (`rhsGap` × `dstGap` ∈ {0,128,256,384})
confirms **only `rhsGap` matters** — `dstGap` has zero effect, because the output
write is beat-separated from the reads (read/write conflict never fires). A
64-KB split (`lhs@0`, `rhs@65536`, `dst@131072`) also does **not** de-conflict:
`65536/32 = 2048 ≡ 0 (mod 16)` and `131072/32 = 4096 ≡ 0 (mod 16)`, so both land
back in group 0 — the 32-byte interleave wraps every 512 B and a 64-KB region
just threads all 48 banks ~42×.

Why only 256 B: a repeat reads 8 consecutive DataBlocks = 8 consecutive bank
groups (a "window" of 8 groups). Two operands' windows **overlap** unless the
offset is 256 B (mod 512 B), which slides `rhs`'s window from groups {0..7} to
{8..15} — disjoint from `lhs`'s {0..7}. A 128-byte gap gives {4..11}, which still
overlaps.

### Result 3 — strided sweep (2201): clean, monotonic bank scaling

| srcBlkStride | distinct groups | beats | VADD interval (cyc) |
|---|---|---|---|
| 1 (contiguous) | 8 | 1 | 24.0 |
| 2 | 8 | 1 | 24.0 |
| 4 | 4 | 2 | 26.0 |
| 8 | 2 | 4 | 30.0 |
| 16 | 1 | 8 | 38.0 |

`interval ≈ 24 + 2·(beats − 1)`, and beats = 8 / distinct_groups — exactly the
vendor doc's model ("a repeat's 8 DataBlocks spread over *N* groups costs *N*
beats"). The operand addresses are **identical** across all strides (only the
`XT` repeat-encoding field changes), so this cleanly separates the bank effect
from codegen or launch overhead. This is the definitive proof that the CA-model
simulator **does** model UB banking on 2201.

### Result 4 — 3510: small effect, and it lives in VLD/VST, not compute

On 3510 the same MemBase `Add` compiles to a register machine (`RV_VLD` +
`RV_VADD` + `RV_VST`), so the compute stream never touches UB banks; banking
shows up only in the load/store span. The contiguous gap sweep shows a tiny
"one repeat" optimum — gap 256 B fastest, gap 128 B slowest (~570 vs ~666 cycle
span, ~1.5%). The strided read compiles to `RV_VSLDB` (register shuffle, no
`RV_VLD`): RV_VADD interval s=1/2/4/8/16 → 53/57/65/65/65 cyc (saturates at
s=4, ~22%).

## The bank structure (authoritative, from the vendor docs)

Two vendor docs disagree with the "256 bytes = a full bank group" assumption.
From `Vector_logical_arch.md` and the `avoid_bank_conflict_*` guides:

* **dav-2201** (910B / A2 / A3): UB = 48 banks = 3 regions × 16 bank groups,
  **3 banks per group**, each bank 4 KB = 128 rows × 32 B. Bank id =
  `region·16 + group`, where `region = addr[17:16]` (the 0/1/2 axis — which
  64-KB block) and `group = (addr/32) % 16` (`addr[8:5]`). So a group's banks
  are 16 apart (bank *g*, *g*+16, *g*+32) and live 64 KB apart (one per region).
  **Bank-group period = 512 B** (16 rows × 32 B); the same bank recurs every
  512 B within a 64-KB region. Conflicts: read/write same bank; write/write same
  group; read/read same group.
* **dav-3510** (950): UB = 8 groups, 2 banks per group, each bank 16 KB = 512
  rows × 32 B. Address encoding `UB_ADDR = {BANK_DEPTH[9], BANK[1], BG[3],
  BANK_WIDTH[5]}`. **Bank-group period = 256 B**, same-bank period = 512 B.
  Conflicts: read/write same bank; write/write same group; read/read two reads
  same bank or ≥3 reads same group.

So **"256 bytes = a full bank group" is correct for 3510 but wrong for 2201**,
where a bank-group cycle is 512 bytes.

## Why 3510 is measuring register throughput, not banks

On dav-2201 the add is a true **memory-to-memory** instruction — `VADD
XD=0x2000, XN=0, XM=0x1000`, operand fields are UB byte addresses, one
instruction processes all 1024 elements via its repeat field (16 VADD total). On
dav-3510 the *same* MemBase `AscendC::Add` call compiles to **register-based**
`RV_VADD`:

```
RV_VADD Dtype:F32  Vd[0], Vn[0], Vm[1], Pg[1]      (256 of them)
```

The operands are register-file vectors, not UB addresses. Data reaches the
registers through separate `VLD`/`VST` (load/store) instructions, so the
**compute interval is register-only and never touches UB banks**. "Don't use reg
programming yet" is impossible on 3510 — the MemBase `Add` *is* reg programming
under the hood; only 2201 has a genuine MemBase `VADD`.

## Conclusion

The CA-model simulator **does** model UB bank conflicts — on 2201 the strided
sweep (24 → 38 cyc, matching the documented "8 DataBlocks in one group = 8
beats") and the gap sweep (only a 256-byte offset de-conflicts the two read
windows, 54.87 → 38.87 cyc) both show real, address-dependent bank behaviour.
The original dense-vs-128-byte-gap result was a **non-de-conflicting offset**, not
evidence of flat bandwidth. On 3510 the effect is small (~1.5%) and lives in the
`VLD`/`VST` stream, not the `RV_VADD` compute stream, because the MemBase `Add`
is a register machine there.

## Reproduce

```bash
# Build both kernels for both architectures.
./scripts/docker-run.sh ./scripts/build.sh sim dav-2201
./scripts/docker-run.sh ./scripts/build.sh sim dav-3510

# Gap sweep (bank_add): sweeps rhsGapBytes; dstGapBytes stays 0. The vadd_cyc
# column is the VADD issue interval (last-first)/(count-1); vldi_cyc prints nan
# unless the log contains RV_VLDI.
./scripts/docker-run.sh python3 /workspace/scripts/bank_sweep.py --arch 2201 --gaps 0,128,256,512 --repeats 3
#   arch=2201 binary=/workspace/build/sim-2201/bank_add repeats=3
#     gap_B  vadd_cyc  vldi_cyc  ticks
#         0     54.87       nan   [3373,3386,3271]  (vadd_count=16)
#       128     54.20       nan   [...]
#       256     38.87       nan   [...]             # <-- de-conflicted (fast)
#       512     54.80       nan   [...]

./scripts/docker-run.sh python3 /workspace/scripts/bank_sweep.py --arch 3510 --gaps 0,128,256,512 --repeats 3
#   arch=3510 binary=/workspace/build/sim-3510/bank_add repeats=3
#     gap_B  vadd_cyc  vldi_cyc  ticks
#         0      2.29       nan   [6096,6090,6097]  (vadd_count=256)
#       128      2.61       nan   [...]
#       256      2.34       nan   [...]
#       512      2.37       nan   [...]

# Strided sweep (bank_stride): run each stride, then extract the VADD interval
# (16 VADD -> (last-first)/15) from core0.veccore0.instr_log.dump.
./scripts/docker-run.sh bash -lc 'rm -rf /tmp/b && mkdir -p /tmp/b && cd /tmp/b \
  && for s in 1 2 4 8 16; do /workspace/build/sim-2201/bank_stride $s >/dev/null 2>&1; done'
#   srcBlkStride 1/2/4/8/16  ->  VADD interval 24.0 / 24.0 / 26.0 / 30.0 / 38.0 cyc

# See the 2201 memory-to-memory VADD vs the 3510 register RV_VADD for yourself:
./scripts/docker-run.sh bash -lc 'rm -rf /tmp/b && mkdir -p /tmp/b && cd /tmp/b \
  && /workspace/build/sim-2201/bank_add dense >/dev/null 2>&1 \
  && grep -m2 VADD core0.veccore0.instr_log.dump'
#   [info] [00001533] ... VEC : ... VADD  XD:X4=0x2000, XN:X3=0, XM:X6=0x1000, XT:..., Dtype:F32, Id:67
./scripts/docker-run.sh bash -lc 'rm -rf /tmp/b && mkdir -p /tmp/b && cd /tmp/b \
  && /workspace/build/sim-3510/bank_add dense >/dev/null 2>&1 \
  && grep -m2 VADD core0.veccore0.instr_log.dump'
#   [info] [00002383] ... RVECEX : ... RV_VADD Dtype: F32  Vd[0], Vn[0], Vm[1], Pg[1],
```
