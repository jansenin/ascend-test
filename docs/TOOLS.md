# Debugging And Analysis

## CPU twin debug

CPU mode performs functional emulation and requires no NPU. It is not a timing
or concurrency model.

```bash
./scripts/docker-run.sh ./scripts/test.sh cpu dav-2201
./scripts/docker-run.sh ./scripts/test.sh cpu dav-3510
./scripts/docker-run.sh ./scripts/gdb-cpu.sh dav-3510 add_mmad_add
```

GDB is configured to follow the child process created for the emulated kernel.

## Simulator and traces

```bash
./scripts/docker-run.sh ./scripts/simulate.sh dav-2201 add_mmad_add
./scripts/docker-run.sh ./scripts/simulate.sh dav-3510 add_mmad_add
```

Override the installed model spelling when necessary:

```bash
SOC_VERSION=Ascend910B4 ./scripts/docker-run.sh ./scripts/simulate.sh dav-2201 add_mmad_add
```

Open `trace.json` in `chrome://tracing`. Import `visualize_data.bin` into
MindStudio Insight for source correlation and richer views. Locate supported
instruction-level CSV output with:

```bash
./scripts/docker-run.sh ./scripts/instructions.sh out/simulator/2201/<run>
```

Simulator cycles are estimates, not hardware performance measurements.

Do not set `ASCEND_WORK_PATH` or `ASCEND_DUMP_PATH` around simulator runs with
CANN 9.2.0-beta.2. Those optional variables activate an early dump callback
whose runtime initialization crashes before `main()`. `simulate.sh` unsets
both variables and uses `msprof --output` for artifacts.

## Embedded device ELF

```bash
./scripts/docker-run.sh ./scripts/extract-elf.sh build/sim-3510/add_mmad_add
```

`msobjdump` lists and extracts embedded AI Core ELF objects. Huawei does not
currently document `bisheng -S` or generic `llvm-objdump -d` as a stable AI
Core disassembly workflow. The simulator's `*_instr_exe.csv` is the supported
instruction view.

## NPU-only tools

Build sanitizer instrumentation without `-O0`:

```bash
./scripts/docker-run.sh ./scripts/build.sh npu dav-2201 -DASCENDC_SANITIZER=ON
./scripts/sanitize-npu.sh memcheck build/npu-2201/add_mmad_add
```

Real-device commands require mounted Ascend driver devices:

```bash
./scripts/profile-npu.sh build/npu-2201/add_mmad_add --aic-metrics=Memory,MemoryL0
./scripts/sanitize-npu.sh racecheck build/npu-2201/add_mmad_add
```

Current Ascend 950 documentation does not support `initcheck` or `synccheck`.
Hardware profiling and sanitizer scripts fail clearly when no NPU is present.
