# AGENTS.md — repo conventions for humans and AI agents

This is a low-level AscendC / Ascend NPU kernel lab. Everything is Dockerized and
runs with **no NPU hardware**: CPU twin-debug and the CA-model simulator only.
The purpose is to learn the low-level programming model (SIMD MemBase/RegBase,
SIMT, MMAD, gather/scatter, synchronization) and measure it empirically.

## Hard rules

1. **Never commit** the CANN installer, `/vendor-src/`, `/build/`, `/out/`,
   `/downloads/*`, or any generated `core*.dump` / `profile_*.toml` / `.cce`
   files. They are all gitignored. Only source, scripts, Docker config, and
   `docs/` belong in the repo.
2. **Keep `docs/reports/` consistent.** Every experiment gets a report under
   `docs/reports/NN-<slug>.md` with four sections: *what we did*, *why*,
   *what we wanted to check*, *reproduce* (copy-pasteable commands with
   `#` comments showing expected output — the reader must NOT be required to
   run them). Update `docs/reports/README.md` index when adding one.
3. **Record every mistake / non-obvious API discovery in `docs/LESSONS.md`.**
   The whole point of this repo is to learn on past mistakes. If an API doc was
   unintuitive, if an assumption turned out wrong, if a claim was later
   corrected (e.g. "SIMT wins" that was really launch overhead) — write it down
   so future agents and the owner don't repeat it.
6. **Write investigations/discoveries down, not just experiments.** When an
   anomaly is investigated and explained (or a claim is made/disproved), capture
   the reasoning + conclusion in `docs/reports/NN-<slug>.md` (or `docs/LESSONS.md`
   for a one-line gotcha). Don't leave a "needs investigation" finding floating
   in chat only.
4. **Never re-use a CMake build dir across run modes or architectures.**
   `CMAKE_ASC_RUN_MODE` (cpu|sim|npu) and `CMAKE_ASC_ARCHITECTURES`
   (dav-2201|dav-3510) are cached; use a fresh `build/{mode}-{2201|3510}` each
   time (the build script does this automatically).
5. **Do not commit unless asked** (the owner has authorized self-commits when a
   change is clearly needed; when in doubt, present first).

## How to engage with the owner

- **Understand intent, don't just execute literally.** Read *why* a request is
  made. If the literal ask won't actually satisfy the underlying goal, say so.
- **Push back on bad suggestions.** If the owner's proposed approach is
  suboptimal, propose a better one instead of silently implementing it.
- **Flag suspicious requests.** If something seems strange, or you suspect the
  owner probably wanted something else, ask before doing it.
- Prefer a short analysis + question over a long detour in the wrong direction.
- **Parallel tasks.** The owner often drops several tasks/questions at once and
  that does NOT mean "abort what you're doing." Fold the new items into the
  current task list, re-prioritize, and continue the in-flight work; act on the
  new items in priority order rather than switching mid-task.

## Workflow (every command through the Docker image)

```bash
# Fresh clone bootstrap (downloads CANN + builds image; needs --accept flags):
./scripts/fetch-cann.sh --accept-license
./scripts/docker-build.sh --accept-eula

# Build a target (mode=cpu|sim|npu, arch=dav-2201|dav-3510):
./scripts/docker-run.sh ./scripts/build.sh sim dav-3510     # -> build/sim-3510/

# Run the test suite:
./scripts/docker-run.sh ./scripts/test.sh sim dav-3510

# Run one simulator binary directly (prints "Total tick: N" + PASS/FAIL, dumps
# core*.veccore*.instr_log.dump + profile_*.toml into CWD — run in a scratch dir):
./scripts/docker-run.sh bash -lc 'cd /workspace/build/sim-3510 && ./vector_add'

# msprof trace (out/simulator/<arch>/<target>-<ts>/.../trace.json):
./scripts/docker-run.sh ./scripts/simulate.sh dav-3510 vector_add

# Environment sanity check / static checks:
./scripts/docker-run.sh ./scripts/check-environment.sh
./scripts/static-checks.sh && git diff --check

# Interactive shell:
./scripts/docker-run.sh bash
```

## Where things live

- `apps/*.asc` — self-contained kernels (host `main()` + device kernel in one
  file). SIMD files include `kernel_operator.h`; SIMT files include
  `simt_api/asc_simt.h` (+ `simt_api/asc_fp16.h` for half) and MUST NOT include
  `kernel_operator.h` (typedef redefinition). SIMD/SIMT are mutually exclusive.
- `include/device_kernels.h` — shared SIMD kernel helpers (namespace `lab`).
- `include/test_support.h`, `include/half_utils.h` — host test/FP16 helpers.
- `CMakeLists.txt` — SIMD targets use `--npu-arch`; SIMT targets add
  `--enable-simt` and are gated on non-`cpu` mode (SIMT has no CPU-debug).
- `scripts/`, `docker/`, `dependencies.lock` — build/toolchain infra.
- `docs/ARCHITECTURE.md`, `docs/TOOLS.md` — how the kernels/tools work.
- `docs/LESSONS.md` — mistakes, API gotchas, and corrected claims (READ FIRST
  before trusting any conclusion).
- `docs/reports/` — per-experiment reports.

## Architecture cheat sheet

| target | `__NPU_ARCH__` | AIV model | SIMT? |
|---|---|---|---|
| Ascend 910B / Atlas A2/A3 | `dav-2201` | MemBase (no RegBase registers) | no |
| Ascend 950PR / 950DT | `dav-3510` | RegBase (`AscendC::Reg::*`) | yes |

Simulator SOC: dav-2201 → `Ascend910B1`, dav-3510 → `Ascend950PR_9599`.

## Where the "answers" come from (verify, don't guess)

Pinned vendor sources (already downloaded for reference, gitignored):
`vendor-src/asc-devkit` (commit `ec3460ef8eeb453312dcd5c5efaf0dca55885627`),
`vendor-src/asc-tools` (`839db8d6b1eb0f1bf70fdc12b4bb103578cb397d`),
`vendor-src/cann-samples`, `vendor-src/msopprof`, `vendor-src/mssanitizer`,
`vendor-src/msinsight`. When unsure about an API, read the header + impl in
`vendor-src/asc-devkit/include/...` rather than trusting prose docs.
