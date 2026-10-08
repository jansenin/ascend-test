# Report 2 — SIMT add + instruction inspection

## What we did

Wrote the first SIMT kernel (`simt_add`, a CUDA-like `__global__` float add
compiled with `--enable-simt` for `dav-3510`), then worked out how to actually
read the generated NPU instructions for both SIMD and SIMT.

## Why

The user wanted to know whether SIMT is "just a programming model thing" or
whether it produces genuinely different machine code, and to see the actual NPU
assembler.

## What we wanted to check

1. Whether SIMT compiles and runs in the simulator.
2. How to obtain the real instruction stream (there is no public HiIPU
   disassembler — `llvm-objdump` returns `<not available>` for every
   instruction).
3. Whether the SIMD and SIMT instruction sets differ in kind, not just in count.

## Result

- SIMT runs in simulator mode only (`--enable-simt` + CPU twin-debug fails to
  compile; msprof produces no data for SIMT).
- The only sources of real instructions are:
  - the simulator's `core*.veccore*.instr_log.dump` (both SIMD and SIMT), and
  - CPU-debug `.cce` files (SIMD only, runtime-generated).
- SIMD emits wide vector instructions (`vadd`, `vlds`, `vsts`); SIMT emits
  warp-scoped `SIMT_*` instructions carrying `[warpId]`, `[execMask]`,
  `[prdctMask]` fields.
- Device code size: SIMD `vector_add` `.text` = 0x114 (276 B) vs SIMT
  `simt_add` `.text` = 0x428 (1064 B, ~3.9× larger).

## Reproduce

```bash
./scripts/docker-run.sh ./scripts/build.sh sim dav-3510

# SIMT add runs (simulator).
./scripts/docker-run.sh bash -lc 'cd /workspace && ./build/sim-3510/simt_add'
#   Total tick: 3760
#   simt_add: PASS (8192 elements)

# Extract the device object and check its machine-code size.
./scripts/docker-run.sh bash -lc '
  /workspace/scripts/extract-elf.sh vector_add
  /workspace/scripts/extract-elf.sh simt_add
  ls -l /workspace/out/device-elf/*/*.aicore.o'
#   vector_add.aicore.o  simt_add.aicore.o

# CPU twin-debug emits .cce instruction text (SIMD only). Run the CPU test,
# then list the generated files.
./scripts/docker-run.sh ./scripts/test.sh cpu dav-3510
./scripts/docker-run.sh bash -lc 'find /workspace/build/cpu-3510/cceprint -name "*.cce"'
#   _ZN3lab9AddKernelILj8192EEEvPhS1_S1__0_0_vec.cce   (SIMD vector add)

# Read the SIMD vector-add instruction listing (unrolled vlds/vadd/vsts loop).
./scripts/docker-run.sh bash -lc 'grep -E "vadd|vlds|vsts|copy_gm_to_ubuf" \
  /workspace/build/cpu-3510/cceprint/_ZN3lab9AddKernelILj8192EEEvPhS1_S1__0_0_vec.cce | sort | uniq -c'
#   ... vlds / vadd / vsts ... copy_gm_to_ubuf_align_v2 ...

# The public llvm-objdump cannot decode HiIPU device code.
./scripts/docker-run.sh bash -lc '$ASCEND_HOME_PATH/tools/bisheng_compiler/bin/llvm-objdump -d \
  /workspace/out/device-elf/vector_add/vector_add.aicore.o'
#   ... <not available> ...   (no public HiIPU ISA decoder)
```
