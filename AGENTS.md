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
4. **Write investigations/discoveries down, not just experiments.** When an
   anomaly is investigated and explained (or a claim is made/disproved), capture
   the reasoning + conclusion in `docs/reports/NN-<slug>.md` (or `docs/LESSONS.md`
   for a one-line gotcha). Don't leave a "needs investigation" finding floating
   in chat only.
5. **Never re-use a CMake build dir across run modes or architectures.**
   `CMAKE_ASC_RUN_MODE` (cpu|sim|npu) and `CMAKE_ASC_ARCHITECTURES`
   (dav-2201|dav-3510) are cached; use a fresh `build/{mode}-{2201|3510}` each
   time (the build script does this automatically).
6. **Do not commit unless asked** (the owner has authorized self-commits when a
   change is clearly needed; when in doubt, present first).

## How to engage with the owner

- **Understand intent, not just the literal ask.** Read *why* a request is made.
  The owner sometimes doesn't yet know exactly what they want. If the literal
  ask won't satisfy the underlying goal, say so; if you believe you understand
  what they actually want and they asked for the wrong thing, tell them.
- **Push back / propose better.** If the owner's suggested approach is
  suboptimal, propose a better one instead of silently implementing it. Don't
  just do the thing.
- **Flag suspicious requests.** If something seems strange, or you suspect the
  owner probably wanted something else, ask before doing it.
- Prefer a short analysis + question over a long detour in the wrong direction.
- **Parallel tasks — integrate, prioritize, then act.** The owner drops several
  tasks/questions at once; that does NOT mean "abort the in-flight work." Keep an
  active state of current tasks, fold new items into it, re-prioritize, and act in
  priority order — do not switch mid-task to the newest request.
- **Don't rush under load.** When the owner piles on tasks or asks to fix
  everything at once, slow down and still honor these rules; don't let urgency
  push them out of active attention.

## Sustaining the project (git and knowledge files)

- **Use git; keep the repo in a consistent state.** Commit self-contained pieces
  of work — even small ones — when it seems right (the owner authorizes
  self-commits). When you can't or shouldn't commit, correct the relevant
  knowledge files instead (`docs/LESSONS.md`, `docs/reports/*`, `docs/REFERENCE.md`).
- **When a self-contained piece is finished, pause for the broader picture.**
  Before taking the next task — when there would otherwise be no attention to
  spare for it — spend a moment sustaining the workflow: commit, update a doc, or
  capture a discovery. Don't let supportive work get perpetually deferred.

## Context management (compression)

These govern how the agent manages its own context window; they exist because
compression can silently degrade intent.

- **Never compress the owner's prompts into paraphrase.** Prompts are small but
  intent-dense. If a prompt falls inside a compression range, summarize it by
  citing it verbatim rather than rewriting it.
- **Do not compress instructions that govern how the agent behaves.** Compressing
  them changes behaviour. Compress factual/technical content instead.
- **When compressing, save the *why*, not just the *what*.** Preserve intent and
  the reasoning behind an instruction. Example: "the owner wanted to save context
  from big, low-information code files" is the intent; "always compress big files"
  is a lossy distortion of it.
- **If a large block that "should be compressed" conflicts with these rules,
  flag it** to the owner instead of silently choosing one side.

## Precise statements (confidence + provenance)

The owner likes precise language and wants to know how sure the agent is and
where a fact came from.

- **Signal confidence with wording.** Distinguish verified (from a file/command
  you actually read/ran), measured (from a real run), inferred/deduced, and
  guessed/assumed. Don't let a stale fact read as current truth.
- **State the source.** If a number comes from a file, name the file; if from a
  command's output, say so (`lscpu`, a simulator log, `vendor-src/...`). The
  owner may have moved machines or the fact may be outdated — provenance lets
  them judge. Apply the same discipline to factual answers.

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
- `docs/REFERENCE.md` — quick-reference: buffer sizes, K0/MMAD constants, tool
  paths, workflows.
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
