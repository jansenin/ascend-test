# 8. bf16 "anomaly" on 910B: a stale-data artifact, not a hardware difference

## What we saw

On the FLOPS-vs-index sorted graphs (`scripts/cube-graph.py --x sorted`) the
dav-2201 (Ascend 910B) `bfloat16` curve looked wrong:

- It starts at lower FLOPS than `half`, keeps a large gap for most of the
  graph, and even sits **below `float`** for more than half the range.
- On dav-3510 (Ascend 950) `bfloat16` and `half` are essentially identical.

That is suspicious on its face: `half` and `bfloat16_t` are both 2-byte `b16`
types (K0 = 32/2 = 16, same 16×16×16 fractal, same 8192 FLOP/cycle ceiling), so
they should be indistinguishable. The 950 graph confirms this; the 910B graph
contradicts it.

## Why we investigated

The graph is only as good as its data. The `out/cube-sweep/2201/bf16.csv` file
was produced by the **previous** (GM-streaming, pre-L1-preload) kernel, while
`half.csv`/`float.csv`/`int8.csv` were already re-measured with the current
L1-preload kernel. So the comparison was apples-to-oranges: the old kernel was
memory-bound on the A-streaming path (MTE2 GM→L1), which inflates the MMAD
issue interval and drags measured FLOPS down at every size below the ceiling.

## What we wanted to check

Two hypotheses:

1. **Data artifact**: the low 2201-bf16 FLOPS are an artifact of the stale
   (old-kernel) CSV, and bf16 is actually equal to half on the current kernel.
2. **Real difference**: bf16 has a genuinely different MMAD latency/throughput
   than half on 910B.

We tested this directly on the **current** kernel by measuring the MMAD issue
interval (the exact quantity that FLOPS = 2·m·n·k / interval is built from) for
half and bfloat16 at several tile sizes on one 2201 core.

## Result

The MMAD issue interval is byte-for-byte identical between `half` and `bfloat16`:

| size (m×k×n) | half interval | bf16 interval |
|---|---:|---:|
| 16×64×64  | 36 cyc | 36 cyc |
| 64×64×64  | 74 cyc | 74 cyc |
| 128×64×128 | 258 cyc | 258 cyc |

At the MMAD level `bfloat16 == half` on 2201 (same fixed latency, same
throughput). The old CSV distribution confirms the artifact: stale 2201-bf16
has `max=14.72 TFLOPS` (the same peak as half) but `median=4.92`, i.e. the
*ceiling* is identical and only the *spread* (many latency-bound points) is
worse — exactly what an MTE2-bound streaming kernel produces at small/mid sizes.

**Conclusion**: the 910B bf16 "anomaly" is a stale-data artifact (old
GM-streaming kernel vs new L1-preload kernel), not a hardware difference.

**Confirmed by the re-sweep.** After the fresh L1-preload run, `bfloat16` and
`half` are byte-identical on both devices:

| arch | dtype | max | median (p50) | p10 |
|---|---|---:|---:|---:|
| 2201 | half | 14.71 | 14.52 | 4.75 |
| 2201 | bf16 | 14.71 | 14.52 | 4.75 |
| 3510 | half | 14.73 | 14.68 | 11.76 |
| 3510 | bf16 | 14.73 | 14.68 | 11.76 |

So the odd 910B curve was purely the old-vs-new kernel mismatch; there is no
bfloat16-vs-half hardware difference on either architecture.

Side finding worth recording: on 2201 the L1 preload is capacity-bound. The
constraint `16 · m·k·sizeof(T) ≤ 523776 B` (L1 = 512 KiB minus a 256 B
reservation) rejects large tiles such as `128×128×128` and `256×64×128`
(`16·128·128·2 = 524288 > 523776`). dav-3510 has the full 524288 B, so its
usable A-tile set is marginally larger.

## Reproduce

```bash
# Rebuild the (fixed) cube_peak kernel for 2201:
./scripts/docker-run.sh ./scripts/build.sh sim dav-2201

# Compare half vs bfloat16 MMAD issue interval on ONE core. The interval is
# extracted from the MMAD issue stamps in core0.cubecore0.instr_log.dump:
# (raw `docker run --user 0:0` because the single-core patch writes the
# root-owned simulator config; `docker-run.sh` runs as the host user and cannot)
docker run --rm --user 0:0 -v "$PWD":/workspace -w /workspace \
  ascendc-low-level:9.2.0-beta.2 bash -lc '
  source /usr/local/Ascend/cann/set_env.sh 2>/dev/null
  cfg="$ASCEND_HOME_PATH/tools/simulator/dav_2201/lib/config_stars.json"
  python3 -c "import json;d=json.load(open(\"$cfg\"));d[\"model_top\"][\"num_aic\"]=1;d[\"model_top\"][\"num_aiv\"]=2;json.dump(d,open(\"$cfg\",\"w\"),indent=2)"
  mkdir -p /workspace/out/run && cd /workspace/out/run
  for dt in half bf16; do
    for sz in "16 64 64" "64 64 64" "128 64 128"; do
      set -- $sz
      /workspace/build/sim-2201/cube_peak $1 $2 $3 $dt >/dev/null 2>&1
      s=$(grep MMAD core0.cubecore0.instr_log.dump | grep -oE "\[[0-9]{8}\]" | tr -d "[]")
      f=$(echo "$s" | head -1); l=$(echo "$s" | tail -1); c=$(echo "$s" | wc -l)
      echo "2201 $dt ${1}x${2}x${3}: interval=$(( (10#$l - 10#$f) / (c-1) )) cyc"
    done
  done'
#   2201 half 16x64x64: interval=36 cyc
#   2201 half 64x64x64: interval=74 cyc
#   2201 half 128x64x128: interval=258 cyc
#   2201 bf16 16x64x64: interval=36 cyc      <- identical to half
#   2201 bf16 64x64x64: interval=74 cyc      <- identical to half
#   2201 bf16 128x64x128: interval=258 cyc   <- identical to half
```
