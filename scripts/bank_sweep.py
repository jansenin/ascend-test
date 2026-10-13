#!/usr/bin/env python3
"""Measure UB bank-conflict overhead for the bank_add kernel.

Runs bank_add (single-core simulator) with a sweep of operand-block gap sizes
(in bytes), extracts the VADD issue cycle stamps from
core0.veccore0.instr_log.dump, and reports the issue interval
(last-first)/(count-1) — the same metric the cube sweep uses for MMAD throughput.

On dav-2201 a read-read bank conflict is expected when the gap leaves the two
source operands in the same bank group, i.e. when (4096 + gap) % 512 == 0.
On dav-3510 the MemBase Add lowers to RV_VADD register ops, so this script also
optionally reports the RV_VLDI (UB load) span, which is where 3510 banking lives.

Usage (inside the container):
    python3 scripts/bank_sweep.py --arch 2201 --gaps 0,32,64,128,256,512 --repeats 3
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

VADD_RE = re.compile(r"\[(\d{8})\].*(?:RV_VADD|VADD)")
VLDI_RE = re.compile(r"\[(\d{8})\].*RV_VLDI")


def extract_cycles(rundir, regex):
    dump = os.path.join(rundir, "core0.veccore0.instr_log.dump")
    if not os.path.exists(dump):
        return None
    stamps = []
    with open(dump, "r", errors="replace") as f:
        for line in f:
            if regex.search(line):
                m = re.search(r"\[(\d{8})\]", line)
                if m:
                    stamps.append(int(m.group(1)))
    if len(stamps) < 2:
        return None
    return stamps


def run_one(binary, gap_bytes, timeout):
    tmp = tempfile.mkdtemp(prefix="bank_", dir="/tmp")
    try:
        proc = subprocess.run(
            [binary, str(gap_bytes)], cwd=tmp, capture_output=True, text=True,
            timeout=timeout,
        )
        out = proc.stdout + proc.stderr
        tick_m = re.search(r"Total tick:\s*(\d+)", out)
        tick = int(tick_m.group(1)) if tick_m else None
        vadd = extract_cycles(tmp, VADD_RE)
        vldi = extract_cycles(tmp, VLDI_RE)
        return {"tick": tick, "vadd": vadd, "vldi": vldi, "pass": "PASS" in out}
    except subprocess.TimeoutExpired:
        return {"tick": None, "vadd": None, "vldi": None, "pass": False}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def span(stamps):
    if not stamps or len(stamps) < 2:
        return None
    return (stamps[-1] - stamps[0]) / float(len(stamps) - 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arch", required=True, choices=["2201", "3510"])
    ap.add_argument("--gaps", default="0,128,256,512", help="comma-separated byte gaps")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()

    binary = f"/workspace/build/sim-{args.arch}/bank_add"
    if not os.path.exists(binary):
        sys.exit(f"binary not found: {binary}")

    gaps = [int(g) for g in args.gaps.split(",")]
    print(f"arch={args.arch} binary={binary} repeats={args.repeats}")
    print(f"{'gap_B':>7s} {'vadd_cyc':>9s} {'vldi_cyc':>9s} {'ticks':>12s}")
    for gap in gaps:
        vadd_int, vldi_int, ticks = [], [], []
        count = None
        for _ in range(args.repeats):
            r = run_one(binary, gap, args.timeout)
            if r["vadd"] is None:
                print(f"{gap:7d}  NO VADD (pass={r['pass']})", file=sys.stderr)
                continue
            count = len(r["vadd"])
            vadd_int.append(span(r["vadd"]))
            if r["vldi"]:
                vldi_int.append(span(r["vldi"]))
            if r["tick"] is not None:
                ticks.append(r["tick"])
        if not vadd_int:
            continue
        va = sum(vadd_int) / len(vadd_int)
        vl = sum(vldi_int) / len(vldi_int) if vldi_int else float("nan")
        tk = "[" + ",".join(str(t) for t in ticks) + "]"
        print(f"{gap:7d} {va:9.2f} {vl:9.2f} {tk:>12s}  (vadd_count={count})")


if __name__ == "__main__":
    main()
