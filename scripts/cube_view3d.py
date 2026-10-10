#!/usr/bin/env python3
"""Interactive 3D viewer for cube_peak sweep results (surface version).

Plots FLOPS (z) over m (x) and n (y) as a continuous surface, with the K
dimension (contraction depth) on a slider (the "time" axis).  A semi-transparent
plane marks the global peak FLOPS so you can see how close each k gets to the
ceiling.  All three axes are logarithmic.  Drag to rotate, scroll to zoom.

The surface is interpolated (scipy.griddata) from the swept (m, n) points, which
sit on a regular 16-multiple grid but have holes from the buffer/coverage
constraints.  Interpolation is done in log(m)-log(n) space so the log spacing is
respected.

Colour is a turbo gradient keyed to the RAW FLOPS value (log normalised), i.e.
the same gradient scheme as cube_volume.py but smooth instead of binned.

Requires an interactive matplotlib backend (TkAgg), scipy, and a display.

Usage:
    python3 scripts/cube_view3d.py [--root out/cube-sweep] [--arch 3510] [--dtype half]
"""
import argparse
import csv
import os

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LogNorm, Normalize  # noqa: E402
from matplotlib.widgets import Slider  # noqa: E402
from mpl_toolkits.mplot3d import Axes3D  # noqa: E402,F401
from scipy.interpolate import griddata  # noqa: E402

CLOCK_HZ = 1.8e9
# Theoretical cube peak in TFLOPS (MAC/cycle * 2 * clock).  half/bf16/int8 do one
# fractal/cycle (4096/4096/8192 MAC/cyc); float is 1/2 (2201) and 1/8 (3510) of
# the fp16 rate (measured saturation — no public float MAC-rate spec).
MAC_PER_CYC = {"half": 4096, "bf16": 4096, "int8": 8192,
               "float": {"2201": 1024, "3510": 256}}


def theoretical_tflops(arch, dtype):
    m = MAC_PER_CYC[dtype]
    if isinstance(m, dict):
        m = m[arch]
    return 2.0 * m * CLOCK_HZ / 1e12


def load(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if r.get("tflops") in (None, ""):
                continue
            rows.append((int(r["m"]), int(r["k"]), int(r["n"]), float(r["tflops"])))
    return rows


def nice_log_ticks(vmin, vmax):
    """1-2-5 log tick values in [vmin, vmax] (for relabeling a log10 axis)."""
    ticks = []
    exp = int(np.floor(np.log10(vmin)))
    while 10 ** exp <= vmax:
        for mult in (1.0, 2.0, 5.0):
            v = mult * 10 ** exp
            if vmin <= v <= vmax:
                ticks.append(v)
        exp += 1
    return ticks


def pow2_ticks(vmin, vmax):
    """Powers of two in [vmin, vmax] (for relabeling the m/n log axes)."""
    ticks = []
    p = int(np.ceil(np.log2(vmin)))
    while (1 << p) <= vmax:
        ticks.append(1 << p)
        p += 1
    return ticks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="out/cube-sweep")
    ap.add_argument("--arch", default="3510", choices=["2201", "3510"])
    ap.add_argument("--dtype", default="half", choices=["half", "float", "int8", "bf16"])
    args = ap.parse_args()

    path = os.path.join(args.root, args.arch, f"{args.dtype}.csv")
    if not os.path.exists(path):
        raise SystemExit(f"no CSV at {path} (run scripts/cube-sweep.sh first)")

    rows = load(path)
    ks = sorted({r[1] for r in rows})
    by_k = {k: [] for k in ks}
    for m, k, n, tf in rows:
        by_k[k].append((m, n, tf))

    max_flops = max(r[3] for r in rows)
    min_flops = min(r[3] for r in rows)
    theo_peak = theoretical_tflops(args.arch, args.dtype)
    mmin, mmax = min(r[0] for r in rows), max(r[0] for r in rows)
    nmin, nmax = min(r[2] for r in rows), max(r[2] for r in rows)

    # Log-domain axis bounds.
    lmmin, lmmax = np.log10(mmin), np.log10(mmax)
    lnmin, lnmax = np.log10(nmin), np.log10(nmax)
    lzmin = np.log10(min_flops * 0.9)
    lzmax = np.log10(max_flops * 1.1)

    fig = plt.figure(figsize=(11, 8))
    ax = fig.add_subplot(111, projection="3d")

    # One shared turbo colour scale (log on the raw FLOPS value) across all k.
    # The colorbar lives on its own axes and survives ax.clear().
    norm = LogNorm(vmin=min_flops, vmax=max_flops)
    mappable = plt.cm.ScalarMappable(norm=norm, cmap="turbo")
    mappable.set_array([])
    fig.colorbar(mappable, ax=ax, shrink=0.5, pad=0.1, label="TFLOPS")

    # Grids are uniform in log(m)/log(n) space (80 x 80).
    lm_grid = np.linspace(lmmin, lmmax, 80)
    ln_grid = np.linspace(lnmin, lnmax, 80)

    # Surface colour uses a linear norm over log10(FLOPS), which is identical to
    # LogNorm on the raw FLOPS but avoids the double-log from feeding log10(F)
    # into a LogNorm.
    lnorm = Normalize(vmin=np.log10(min_flops), vmax=np.log10(max_flops))

    def draw(k):
        # ax.clear() is the only reliable way to drop the previous surface:
        # matplotlib 3.10's ax.collections is an ArtistList with no .remove(),
        # and Poly3DCollection.remove() breaks after a TkAgg depth re-order.
        ax.clear()
        ax.set_xlim(lmmin, lmmax)
        ax.set_ylim(lnmin, lnmax)
        ax.set_zlim(lzmin, lzmax)

        # Peak plane in log coords.
        Xp, Yp = np.meshgrid(np.linspace(lmmin, lmmax, 4), np.linspace(lnmin, lnmax, 4))
        ax.plot_surface(Xp, Yp, np.full_like(Xp, np.log10(theo_peak)),
                        alpha=0.20, color="red")

        ax.set_xlabel("m")
        ax.set_ylabel("n")
        ax.set_zlabel("TFLOPS (log)")

        zticks = nice_log_ticks(min_flops, max_flops)
        ax.set_zticks([np.log10(v) for v in zticks])
        ax.set_zticklabels([f"{v:g}" for v in zticks])

        mticks = pow2_ticks(mmin, mmax)
        nticks = pow2_ticks(nmin, nmax)
        ax.set_xticks([np.log10(v) for v in mticks])
        ax.set_xticklabels([f"{v:g}" for v in mticks])
        ax.set_yticks([np.log10(v) for v in nticks])
        ax.set_yticklabels([f"{v:g}" for v in nticks])

        pts = by_k[k]
        m = np.array([p[0] for p in pts], float)
        n = np.array([p[1] for p in pts], float)
        t = np.array([p[2] for p in pts], float)

        LMI, LNI = np.meshgrid(lm_grid, ln_grid)
        F = griddata((np.log10(m), np.log10(n)), t, (LMI, LNI), method="linear")
        ax.plot_surface(LMI, LNI, np.log10(F), cmap="turbo", norm=lnorm, alpha=0.95)
        ax.set_title(f"{args.arch} {args.dtype}   k = {k}   (theoretical peak = {theo_peak:.2f} TFLOPS)")

    ax_slider = fig.add_axes([0.18, 0.02, 0.64, 0.03])
    slider = Slider(
        ax_slider, "k", ks[0], ks[-1], valinit=ks[0], valstep=16, valfmt="%d",
    )

    def update(val):
        k = min(ks, key=lambda x: abs(x - val))
        draw(k)
        fig.canvas.draw_idle()

    slider.on_changed(update)
    draw(ks[0])
    plt.show()


if __name__ == "__main__":
    main()
