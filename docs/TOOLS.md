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

## Desktop GUI applications

On Linux, `docker-run.sh` automatically forwards the active X11 socket and
Xauthority file, the active Wayland socket, or both. Common X11, Wayland, GTK,
OpenGL, and audio client libraries are installed in the image.

```bash
./scripts/docker-run.sh --gui bash
xeyes
```

`--gui` fails if no usable host display is detected. Automatic mode keeps
headless commands working when no display exists; `--no-gui` explicitly
disables display forwarding. The container runs with the invoking user's UID
and GID rather than as root.

X11 normally works without `xhost` because the host's readable Xauthority file
is mounted read-only. If the desktop does not expose one, authorize only the
local user before starting the container and revoke it afterward:

```bash
xhost +SI:localuser:"$(id -un)"
./scripts/docker-run.sh --gui bash
xhost -SI:localuser:"$(id -un)"
```

For SSH sessions, connect to the Docker host with `ssh -X` or `ssh -Y` first.
Docker Desktop on macOS or Windows additionally requires a host X server;
native Wayland forwarding is Linux-only. GUI access exposes the display server
to processes in the container, so use `--no-gui` for untrusted programs.

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

## Inspecting actual NPU instructions (SIMD vs SIMT)

The device ELF is `elf64-hiipu`; the public BiSheng `llvm-objdump` registers a
`hiipu64` target but its ISA decoder is not shipped, so `-d` prints
`<not available>`. Use these supported views instead.

The two views describe the **same** instruction stream:

- The `.cce` "CCE print" files are the real device instructions, not a model.
  Their mnemonics match the simulator trace one-to-one (`vadd` = `RV_VADD`,
  `vlds` = `RV_VLDI`, `vsts` = `RV_VSTI`, `mad` = the MMAD, `copy_gm_to_ubuf_*`
  = `MOV_SRC_TO_DST_ALIGNv2`). `.cce` is emitted at **runtime** by
  `libcpudebug_cceprint.so` when a SIMD kernel runs under CPU twin-debug
  (which SIMT lacks), so there is no standalone compile-time `.cce` dump:
  the `--cce-enable-print` compiler flag does not write a file by itself.

```bash
./scripts/docker-run.sh ./scripts/test.sh cpu dav-3510
ls build/cpu-3510/cceprint/          # *_<block>_<core>_vec.cce / _cub.cce
```

- The CA-model simulator emits per-core ASCII instruction traces
  (`core*.veccore*.instr_log.dump`) into the current directory when a `sim`
  executable runs directly. This works for **both** SIMD and SIMT, so it is
  the single source for a like-for-like comparison:

```bash
./scripts/docker-run.sh ./scripts/build.sh sim dav-3510
./scripts/docker-run.sh bash -lc 'cd /workspace && build/sim-3510/vector_add'
./scripts/docker-run.sh bash -lc 'cd /workspace && build/sim-3510/simt_add'
ls core*.veccore*.instr_log.dump     # ASCII instruction trace (gitignored)
```

SIMD and SIMT are distinct instruction sets, not just programming models:

| Aspect | SIMD (`__vector__`) | SIMT (`__global__`, `--enable-simt`) |
|---|---|---|
| Compute | `RV_VADD` / `vadd` | `SIMT_FADD` |
| Load | `RV_VLDI` / `vlds`, DMA `MOV_SRC_TO_DST_ALIGNv2` | `SIMT_LDG` (per warp) |
| Store | `RV_VSTI` / `vsts` | `SIMT_STG` (per warp) |
| Granularity | one 128-wide vector register per instr | one thread element, explicit `warpId`/`schId` |
| Address math | DMA descriptors | ~200 `SIMT_IADD`/`SIMT_IMUL`/`SIMT_LEA`/`SIMT_ISETP`/`SIMT_SEL` |
| Code size (8192-elem add) | `.text` 0x114 (276 B) | `.text` 0x428 (1064 B) |

`simt_add` is `dav-3510`-only and has no CPU twin-debug mode; inspect it via
the simulator trace dumps above.

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
