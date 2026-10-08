# LESSONS.md — mistakes, API gotchas, and corrected claims

The point of this repo is to learn on past mistakes. Every non-obvious API
behavior, wrong assumption, and later-corrected claim belongs here, so future
sessions (human or agent) don't rediscover them. Entries are grouped by theme
and written as terse, self-contained notes.

---

## Data movement: offset units differ by API layer

- **Basic API (LocalTensor) `AscendC::Gather` / `Scatter`** take the
  offset/index tensors in **BYTE addresses**, not element indices. We burned a
  bug on this: passing element index `4095` for float data is interpreted as
  byte `4095` → element `1023`. Multiply element index by `sizeof(T)`.
- **RegBase `AscendC::Reg::Gather` (vgather2) / `Scatter` (vscatter) /
  `Gather` (vselr)** use **ELEMENT indices** (uint32 for 4-byte data), index
  range is the whole UB buffer (chunk for >64 elements). Two different
  conventions in two API layers — always check which one you are in.

## FP16 conversion on the host

- `aclFloatToFloat16` / `aclFloat16ToFloat` do a **numeric cast** (`float` →
  `uint16_t`), NOT an IEEE-754 binary16 bit conversion. Host `1.0f` becomes
  `0x0001`, which device `half` reads as a subnormal → silently zero output
  (this was the "MMAD returns zeros" bug). Use the manual bit-conversion
  helpers (`include/half_utils.h`: `lab::F16` / `lab::F32`).
- `_Float16` is not usable for the device target (BiSheng rejects it); do the
  bit math yourself and `memcpy`.

## RegBase (dav-3510) API quirks

- **`AscendC::GetSpr<SpecialPurposeReg::AR>()` is `__aicore__`-only** — it
  cannot be called inside a `__simd_vf__` function (build error "simd_vf can
  only call simd_callee"). `AscendC::Reg::ClearSpr<AR>()` **is**
  `__simd_callee__` (callable from a VF). Read the running compaction count in
  the `__global__ __vector__` body, between `asc_vf_call`s.
- `GetSpr<AR>()` returns a **BYTE count**; divide by `sizeof(T)` for the
  element count.
- **`Reg::Arange<T>` does not support `uint32_t`** (int8/16/32, float, half,
  int64 only). We precompute position vectors on the host instead.
- **`Squeeze` vs `Unsqueeze` naming is misleading**: `Squeeze` (vsqz) compacts
  **data** (float supported); `Unsqueeze` (vusqz) computes an **exclusive
  prefix-sum of the mask** (int-only, `dst[i]=popcount(mask[0..i-1])`) and does
  NOT move data. There is no direct "expand data" register op — expansion is
  `Unsqueeze` (positions) + `Scatter`.
- **`AR` (SPR 74) is a single shared counter**: two `Squeeze<STORE_REG>` +
  `StoreUnAlign` pairs cannot be interleaved in one loop (the counter would
  double-advance). Do one compaction pass, then use hardware gather/scatter.
- `Squeeze<STORE_REG>` writes the cumulative valid count to AR; `StoreUnAlign`
  (vstur) tracks its **own** output offset via the `UnalignRegForStore` (a
  `vector_align`) register, and `StoreUnAlignPost` finalizes.
- `Reg::Select(dst, src0, src1, mask)`: mask bit=1 → src0, bit=0 → src1 (merge:
  unselected lanes keep value). `Reg::Compares<T,CMPMODE::LT|GT|...>` sets
  bit=1 where the comparison is true.
- `LocalTensor<T>` has a default constructor, so `LocalTensor<T> arr[4];` then
  assign from the allocator is fine.

## Synchronization

- **On Ascend 950 (dav-3510) the PIPE_V↔PIPE_V RAW hazard is resolved by
  hardware** (the docs' phrase is "硬件保证的同步" / hardware-guaranteed single
  pipeline sync). You do NOT need `PipeBarrier<PIPE_V>` between dependent vector
  instructions. On dav-2201 the BiSheng compiler inserts them (`cce-auto-sync`).
  Cross-pipe (DMA↔vector) sync — `SetFlag/WaitFlag<MTE2_V>`, `<V_MTE3>` — is
  still required on both.
- **"Scoreboard" is not the official term.** We used it informally to explain
  *how* the hardware resolves the hazard. The docs never name it; say
  "hardware-guaranteed in-order-issue / pipelined-execution" and cite
  `key_features.md` (硬件保证的同步) + `intra_core_sync_overview.md`
  (in-order issue + overlapped execution) + `basic_architecture.md` (Scalar
  dispatches to independent Vector/Cube/MTE queues).
- **SIMT `asc_syncthreads()` is required even for a permutation index**, not
  just random. Each gather level reads `smem[level][idx]` where `idx=index[pos]`
  is another thread's slot (`idx != pos` in a permutation), so the write is
  cross-thread and needs a block-wide barrier. Removing barriers **FAILed** in
  the simulator ("expected X, got 0") for BOTH perm and random — see
  `docs/reports/06-simt-shared-memory-sync.md`.
- **Don't hand-optimize around a hazard the hardware already hides.** A
  software-pipelined SIMD chained gather (diagonal schedule, 4x buffers) was
  ~5% *slower* than the naive version, with an identical instruction histogram
  — the hardware vector pipe already overlapped the dependent `vgather2`s, and
  the pipeline's extra flags/DMA ping-pong added overhead.

## Measurement methodology

- **"Total tick" is a simulator model metric, not wall time or real hardware.**
  Use it for relative A/B within the same simulator config, not absolute
  throughput.
- **Single-pass benchmarks are dominated by launch/prologue overhead.** Fitting
  `T(k) = F + k·W` over a `kRepeats ∈ {1,2,4,8,16}` sweep separates fixed cost
  F from per-pass work W. Example: chained gather "SIMD wins 13%" at k=1 was
  actually F_diff=741 ticks (SIMT's 128-thread block setup) — steady-state W was
  ~equal (6023 vs 6075). **Always amortize before concluding.**
- **SIMT msprof produces empty data** (no `trace.json`/`visualize_data.bin`);
  the only SIMT instruction trace is the simulator's `core*.instr_log.dump`.
- The CA-model simulator *can* catch some races (it caught the shared-memory
  race above), but never treat it as authoritative for real-hardware races or
  timing.

## SIMD vs SIMT (corrected mental model)

- **SIMT is warp-level SIMD**, not per-thread scalar. SIMT instructions carry
  `[warpId]`/`[execMask:ffffffff]` (32-lane warps). The real differences are:
  vector width (SIMD RegBase fp32 = 64 lanes vs SIMT warp = 32), the raw-pointer
  memory model (SIMT pays per-access 64-bit address math), and thread-loop
  predicates/branches. SIMT adds DCache + 4 warp schedulers + a register file on
  top of the shared ALU; official docs frame it as "SIMD primary, SIMT
  auxiliary" (>90% compute is SIMD/cube).
- **Corrected claim:** early on we might have framed SIMT gather as "close to
  SIMD". Measured truth: *independent* gather SIMD is ~5x faster (hardware
  `RV_VGATHER2`, 64 elems/instr); *chained/dependent* gather is a tie; *dense
  arithmetic* SIMD ~3x; *divergent branch* (rare `if`) naive-SIMD loses to SIMT
  ~1.9x, but a compacted SIMD (gather→operate→scatter) beats both.

## Tooling gotchas

- **No public HiIPU disassembler**: `llvm-objdump` has a `hiipu64` target but
  prints `<not available>` for every instruction. Real instruction listings come
  from the simulator `core*.veccore*.instr_log.dump` (ASCII) and, for SIMD only,
  CPU-debug `.cce` files.
- **`.cce` files are emitted at RUNTIME by CPU twin-debug** (`libcpudebug_cceprint`),
  not at compile time. `--cce-enable-print` produces nothing standalone. SIMT
  has no CPU-debug mode → no `.cce` for SIMT.
- **Simulator segfault before `main()`** = CANN 9.2.0-beta.2 `libascend_dump`
  static-init-order bug, triggered by setting `ASCEND_WORK_PATH` or
  `ASCEND_DUMP_PATH`. Unset both (`env -u ...`); `scripts/simulate.sh` already
  does this. Use `msprof --output` instead of `ASCEND_WORK_PATH`.
- **Docker entrypoint `set -u` breaks Huawei `set_env.sh`** (unbound-variable
  warnings). Wrap the `source` in `set +u` / `set -u`.
- **CANN `.run` installer needs `python3-pip`** — the `llm_datadist` wheel
  install fails with "pip3 not installed" otherwise. `python3-venv` alone does
  not provide pip on Ubuntu 24.04.
- **`CMAKE_ASC_RUN_MODE` must be set before `project()`** and never re-used
  across run modes/architectures (fresh `build/{mode}-{arch}` each time).

## SIMD vs SIMT header exclusivity

- SIMT files (`--enable-simt`) MUST NOT include `kernel_operator.h`
  (typedef redefinition with the SIMT `half`/builtin types). SIMD files must not
  include `simt_api/asc_simt.h`. They are mutually exclusive at compile time.
- `include/half_utils.h` was created to be include-able by **both** (no
  `kernel_operator.h` / no `simt_api` dependency), for host-side fp16 bit math.
