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
- **"Total tick" is not comparable across architectures.** `Ascend910B1`
  (dav-2201) and `Ascend950PR_9599` (dav-3510) are different CA-models with
  their own cycle accounting, so a higher tick on 3510 does not
  mean 950 is slower. Only compare tick within one SoC model. (We almost wrote
  a "950 is heavier because RegBase/MIX-sync" explanation for a cross-arch tick
  gap that also showed up in a plain `vector_add` — the gap is the model, not
  the microarchitecture.)
- **The cross-arch tick gap is NOT clock frequency — it is higher modeled
  memory/DMA latency.** A direct sim run prints
  `[INFO] Chip 0 AIC / Scheduler / Soc periods: 200.0000 / 200.0000 / 105.0000`
  and that line is *identical* for both `dav-2201` and `dav-3510`; the
  per-instruction `instr_exe.csv` also shows the same ~1.8 GHz. `vector_add` is
  ~95% data movement: on 3510 the DMA is GM→UB reads spanning ~1.4 µs + UB→GM
  write ~0.45 µs, while the entire RegBase compute is a single `VF` block of
  ~96 ns (~170 cyc) — the same order as 2201's MemBase `VADD` (156 cyc), so the
  RegBase register staging (`RV_VLDI`/`RV_VADD`/`RV_VSTI`) adds no meaningful
  compute time. The 950 model simply models higher memory/DMA latency (total
  span 1.99 µs vs 2201's 0.86 µs ≈ 2.3x). Also note msprof "Total tick" is a
  poor cross-arch comparator: it includes ~3000 cyc of near-identical model
  init/teardown, so it showed 1.08x while the real kernel latency is 1.72x.
  There is no readable device-characteristics file with the frequency:
  `libPowerModel.so` only embeds field *names* (`aicFreq`/`aivFreq`/`socFreq`/
  ...); the values are compiled into the binaries, and
  `ascend_system_advisor/asys/common/device.py` reads frequency from live
  hardware via DSMI (not the simulator).
- **Measure spans, not summed per-call cycles.** In `instr_exe.csv`/`trace.json`
  the `cycles` column for a `call_count=N` loop instruction (e.g. `RV_VLDI`
  call_count=64) is the SUM of all N iterations' latencies; the vector pipe
  pipelines them, so summing over-counts hugely (we said "RegBase add ≈ 2592
  cyc" when the real `VF` span is ~96 ns ≈ 170 cyc — ~15x off). Take the FIRST
  occurrence → LAST occurrence span of the instruction group instead, or use the
  enclosing `VF` block in the trace.
- **Single-pass benchmarks are dominated by launch/prologue overhead.** Fitting
  `T(k) = F + k·W` over a `kRepeats ∈ {1,2,4,8,16}` sweep separates fixed cost
  F from per-pass work W. Example: chained gather "SIMD wins 13%" at k=1 was
  actually F_diff=741 ticks (SIMT's 128-thread block setup) — steady-state W was
  ~equal (6023 vs 6075). **Always amortize before concluding.**
- **A naive per-tile latency comparison overstates a DMA bottleneck.** In the
  cube sweep we first claimed "MTE2 (GM→L1) 2045 cyc > MMAD 1049 cyc, so the A
  stream is a 2x bottleneck". The sweep data disproved it: half/bf16/int8 already
  hit ratio 1.00, because the per-tile MTE2 transfer is **hidden by the 2-tile
  double-buffer** (the MTE2 for tile *t+1* overlaps MMAD *t*). Always account for
  pipelining/double-buffer slack and verify against the actual MMAD issue
  interval before concluding a data-movement pipe is the limiter.
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

## Cube / MMAD

- **On-core allocators do NOT bounds-check.** `LocalMemAllocator<Hardware::L0A>`
  (and L0B/L0C) silently wrap/overflow when you request more than the buffer
  holds — no crash, just garbage output. This bit us: a float A tile of
  256·64·4 = 64 KB was allocated twice (double-buffered) into a 64 KB L0A, and
  the result was a "wrong answer" (maxErr 6.9) that looked like a dtype bug but
  was really a silent overflow. **Always add host-side size guards** to cube
  kernels: `m·k·sizeof(T) ≤ L0A/2` (double-buffered A), `k·n·sizeof(T) ≤ L0B`,
  `m·n·sizeof(CT) ≤ L0C`.
- **`__NPU_ARCH__` is NOT defined in host code** (only device code). To make an
  arch-dependent constant visible to the host, pass it via CMake
  `target_compile_definitions(... ASCENDC_L0C_CAP_BYTES=262144)` (bisheng is
  clang-based and accepts `-D`), not `#if __NPU_ARCH__`.
- **L0 buffer sizes**: L0A = L0B = 64 KB (both archs); L0C = 128 KB (dav-2201)
  / 256 KB (dav-3510).
- **`LoadData` transpose support differs by arch**: on dav-2201
  `ifTranspose=true` only supports b16 (half/bfloat16) — float/int8 MUST store
  B transposed `[N,K]` and load with `ifTranspose=false`. On dav-3510
  `ifTranspose=true` supports b4/b8/b16/b32 but b8 needs `mStep` a multiple of
  2 (K a multiple of 32). Storing B transposed + `ifTranspose=false` works for
  all 4 dtypes on both archs — the official `matmul_basic_api_high_performance`
  uses this (`IS_B_TRANSPOSE=true`).
- **LoadData kStep/repeatTimes units are dtype-dependent**: K₀ = 32/sizeof(T)
  (half=16, float=8, int8=32, bfloat16=16). `kStep` (3510) and `repeatTimes`
  (2201) are in units of K₀; the source offset stride is `512/sizeof(T)`
  elements. mStep/srcStride/dstStride stay in 16-element M/N fractals
  (dtype-independent).
- **When A and B share L1 (manual byte offsets, A overwriting B's transient
  space), you MUST sync MTE1→MTE2 across the hand-off.** The A `DataCopy`
  (MTE2 pipe) will happily overwrite B's L1 region while `LoadData` (MTE1 pipe)
  is still reading it — `WaitFlag<MTE1_M>` only blocks the Cube (M) pipe, not
  MTE2. Symptom: wrong results for small M (m=16/m=32) on dav-3510 only,
  because for small M the A-tiles fill more of B's L1 footprint. Fix:
  `SetFlag<HardEvent::MTE1_MTE2>(id)` right after `LoadBTile`, then
  `WaitFlag<HardEvent::MTE1_MTE2>(id)` before the A `DataCopy`. (`MTE1_MTE2` is
  the "reverse" flag: MTE1 signals done reading L1, MTE2 waits before
  overwriting.) Isolated with a minimal single-MMAD repro that swapped the
  allocator-based L1 (a1,b1 separate → PASS) for the manual byte-offset layout
  (a1,b1 overlapping → FAIL), then confirmed the missing sync.
