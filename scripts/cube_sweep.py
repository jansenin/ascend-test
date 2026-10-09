#!/usr/bin/env python3
"""Sweep the cube_peak MMAD kernel over m,n,k multiples of 16 and report FLOPS.

Runs cube_peak (single-core simulator) for every (m,k,n) that fits the on-core
buffers, extracts the MMAD issue cycle stamps from the simulator instruction
log, and computes per-MMAD throughput.

Buffer constraints (correctness, NOT just perf -- the on-core allocators do not
bounds-check and silently corrupt when exceeded):
  - m*k*sizeof(T)  <= L0A/2   (A is double-buffered; 64KB L0A -> 32KB per tile)
  - k*n*sizeof(T)  <= L0B     (B is static; 64KB L0B)
  - m*n*sizeof(CT) <= L0C     (128KB on dav-2201, 256KB on dav-3510)
  - (m/16)*(n/16)  >= 10      (skip too-small tiles)

FLOPS convention: 2*m*n*k FLOP per MMAD.  interval = (last MMAD issue - first
MMAD issue) / (num_mmads - 1) cycles.  FLOPS/cycle = 2*m*n*k / interval.
Clock is 1.8 GHz, ideal Cube throughput is 8192 FLOP/cycle (14.75 TFLOPS).

Usage (inside the container, after the config_stars.json core-count patch):
    python3 scripts/cube_sweep.py --arch 3510 --dtype half
"""
import argparse
import concurrent.futures
import csv
import os
import re
import shutil
import subprocess
import sys
import tempfile

L0A_BYTES = 64 * 1024
L0B_BYTES = 64 * 1024
L0C_BYTES = {"2201": 128 * 1024, "3510": 256 * 1024}
# L1 usable: dav-2201 reserves 256B (ASC_L1_SIZE = 512*1024 - 256), dav-3510 does not.
L1_BYTES = {"2201": 512 * 1024 - 256, "3510": 512 * 1024}
CLOCK_HZ = 1.8e9
IDEAL_FLOPS_PER_CYCLE = 8192.0

# sizeof(T) for A/B, sizeof(CT) for the accumulator
DTYPE_T = {"half": 2, "float": 4, "int8": 1, "bf16": 2}
DTYPE_CT = {"half": 4, "float": 4, "int8": 4, "bf16": 4}

NUM_MMADS = 16


def enumerate_sizes(arch, dtype):
    ts = DTYPE_T[dtype]
    ct = DTYPE_CT[dtype]
    l0c = L0C_BYTES[arch]
    l1 = L1_BYTES[arch]
    sizes = []
    for m in range(16, 4096, 16):
        for n in range(16, 4096, 16):
            if (m // 16) * (n // 16) < 10:
                continue
            if m * n * ct > l0c:
                continue
            for k in range(16, 4096, 16):
                if m * k * ts > L0A_BYTES // 2:
                    continue
                if NUM_MMADS * m * k * ts > l1:
                    continue
                if k * n * ts > L0B_BYTES:
                    continue
                sizes.append((m, k, n))
    return sizes


def extract_mmad_cycles(rundir):
    """Return (first_cycle, last_cycle, count) of MMAD issue stamps, or None."""
    dump = os.path.join(rundir, "core0.cubecore0.instr_log.dump")
    if not os.path.exists(dump):
        return None
    stamps = []
    with open(dump, "r", errors="replace") as f:
        for line in f:
            if "MMAD" in line:
                m = re.search(r"\[(\d{8})\]", line)
                if m:
                    stamps.append(int(m.group(1)))
    if len(stamps) < 2:
        return None
    return (stamps[0], stamps[-1], len(stamps))


def run_one(binary, m, k, n, dtype, timeout):
    tmp = tempfile.mkdtemp(prefix="cube_", dir="/tmp")
    try:
        proc = subprocess.run(
            [binary, str(m), str(k), str(n), dtype],
            cwd=tmp,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = proc.stdout + proc.stderr
        tick_m = re.search(r"Total tick:\s*(\d+)", out)
        tick = int(tick_m.group(1)) if tick_m else None
        if "PASS" in out:
            status = "PASS"
        elif "FAIL" in out or "reject" in out.lower() or "exceed" in out.lower():
            status = "FAIL"
        else:
            status = "?"
        mmad = extract_mmad_cycles(tmp)
        return {"m": m, "k": k, "n": n, "tick": tick, "status": status, "mmad": mmad, "log": out}
    except subprocess.TimeoutExpired:
        return {"m": m, "k": k, "n": n, "tick": None, "status": "TIMEOUT", "mmad": None, "log": ""}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arch", required=True, choices=["2201", "3510"])
    ap.add_argument("--dtype", required=True, choices=sorted(DTYPE_T))
    ap.add_argument("--binary", default=None, help="cube_peak executable path")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--output", default=None)
    ap.add_argument("--limit", type=int, default=None, help="run only first N sizes (debug)")
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()

    binary = args.binary or f"/workspace/build/sim-{args.arch}/cube_peak"
    binary = os.path.abspath(binary)
    if not os.path.exists(binary):
        sys.exit(f"binary not found: {binary}")

    # Each simulator process uses ~1.2 cores (23 threads, mostly idle waiting on
    # events), so "leave 4 free" on an N-core host => floor((N-4)/1.2) workers.
    workers = args.workers or max(1, int(((os.cpu_count() or 2) - 4) / 1.2))
    workers = max(1, workers)

    out_path = args.output or f"/workspace/out/cube-sweep/{args.arch}/{args.dtype}.csv"
    out_dir = os.path.dirname(out_path)
    os.makedirs(out_dir, exist_ok=True)

    sizes = enumerate_sizes(args.arch, args.dtype)
    if args.limit:
        sizes = sizes[: args.limit]

    print(f"arch={args.arch} dtype={args.dtype} sizes={len(sizes)} workers={workers}")
    print(f"binary={binary}")
    print(f"output={out_path}")
    sys.stdout.flush()

    ts = DTYPE_T[args.dtype]
    fields = ["m", "k", "n", "mkn", "tick", "mmad_count", "interval_cyc",
              "flops_per_cyc", "tflops", "efficiency", "status"]

    with open(out_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        fh.flush()

        done = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(run_one, binary, m, k, n, args.dtype, args.timeout): (m, k, n)
                    for (m, k, n) in sizes}
            for fut in concurrent.futures.as_completed(futs):
                m, k, n = futs[fut]
                r = fut.result()
                row = {"m": m, "k": k, "n": n, "mkn": m * k * n, "tick": r["tick"],
                       "mmad_count": None, "interval_cyc": None, "flops_per_cyc": None,
                       "tflops": None, "efficiency": None, "status": r["status"]}
                if r["mmad"] is not None:
                    first, last, count = r["mmad"]
                    interval = (last - first) / float(count - 1)
                    fpc = 2.0 * m * k * n / interval
                    row["mmad_count"] = count
                    row["interval_cyc"] = round(interval, 3)
                    row["flops_per_cyc"] = round(fpc, 3)
                    row["tflops"] = round(fpc * CLOCK_HZ / 1e12, 3)
                    row["efficiency"] = round(fpc / IDEAL_FLOPS_PER_CYCLE, 4)
                w.writerow(row)
                fh.flush()
                done += 1
                if done % 100 == 0:
                    print(f"  {done}/{len(sizes)} done", file=sys.stderr)

    print(f"wrote {out_path} ({len(sizes)} rows)")


if __name__ == "__main__":
    main()
