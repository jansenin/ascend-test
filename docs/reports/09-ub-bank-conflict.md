# 09 — UB memory-bank conflict: dense vs 128-byte-gap operand placement

## What we did

Built `apps/bank_add.asc`, a vector-add kernel that performs **16 independent
adds of the same two 1024-float inputs** (`dst[i] = lhs + rhs` for `i` in
0..15), and measured **only the compute interval** — the first-ADD-issue cycle
to the last-ADD-issue cycle, exactly the metric the cube MMAD sweep uses. The
single thing that varies between the two cases is the UB placement of the
operand/output blocks:

* **dense** — blocks packed back-to-back: `lhs@0`, `rhs@4096`,
  `dst[i]@(2+i)·4096` (all byte offsets, 32 B aligned).
* **sparse** — 128 bytes of empty space between blocks: `lhs@0`, `rhs@4224`,
  `dst[i]@(2+i)·4224`.

The kernel is MemBase only (`AscendC::LocalTensor` + `AscendC::Add`, no RegBase
code). `scripts/bank_sweep.py` runs each mode `--repeats` times, parses
`core0.veccore0.instr_log.dump`, greps the add instruction, and reports
`interval = (last − first) / (count − 1)`.

## Why we did it

The Unified Buffer (UB) is organized as interleaved **banks**, and two
simultaneous accesses to the same bank / bank group serialize. We wanted to
measure that overhead directly: does spreading operands 128 bytes apart change
vector-add throughput vs. packing them back-to-back?

## What we wanted to check

1. Is there a measurable bank-conflict penalty between the dense and sparse
   layouts, and how big?
2. Is the CA-model simulator modelling bank conflicts at all?
3. Is "256 bytes = a full bank group" the right unit to reason with?

### Result: no measurable bank-conflict penalty

| arch | dense (conflict) | sparse (no conflict) | Δ |
|---|---|---|---|
| dav-2201 | 54.87 cyc/VADD | 54.20 cyc/VADD | +0.67 (1.2%) |
| dav-3510 | 2.29 cyc/RV_VADD | 2.61 cyc/RV_VADD | −0.32 (dense *faster*) |

Each figure is perfectly reproducible (3 runs, min = mean = max). The deltas are
~1% and, on 3510, even point the *wrong* way for a bank-conflict story. The
dense layout genuinely does collide (see below) yet costs nothing measurable.

### The bank structure (authoritative, from the vendor docs)

Two vendor docs disagree with the "256 bytes = a full bank group" assumption.
From `Vector_logical_arch.md` and the `avoid_bank_conflict_*` guides:

* **dav-2201** (910B / A2 / A3): UB = 48 banks, 16 bank groups, **3 banks per
  group**, each bank 4 KB = 128 rows × 32 B. `bank = (addr/32) % 48`,
  `bank_group = (addr/32) % 16`, so a group's banks are 16 apart (bank *g*,
  *g*+16, *g*+32). **Bank-group period = 512 B** (16 rows × 32 B); same-bank
  period = 1536 B. Conflicts: read/write same bank; write/write same group;
  read/read same group.
* **dav-3510** (950): UB = 8 groups, 2 banks per group, each bank 16 KB = 512
  rows × 32 B. Address encoding `UB_ADDR = {BANK_DEPTH[9], BANK[1], BG[3],
  BANK_WIDTH[5]}`. **Bank-group period = 256 B**, same-bank period = 512 B.
  Conflicts: read/write same bank; write/write same group; read/read two reads
  same bank or ≥3 reads same group.

So **"256 bytes = a full bank group" is correct for 3510 but wrong for 2201**,
where a bank-group cycle is 512 bytes (and a single bank cycle is 1536 bytes).

The dense layout *does* collide on 2201: `lhs@0 → bank 0 (group 0)`,
`rhs@4096 → bank 32 (group 0)`, `dst@8192 → bank 16 (group 0)` — all three
operands in group 0, so the two reads (`lhs`,`rhs`) hit the read/read-conflict
condition. The sparse layout separates them into groups 0 / 4 / 8. Yet the issue
interval barely moves.

### Why 3510 is measuring register throughput, not banks

This is the real surprise of the experiment. On dav-2201 the add is a true
**memory-to-memory** instruction — `VADD XD=0x2000, XN=0, XM=0x1000`, operand
fields are UB byte addresses, one instruction processes all 1024 elements via
its repeat field (16 VADD total). On dav-3510 the *same* MemBase
`AscendC::Add` call compiles to **register-based** `RV_VADD`:

```
RV_VADD Dtype:F32  Vd[0], Vn[0], Vm[1], Pg[1]      (256 of them)
```

The operands are register-file vectors, not UB addresses. Data reaches the
registers through separate `VLD`/`VST` (load/store) instructions, so the
**compute interval is register-only and never touches UB banks**. "Don't use reg
programming yet" is impossible on 3510 — the MemBase `Add` *is* reg programming
under the hood; only 2201 has a genuine MemBase `VADD`.

### Conclusion

The CA-model simulator does **not** model UB bank conflicts for the vector add
path (or the effect is sub-cycle and lost). On 2201 the add is UB-bandwidth
bound at ~224 B/cycle regardless of placement (12288 B moved per 1024-element
add ÷ 54.87 cyc), i.e. the simulator treats UB as flat bandwidth, not banks. To
actually observe bank behaviour one would need (a) a strided/`Repeat`-parameter
access that keeps 8 DataBlocks inside one group — the documented "8-beat"
write/write case — and (b) an architecture where the compute touches UB
directly (2201). On 3510, bank conflicts live in `VLD`/`VST`, not in the compute
stream.

## Reproduce

```bash
# Build the kernel for both architectures.
./scripts/docker-run.sh ./scripts/build.sh sim dav-2201
./scripts/docker-run.sh ./scripts/build.sh sim dav-3510

# Sweep both layouts; each mode is run 3x and the VADD issue interval is parsed
# from core0.veccore0.instr_log.dump (first->last issue / (count-1)).
./scripts/docker-run.sh python3 /workspace/scripts/bank_sweep.py --arch 2201 --repeats 3
#   arch=2201 binary=/workspace/build/sim-2201/bank_add repeats=3
#   dense  vadd_count=16  interval_cyc min=54.87 mean=54.87 max=54.87  ticks=[3373, 3386, 3271]
#   sparse vadd_count=16  interval_cyc min=54.20 mean=54.20 max=54.20  ticks=[3340, 3316, 3209]

./scripts/docker-run.sh python3 /workspace/scripts/bank_sweep.py --arch 3510 --repeats 3
#   arch=3510 binary=/workspace/build/sim-3510/bank_add repeats=3
#   dense  vadd_count=256 interval_cyc min=2.29 mean=2.29 max=2.29  ticks=[6096, 6090, 6097]
#   sparse vadd_count=256 interval_cyc min=2.61 mean=2.61 max=2.61  ticks=[6170, 6173, 6173]

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
