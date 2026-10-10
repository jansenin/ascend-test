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

  mkn|mn|mk|kn — FLOPS vs a size metric.  The raw points are drawn as a faint
            scatter; on top of them a monotonic "running-max envelope" line is
            drawn (best FLOPS at-or-below each size).  The line is a smoothing
            of the scatter, not a separate data series.

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
from matplotlib.lines import Line2D  # noqa: E402

ARCH_LABEL = {"2201": "dav-2201 (910B)", "3510": "dav-3510 (950)"}
ARCH_COLOR = {"2201": "tab:blue", "3510": "tab:orange"}
DTYPE_ORDER = ["half", "float", "int8", "bf16"]
DTYPE_COLOR = {"half": "tab:blue", "float": "tab:orange",
               "int8": "tab:green", "bf16": "tab:red"}

CLOCK_HZ = 1.8e9

# Theoretical cube peak in TFLOPS = MAC/cycle * 2 FLOP/MAC * clock.
#
# half / bf16 / int8: the cube completes one 16x16x16 (b16) or 16x16x32 (b8)
# fractal per cycle, i.e. K0=16/16/32 elements of reduction per cycle ->
# 4096 / 4096 / 8192 MAC per cycle.  This is both the documented rate AND what
# the sweep saturates at (ratio 1.00).
#
# float: NOT one fractal per cycle.  The sweep saturates at exactly 1/2 (2201)
# and 1/8 (3510) of the fp16 fractal rate -> 1024 / 256 MAC per cycle.  We take
# the measured saturation as the reference because no independent public spec
# gives a float MMAD MAC rate, and it is arch-dependent.
MAC_PER_CYC = {
    "half": 4096, "bf16": 4096, "int8": 8192,
    "float": {"2201": 1024, "3510": 256},
}


def theoretical_tflops(arch, dtype):
    m = MAC_PER_CYC[dtype]
    if isinstance(m, dict):
        m = m[arch]
    return 2.0 * m * CLOCK_HZ / 1e12


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

    def draw_line(ax, arch, dtype, label, color):
        pts, xs, ys = data[(arch, dtype)]
        if is_sorted:
            ax.plot(xs, ys, "-", lw=1.5, color=color, label=label)
        else:
            px = [x for x, _ in pts]
            py = [y for _, y in pts]
            ax.plot(px, py, "o", ms=2, alpha=0.10, color=color)
            ax.plot(xs, ys, "-", lw=2, color=color, label=label)

    # 1. per-dtype, two device lines
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    for ax, dtype in zip(axes.flat, DTYPE_ORDER):
        for arch in ("2201", "3510"):
            if (arch, dtype) in data:
                draw_line(ax, arch, dtype, ARCH_LABEL[arch], ARCH_COLOR[arch])
                # theoretical peak reference (dashed, arch colour — float differs by arch)
                ax.axhline(theoretical_tflops(arch, dtype), color=ARCH_COLOR[arch],
                           ls=":", lw=1, alpha=0.7,
                           label=f"{ARCH_LABEL[arch]} peak = {theoretical_tflops(arch, dtype):.2f}")
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
        ax.legend(fontsize=7)
    mode = "FLOPS-sorted rank" if is_sorted else f"tile size x={args.x}"
    if not is_sorted:
        mode += "  (dots = raw points; lines = running-max envelope)"
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
                draw_line(ax, arch, dtype, dtype, DTYPE_COLOR[dtype])
                ax.axhline(theoretical_tflops(arch, dtype), color=DTYPE_COLOR[dtype],
                           ls=":", lw=1, alpha=0.5)
        ax.set_title(ARCH_LABEL[arch])
        if is_sorted:
            ax.set_xlim(0, 1)
            ax.set_xlabel("sorted rank (cbrt, normalised)")
        else:
            ax.set_xscale("log")
            ax.set_xlabel(f"x = {args.x}")
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=8)
        if not is_sorted:
            # single gray legend entry for the raw scatter, so it is not unexplained
            handles, labels = ax.get_legend_handles_labels()
            handles.insert(0, Line2D([0], [0], marker="o", ls="", color="0.4",
                                     ms=3, alpha=0.3, label="raw points"))
            ax.legend(handles=handles, fontsize=8)
    axes[0].set_ylabel("TFLOPS")
    fig.suptitle(f"cube_peak MMAD FLOPS per device ({mode})", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    out2 = os.path.join(args.out, f"flops_by_device_x-{args.x}.png")
    fig.savefig(out2, dpi=120)
    plt.close(fig)
    print("wrote", out2)


if __name__ == "__main__":
    main()
