#!/usr/bin/env python3
"""3D volume of cube under-utilization.

Plots every (m, k, n) point whose cube utilization is below a threshold
(fraction of the best FLOPS this arch/dtype reaches). All three axes are
log-scale; points are colored by utilization. Points at or above the threshold
are drawn as a faint gray backdrop so the under-utilized "volume" stands out.

Run on the host (needs matplotlib; the container image has none):

    python3 scripts/cube_volume.py --arch 3510 --dtype half
    python3 scripts/cube_volume.py --arch 2201 --dtype float --threshold 0.9
"""

import argparse
import csv
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm
from matplotlib.lines import Line2D
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401  (registers the 3d projection)

DTYPES = ("half", "float", "int8", "bf16")


def load_csv(root, arch, dtype):
    path = os.path.join(root, arch, f"{dtype}.csv")
    if not os.path.exists(path):
        sys.exit(f"no CSV at {path}")
    ms, ks, ns, tfs = [], [], [], []
    with open(path) as fh:
        for r in csv.DictReader(fh):
            if not r.get("tflops"):
                continue
            ms.append(int(r["m"]))
            ks.append(int(r["k"]))
            ns.append(int(r["n"]))
            tfs.append(float(r["tflops"]))
    if not tfs:
        sys.exit(f"no data rows in {path}")
    return (np.asarray(ms, dtype=float),
            np.asarray(ks, dtype=float),
            np.asarray(ns, dtype=float),
            np.asarray(tfs, dtype=float))


def log_ticks(lo, hi):
    """Powers of two in [lo, hi] for use as log-axis tick values."""
    out = []
    v = 1
    while v <= hi:
        if v >= lo:
            out.append(v)
        v *= 2
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arch", required=True, choices=("2201", "3510"))
    ap.add_argument("--dtype", required=True, choices=DTYPES)
    ap.add_argument("--threshold", type=float, default=0.95,
                    help="cube utilization threshold (fraction of peak); default 0.95")
    ap.add_argument("--root", default="out/cube-sweep")
    ap.add_argument("--out", default=None,
                    help="PNG output path; default <root>/<arch>/volume_<dtype>.png")
    ap.add_argument("--no-show", action="store_true",
                    help="only write the PNG, do not open an interactive window")
    args = ap.parse_args()

    if not 0.0 < args.threshold <= 1.0:
        sys.exit("--threshold must be in (0, 1]")

    m, k, n, tf = load_csv(args.root, args.arch, args.dtype)
    peak = float(tf.max())
    util = tf / peak
    sub = util < args.threshold

    # matplotlib 3d axes do NOT support set_xscale("log")/etc. (produces broken
    # projection, missing points, flat grey box). Instead plot log10() of each
    # coordinate on a LINEAR 3d axis and relabel ticks with the real values.
    lm = np.log10(m)
    lk = np.log10(k)
    ln = np.log10(n)

    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(111, projection="3d")

    # Discrete color bands for the under-utilized volume (several distinct colors).
    nbins = 6
    boundaries = np.linspace(0.0, args.threshold, nbins + 1)
    cmap = plt.cm.turbo
    norm = BoundaryNorm(boundaries, cmap.N)

    # One scatter collection so every point depth-sorts together. Two separate
    # scatters render as two independent layers and can wrongly occlude each other
    # while rotating (that's what made saturated points vanish). Saturated -> grey
    # at the user's chosen opacity; under-utilized -> turbo, binned by utilization.
    rgba = np.empty((m.size, 4))
    rgba[:, :3] = 0.55          # grey
    rgba[:, 3] = 0.35           # opacity
    if sub.any():
        rgba[sub] = cmap(norm(util[sub]))
    ax.scatter(lm, ln, lk, c=rgba, s=14, depthshade=False)

    mappable = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    mappable.set_array([])
    cb = fig.colorbar(mappable, ax=ax, pad=0.12, shrink=0.55,
                      label="utilization (fraction of peak)")
    cb.set_ticks(boundaries)
    cb.set_ticklabels([f"{b:.2f}" for b in boundaries])

    ax.legend(handles=[
        Line2D([], [], marker="o", linestyle="", markerfacecolor="0.55",
               markeredgecolor="0.15", markersize=7,
               label=f"util >= {args.threshold:g}"),
        Line2D([], [], marker="o", linestyle="", markerfacecolor="0.65",
               markersize=7, label=f"util < {args.threshold:g}"),
    ], loc="upper left")

    for axis, vals, label in (
        (ax.xaxis, log_ticks(m.min(), m.max()), "m (log)"),
        (ax.yaxis, log_ticks(n.min(), n.max()), "n (log)"),
        (ax.zaxis, log_ticks(k.min(), k.max()), "k (log)"),
    ):
        axis.set_ticks([np.log10(v) for v in vals])
        axis.set_ticklabels([str(v) for v in vals])
        axis.set_label_text(label)

    ax.set_xlim(np.log10(8.0), np.log10(float(m.max()) * 2))
    ax.set_ylim(np.log10(8.0), np.log10(float(n.max()) * 2))
    ax.set_zlim(np.log10(8.0), np.log10(float(k.max()) * 2))

    n_sub = int(sub.sum())
    n_tot = int(m.size)
    ax.set_title(
        f"cube under-utilization  arch={args.arch} dtype={args.dtype}\n"
        f"util < {args.threshold:g}: {n_sub}/{n_tot} points   (peak = {peak:.2f} TFLOPS)"
    )

    out = args.out or os.path.join(args.root, args.arch, f"volume_{args.dtype}.png")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"wrote {out}  (under-utilized {n_sub}/{n_tot}, peak {peak:.2f} TFLOPS)")
    if not args.no_show:
        plt.show()


if __name__ == "__main__":
    main()
