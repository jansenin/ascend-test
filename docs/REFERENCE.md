# Reference — hardware constants, tools, and workflows

Dense quick-reference of facts that were looked up once and are easy to forget.
Long-form explanations live in `ARCHITECTURE.md`, `TOOLS.md`, and `LESSONS.md`.
This file is just the numbers and one-liners.

## Architecture cheat sheet

| target | `--npu-arch` | `__NPU_ARCH__` | product | AIV model | SIMT? | SOC (simulator) |
|---|---|---|---|---|---|---|
| Ascend 910B / Atlas A2/A3 | `dav-2201` | `2201` | 910B, A2, A3 | MemBase (no RegBase) | no | `Ascend910B1` |
| Ascend 950PR / 950DT | `dav-3510` | `3510` | 950 | RegBase (`Reg::*`) | yes | `Ascend950PR_9599` |

- SIMD files `#include "kernel_operator.h"`; SIMT files `#include "simt_api/asc_simt.h"`
  (+ `simt_api/asc_fp16.h` for half). The two are mutually exclusive (typedef clash).
- SIMT is `dav-3510` only, needs `--enable-simt`, has no CPU-debug, and `msprof`
  produces empty data for SIMT.
- `half` / `bfloat16_t` are **global** builtin types (not `AscendC::half`).

## On-chip buffer sizes (bytes)

Authoritative source (per arch):
`vendor-src/asc-devkit/docs/zh/guide/programming_guide/advanced_programming/hardware_implementation/architecture_spec/npu_arch_2201.md`
(lines 45-50) and `.../npu_arch_3510.md` (lines 89-95).

| buffer | dav-2201 | dav-3510 | align |
|---|---|---|---|
| UB | `192*1024 - 256` = 196352 | `248*1024` (+VF_STACK+RESERVE) = 253952 | 32 B |
| L1 | `512*1024 - 256` = 523776 | `512*1024` = 524288 | 32 B |
| L0A | 64 KB | 64 KB | 512 B |
| L0B | 64 KB | 64 KB | 512 B |
| L0C | 128 KB | 256 KB | 64 B |
| BiasTable | 1 KB | 4 KB | 64 B |
| Fixpipe buffer | — | 4 KB | 64 B |

> **The 256-byte reservation is dav-2201 only.** 2201 reserves 256 B in both UB
> and L1 (`ASC_UB_SIZE = 192*1024 - 256`, `ASC_L1_SIZE = 512*1024 - 256`); 3510 has
> none. Consequence for the cube sweep: 16 A-tiles of 32 KB each = 512 KB fits in
> 3510 L1 but overflows 2201 L1 by 256 B, so a handful of the largest `M*K` tiles
> are rejected on 2201 only.

## Cube / MMAD

- MMAD computes `C[M×N] += A[M×K] · B[K×N]`; operands live in L0A / L0B / L0C.
- `K0 = 32 / sizeof(T)` elements per 512-byte fractal row/col: half/bf16=16,
  float=8, int8=32. `E512 = 512/sizeof(T)`.
- Hardware tile is 16×16 (K in units of K0); `MmadParams` m/n/k ≤ 4095.
- dtype → accumulator: half→float, bfloat16→float, float→float, int8→int32.
  Hardware float32 has a 10-bit mantissa (reduced precision).
- LoadData: `kStep` (3510) / `repeatTimes` (2201) are in **K0 units**; source
  offset stride is `E512` elements. `ifTranspose=true` only supports b16 on 2201,
  so store B **transposed** `[N,K]` and load with `ifTranspose=false`.
- Measured Cube peak (single-core CA-model sim, ~1.8 GHz):
  | dtype | MAC/cyc | FLOP/cyc | TFLOPS/TOPS | ratio vs ideal |
  |---|---|---|---|---|
  | half / bf16 | 4096 | 8192 | 14.7 TFLOPS | 1.00 (both archs) |
  | int8 | 8192 | — | 29.5 TOPS | exactly 2× fp16 |
  | float (2201) | 1024 | 2048 | 3.68 TFLOPS | 2.0 |
  | float (3510) | 256 | 512 | 0.92 TFLOPS | 8.0 |
  Ideal interval (cycles) = `(m/16)*(n/16)*(k/K0)`. Small tiles are latency-bound.
  float numbers are the CA-model result and may not match silicon.

## Vector / register / SIMT

- Vector register = **256 bytes** = 64 fp32 / 128 fp16 per instruction.
- SIMT warp = 32 lanes; SIMT executes on the same AIV vector core (warp
  scheduler + SIMT register file + DCache added on top; ALU shared with SIMD).
- dav-2201 is MemBase (GM→UB→compute→GM, no register programming); dav-3510 is
  RegBase (`Reg::LoadAlign`/`Reg::Add`/`Reg::StoreAlign` via `asc_vf_call`).
- On 950, PIPE_V→PIPE_V sync is hardware-guaranteed (no `PipeBarrier<PIPE_V>`
  needed between dependent vector ops); cross-pipe (MTE2_V / V_MTE3) flags are
  still required. On 2201 the BiSheng compiler auto-inserts V→V sync.

## Clock

- Simulator: ~1.8 GHz on both archs (per-instruction `cycles / running_time(us)`).
- `Total tick` from the simulator is a cycle count; frequency only maps cycles to
  wall time and never changes the tick count. Cross-arch tick gaps are NOT
  comparable (different CA-models + cycle accounting).

## Tools (inside the Docker image, `ASCEND_HOME_PATH=/usr/local/Ascend/cann-9.2.0-beta.2`)

- `bisheng` — Ascend C compiler (Clang-derived). `--npu-arch`, `--enable-simt`,
  `--run-mode=cpu|sim`, `-save-temps`, `-g`, `--sanitizer` (NPU only).
- `msobjdump --list-elf|--dump-elf|--extract-elf` — extract device ELF
  (`*.aicore.o`, format `elf64-hiipu`). There is **no public HiIPU disassembler**
  (`llvm-objdump -d` returns `<not available>` for every instruction).
- `msprof op simulator --soc-version=... --output=... <bin>` — trace.json +
  `visualize_data.bin` + `core*_instr_exe.csv`.
- `mssanitizer` / `msopprof` — NPU-hardware-only (correctly fail in the container).
- Simulator dirs: `tools/simulator/dav_2201/lib`, `tools/simulator/dav_3510/lib`,
  `Ascend910B1/`, `Ascend950PR_9599/`, `Ascend950PR_9589/`.

## Workflows (all through `./scripts/docker-run.sh <cmd>`)

```bash
./scripts/docker-run.sh ./scripts/build.sh sim dav-3510     # -> build/sim-3510/
./scripts/docker-run.sh ./scripts/test.sh sim dav-3510      # run the test suite
# run one sim binary directly: prints "Total tick: N" + PASS/FAIL, dumps
# core*.{veccore,cubecore}*.instr_log.dump + profile_*.toml into CWD
./scripts/docker-run.sh bash -lc 'cd /workspace && ./build/sim-3510/cube_peak 256 64 256 half'
./scripts/docker-run.sh ./scripts/simulate.sh dav-3510 vector_add   # msprof trace
```

- Build dirs `build/{cpu|sim|npu}-{2201|3510}`; never reuse a dir across
  mode/arch (`CMAKE_ASC_RUN_MODE`/`CMAKE_ASC_ARCHITECTURES` are cached).
- `simulate.sh` does `env -u ASCEND_WORK_PATH -u ASCEND_DUMP_PATH` (workaround for
  a CANN 9.2.0-beta.2 `libascend_dump` static-init segfault when those are set).

## Simulator core-count (single-core speedup)

The CA-model default models the full chip. To run one core (~9× faster):

```bash
cfg=/usr/local/Ascend/cann-9.2.0-beta.2/tools/simulator/dav_3510/lib/config_stars.json
python3 -c "import json;d=json.load(open('$cfg'));d['model_top']['num_aic']=1;d['model_top']['num_aiv']=2;json.dump(d,open('$cfg','w'),indent=2)"
```

Defaults: dav_2201 = 24 aic/48 aiv, dav_3510 = 32 aic/64 aiv. The patch is read
by `libmodel_top.so` from its fixed lib-dir path (a CWD `config_stars.json` is
ignored). The image is immutable (each `docker run --rm` is a fresh container), so
the patch never persists — **there is nothing to restore**. The patch needs root:
`docker run --rm --user 0:0 ...`.

## API gotchas (see LESSONS.md for full detail)

- `LocalTensor<T>(TPosition pos, uint32_t byteOffset, uint32_t elemCount)` — ctor
  takes a **byte** offset + **element** count; `operator[]` takes element offset.
- Basic-API `AscendC::Gather`/`Scatter` (LocalTensor) use **byte** offsets;
  RegBase `Reg::Gather`/`Scatter`/`Gather(vselr)` use **element** indices.
- `GetSpr<AR>()` is `__aicore__` (returns **byte** count; not callable in VF);
  `ClearSpr<AR>()` is `__simd_callee__`. `Squeeze(vsqz)` compacts data;
  `Unsqueeze(vusqz)` is an int-only exclusive prefix-sum, NOT data movement.
- On-core allocators (`LocalMemAllocator`) do **not** bounds-check: overflowing
  L0A/L0B/L0C silently corrupts output. Always add host-side size guards.
- `__NPU_ARCH__` is undefined in **host** code (only device code) — pass
  arch-dependent constants via CMake `-D` (e.g. `ASCENDC_L0C_CAP_BYTES`).
