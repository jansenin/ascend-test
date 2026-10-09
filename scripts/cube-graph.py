#!/usr/bin/env python3
"""Plot cube_peak MMAD sweep results (FLOPS curves).

Reads the CSVs produced by scripts/cube_sweep.py from out/cube-sweep/ and
produces two figure families:

  1. per-dtype: one subplot per dtype, two lines (dav-2201 vs dav-3510).
  2. per-device: one subplot per device, one line per dtype.

Two plotting modes (selected with --x):

  sorted  (default) — the "rank" plot the user asked for.  Take every swept
           point, sort by FLOPS ascending, and plot FLOPS vs a synthetic
           x = cbrt(index) normalised to [0,1] (cbrt because the point count
           grows roughly cubically with the three free dims m,n,k, and the
           normalisation makes every line span [0,1] so multiple lines are
           comparable).  Because the points are sorted, the line is monotonic.

  mkn|mn|mk|kn — FLOPS vs a size metric, with a running-max envelope (the old
           view).  Raw scatter is noisy; the envelope shows the latency-bound
           rise to the throughput plateau.

Runs on the host (only needs matplotlib + the CSVs, no NPU/container).

Usage:
    python3 scripts/cube-graph.py [--x sorted|mkn|mn|mk|kn] [--out DIR]
"""
import argparse
import csv
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ARCH_LABEL = {"2201": "dav-2201 (910B)", "3510": "dav-3510 (950)"}
DTYPE_ORDER = ["half", "float", "int8", "bf16"]
# Theoretical "1 fractal/cycle" peak in TFLOPS (512*K0 FLOP/cyc @ 1.8 GHz).
K0 = {"half": 16, "bf16": 16, "float": 8, "int8": 32}
IDEAL_TFLOPS = {d: 512.0 * K0[d] * 1.8e9 / 1e12 for d in K0}


def load(csv_path):
    rows = []
    with open(csv_path, newline="") as f:
        for r in csv.DictReader(f):
            if r.get("tflops") in (None, ""):
                continue
            rows.append(r)
    return rows


def xval(r, metric):
    m, k, n = int(r["m"]), int(r["k"]), int(r["n"])
    return {"mkn": m * k * n, "mn": m * n, "mk": m * k, "kn": k * n}[metric]


def running_max(pts):
    """Monotonic non-decreasing envelope: best FLOPS at or below each size."""
    xs, ys = [], []
    best = 0.0
    for x, y in sorted(pts):
        best = max(best, y)
        xs.append(x)
        ys.append(best)
    return xs, ys


def sorted_curve(pts):
    """Sort points by FLOPS ascending; x = cbrt(index) normalised to [0,1]."""
    ys = sorted(y for _, y in pts)
    n = len(ys)
    xs = [i ** (1.0 / 3.0) for i in range(n)]
    denom = xs[-1] if n > 1 else 1.0
    xs = [x / denom for x in xs]
    return xs, ys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--x", default="sorted",
                    choices=["sorted", "mkn", "mn", "mk", "kn"],
                    help="'sorted' = FLOPS-sorted cbrt-index curve; else size-metric envelope")
    ap.add_argument("--out", default="out/cube-sweep")
    ap.add_argument("--root", default="out/cube-sweep", help="dir containing <arch>/<dtype>.csv")
    args = ap.parse_args()

    data = {}
    for arch in ("2201", "3510"):
        for dtype in DTYPE_ORDER:
            p = os.path.join(args.root, arch, f"{dtype}.csv")
            if not os.path.exists(p):
                continue
            rows = load(p)
            if not rows:
                continue
            if args.x == "sorted":
                xs, ys = sorted_curve([(None, float(r["tflops"])) for r in rows])
                data[(arch, dtype)] = (None, xs, ys)
            else:
                pts = [(xval(r, args.x), float(r["tflops"])) for r in rows]
                exs, eys = running_max(pts)
                data[(arch, dtype)] = (pts, exs, eys)
    if not data:
        raise SystemExit(f"no sweep CSVs found under {args.root}")

    os.makedirs(args.out, exist_ok=True)
    is_sorted = args.x == "sorted"

    def draw_line(ax, arch, dtype, label):
        pts, xs, ys = data[(arch, dtype)]
        if is_sorted:
            ax.plot(xs, ys, "-", lw=1.5, label=label)
        else:
            px = [x for x, _ in pts]
            py = [y for _, y in pts]
            ax.plot(px, py, "o", ms=2, alpha=0.10)
            ax.plot(xs, ys, "-", lw=2, label=label)

    # 1. per-dtype, two device lines
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    for ax, dtype in zip(axes.flat, DTYPE_ORDER):
        for arch in ("2201", "3510"):
            if (arch, dtype) in data:
                draw_line(ax, arch, dtype, ARCH_LABEL[arch])
        ax.axhline(IDEAL_TFLOPS[dtype], color="gray", ls=":", lw=1,
                   label=f"1 fractal/cyc = {IDEAL_TFLOPS[dtype]:.1f}")
        ax.set_title(dtype)
        if is_sorted:
            ax.set_xlim(0, 1)
            ax.set_xlabel("sorted rank (cbrt, normalised)")
        else:
            ax.set_xscale("log")
            ax.set_xlabel(f"x = {args.x}")
        ax.set_yscale("log")
        ax.set_ylabel("TFLOPS")
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=8)
    mode = "FLOPS-sorted rank" if is_sorted else f"tile size x={args.x}"
    fig.suptitle(f"cube_peak MMAD FLOPS vs {mode}", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    out1 = os.path.join(args.out, f"flops_by_dtype_x-{args.x}.png")
    fig.savefig(out1, dpi=120)
    plt.close(fig)
    print("wrote", out1)

    # 2. per-device, one line per dtype
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True)
    for ax, arch in zip(axes, ("2201", "3510")):
        for dtype in DTYPE_ORDER:
            if (arch, dtype) in data:
                draw_line(ax, arch, dtype, dtype)
        ax.set_title(ARCH_LABEL[arch])
        if is_sorted:
            ax.set_xlim(0, 1)
            ax.set_xlabel("sorted rank (cbrt, normalised)")
        else:
            ax.set_xscale("log")
            ax.set_xlabel(f"x = {args.x}")
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=8)
    axes[0].set_ylabel("TFLOPS")
    fig.suptitle(f"cube_peak MMAD FLOPS per device ({mode})", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    out2 = os.path.join(args.out, f"flops_by_device_x-{args.x}.png")
    fig.savefig(out2, dpi=120)
    plt.close(fig)
    print("wrote", out2)


if __name__ == "__main__":
    main()
