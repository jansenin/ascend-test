# 10 — Hunting for an official performance model (PTO / VfSim)

## What we did

Went looking for an already-made performance model of the two chips (dav-2201 /
910B and dav-3510 / 950), instead of reverse-engineering one from microbenchmarks.
Found three layers, from least to most detailed:

1. **The CA-model simulator is binary-only** — no source ships in the image.
2. **PyPTO** (`python/site-packages/pypto/`) is the "describe an op in Python, get
   a performance estimate" tool; its engine is a C++ library.
3. **The PTO C++ cost model** is fully readable and is what we extracted:
   - `costmodel/a2a3/` (dav-2201): a *linear* formula model —
     `formula_costmodel/formula_params.csv` = `op,dtype,cols,slope,bias`.
   - `costmodel/a5/VfSim/` (dav-3510): a *cycle-accurate* vector-unit simulator
     in C++, parameterized by `params/{uarch,isa,forwarding,initiation_interval}.csv`.

The 3510 `VfSim` is **open source** (vendored from
`github.com/wang-chonghao/VfSimulator`); both are now copied under `vendor-src/`
for local reference (`vendor-src/pto/`, `vendor-src/VfSimulator/`).

## Why we did it

The bank microbenchmarks (report 09) showed the *simulator* reacting to operand
placement, and we wanted a ground-truth model to explain *why* — ideally one that
states the memory-bank rules directly.

## What we wanted to check

Whether an official model exists, and whether it models **UB memory banks** (the
thing report 09 probed).

## Result

The key numbers line up with our measurements:

| model | value | measured (report 09) |
|---|---|---|
| 3510 `VADD` fp32 | throughput 2 cyc (`isa.csv`) | RV_VADD issue interval ~2.3–2.6 cyc |
| 2201 `TADDS` fp32 | slope 0.0156 cyc/col ≈ 256 B/cyc | ~224 B/cyc |

**But there is a distinction we got wrong at first, worth stating precisely:**

- The **PTO / VfSim cost model** does **not** model UB memory banks. `VfSim` is a
  *register-level* out-of-order model (issue ports, IDU window, per-op latency/
  throughput/forwarding); its loads/stores are fixed 9-cycle-latency,
  throughput-1, address-independent. The word "bank" in `VfSim` refers to the
  *physical register file* (vector vs predicate banks), not UB. UB is only a
  storage *type tag*.
- The **CA-model simulator** (the `sim` run-mode binary that emits
  `core*.instr_log.dump` and produces every interval we measured) **does** model
  UB bank behavior — that is exactly where the stride (24→38 cyc) and gap
  (256 B fast) effects came from.

So: the *cost model* treats UB as flat bandwidth; the *simulator* does not. They
are two different pieces, and report 09's bank effects come from the simulator's
memory model, not from VfSim.

## Reproduce

```bash
# The model lives under vendor-src/ (gitignored). Re-copy it from the image:
docker run --rm -v "$PWD/vendor-src":/v ascendc-low-level:9.2.0-beta.2 \
  bash -c 'cp -r /usr/local/Ascend/cann-9.2.0-beta.2/x86_64-linux/include/pto /v/pto'

# 3510 per-instruction timing (op,form,startup,latency,throughput,drain,...):
#   VADD,f32,6,7,2,5,9,9,ALU,EXU01,COMPUTE    <-- throughput 2
#   VLDS,f32,0,9,1,0,9,0,,,LOAD               <-- load: fixed 9 cyc, throughput 1
grep -E 'VADD|VLDS|VSTS' vendor-src/pto/costmodel/a5/VfSim/params/isa.csv

# 3510 microarchitecture (ports, windows, depths):
#   issue_ports=2, load_ports=2, store_ports=1, IDU_issue_width=5, vreg_num=68
cat vendor-src/pto/costmodel/a5/VfSim/params/uarch.csv

# 2201 linear cost model (op,dtype,cols,slope,bias):
#   TADDS,f32,32,0.0156,25        <-- slope cycles per column
head -5 vendor-src/pto/costmodel/a2a3/formula_costmodel/formula_params.csv
```

Note: `vendor-src/` is gitignored, so these files are local reference only; the
`results/cube-sweep/` CSVs/PNGs (committed) are the reproducible cube data that
`cube_view3d.py` / `cube_volume.py` / `cube-graph.py` now read by default.
