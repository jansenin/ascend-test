#!/usr/bin/env python3
"""Measure UB bank-conflict overhead for the bank_add kernel.

Runs bank_add (single-core simulator) in both dense and sparse UB-layout modes,
extracts the VADD issue cycle stamps from core0.veccore0.instr_log.dump, and
reports the issue interval (last-first)/(count-1), the same metric the cube
sweep uses for MMAD throughput.

  dense  -> lhs/rhs/dst blocks packed back-to-back (1024 floats = 4096 B each)
  sparse -> 128 B of empty space between blocks

For each mode we run N repeats and report min/mean/max interval so run-to-run
noise in the CA-model simulator is visible.

Usage (inside the container):
    python3 scripts/bank_sweep.py --arch 2201 --repeats 3
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

VADD_RE = re.compile(r"\[(\d{8})\].*VADD")


def extract_vadd_cycles(rundir):
    dump = os.path.join(rundir, "core0.veccore0.instr_log.dump")
    if not os.path.exists(dump):
        return None
    stamps = []
    with open(dump, "r", errors="replace") as f:
        for line in f:
            if "VADD" in line:
                m = re.search(r"\[(\d{8})\]", line)
                if m:
                    stamps.append(int(m.group(1)))
    if len(stamps) < 2:
        return None
    return (stamps[0], stamps[-1], len(stamps))


def run_one(binary, mode, timeout):
    tmp = tempfile.mkdtemp(prefix="bank_", dir="/tmp")
    try:
        proc = subprocess.run(
            [binary, mode], cwd=tmp, capture_output=True, text=True, timeout=timeout
        )
        out = proc.stdout + proc.stderr
        tick_m = re.search(r"Total tick:\s*(\d+)", out)
        tick = int(tick_m.group(1)) if tick_m else None
        vadd = extract_vadd_cycles(tmp)
        return {"tick": tick, "vadd": vadd, "pass": "PASS" in out}
    except subprocess.TimeoutExpired:
        return {"tick": None, "vadd": None, "pass": False}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arch", required=True, choices=["2201", "3510"])
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()

    binary = f"/workspace/build/sim-{args.arch}/bank_add"
    if not os.path.exists(binary):
        sys.exit(f"binary not found: {binary}")

    print(f"arch={args.arch} binary={binary} repeats={args.repeats}")
    for mode in ("dense", "sparse"):
        intervals = []
        ticks = []
        for _ in range(args.repeats):
            r = run_one(binary, mode, args.timeout)
            if r["vadd"] is None:
                print(f"  {mode}: NO VADD found (pass={r['pass']})", file=sys.stderr)
                continue
            first, last, count = r["vadd"]
            interval = (last - first) / float(count - 1)
            intervals.append(interval)
            ticks.append(r["tick"])
        if intervals:
            mn, mx = min(intervals), max(intervals)
            mean = sum(intervals) / len(intervals)
            print(f"  {mode:6s} vadd_count={count} interval_cyc "
                  f"min={mn:.2f} mean={mean:.2f} max={mx:.2f}  ticks={ticks}")


if __name__ == "__main__":
    main()
