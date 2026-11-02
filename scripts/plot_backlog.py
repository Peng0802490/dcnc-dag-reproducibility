#!/usr/bin/env python3
"""Fig. 6: incomplete-request backlog under NTO and FIFO at lambda = 0.80.

IEEE single-column figure: one linear main axes plus a top-left inset that
enlarges the NTO backlog.  Reads the aggregated experiment-B trajectories and
writes a 600 dpi PNG.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager

HERE = Path(os.environ.get("DCNC_FIGURE_OUTPUT", str(Path(__file__).resolve().parents[1] / "results/figures")))
HERE.mkdir(parents=True, exist_ok=True)
SRC = Path(os.environ["DCNC_FIFO_DATA"])
STEM = os.environ.get("FIG6_STEM", "fig6_backlog_lambda_0p80")

LAMBDA = 0.80
C_NTO = "#0072B2"      # dark blue
C_FIFO = "#D55E00"     # vermillion
CI_ALPHA = 0.14

# ------------------------------------------------------------------ fonts
for cand in (Path("C:/Windows/Fonts/times.ttf"), HERE / "fonts" / "times.ttf"):
    if cand.exists():
        try:
            font_manager.fontManager.addfont(str(cand))
        except Exception:
            pass
_avail = {f.name for f in font_manager.fontManager.ttflist}
SERIF = "Times New Roman" if "Times New Roman" in _avail else "DejaVu Serif"

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": [SERIF],
    "mathtext.fontset": "custom",
    "mathtext.rm": SERIF,
    "mathtext.it": SERIF + ":italic",
    "mathtext.bf": SERIF + ":bold",
    "axes.labelsize": 8,
    "xtick.labelsize": 7.5,
    "ytick.labelsize": 7.5,
    "legend.fontsize": 7.5,
    "axes.linewidth": 0.7,
    "xtick.direction": "in",
    "ytick.direction": "in",
    "xtick.major.width": 0.7,
    "ytick.major.width": 0.7,
    "xtick.major.size": 2.6,
    "ytick.major.size": 2.6,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "svg.fonttype": "none",
    "figure.facecolor": "white",
    "axes.facecolor": "white",
})

# ------------------------------------------------------------------- data
series = {}
with SRC.open() as f:
    for r in csv.DictReader(f):
        if abs(float(r["lambda"]) - LAMBDA) > 1e-9:
            continue
        series.setdefault(r["policy"], []).append(
            (int(r["time"]), float(r["mean_backlog"]),
             float(r["ci95_low"]), float(r["ci95_high"])))

curves = {}
for pol, pts in series.items():
    pts.sort()
    t = np.array([0.0] + [p[0] for p in pts])          # explicit (0, 0) start
    m = np.array([0.0] + [p[1] for p in pts])
    lo = np.maximum(0.0, np.array([0.0] + [p[2] for p in pts]))   # backlog is non-negative
    hi = np.array([0.0] + [p[3] for p in pts])
    curves[pol] = (t, m, lo, hi)

# ----------------------------------------------------------------- figure
fig = plt.figure(figsize=(3.45, 2.35))
ax = fig.add_axes([0.155, 0.175, 0.825, 0.805])

for pol, colour, z in (("FIFO", C_FIFO, 2), ("NTO", C_NTO, 3)):
    t, m, lo, hi = curves[pol]
    x = t / 1e6
    ax.fill_between(x, lo / 1e6, hi / 1e6, color=colour, alpha=CI_ALPHA,
                    lw=0, zorder=z)
    ax.plot(x, m / 1e6, "-", color=colour, lw=1.6, solid_joinstyle="round",
            zorder=z + 2, label=pol)

ax.set_xlim(0, 10)
# small negative margin so the NTO curve, which sits at about 17 requests
# (7e-6 of the axis range), is lifted clear of the bottom spine.
# No data value is changed and the ticks still start at zero.
ax.set_ylim(-0.075, 2.35)
ax.set_xticks([0, 2, 4, 6, 8, 10])
ax.set_yticks([0, 0.5, 1.0, 1.5, 2.0])
ax.set_xlabel(r"Time $t$ ($\times 10^{6}$ slots)")
ax.set_ylabel(r"Incomplete requests $I(t)$ ($\times 10^{6}$)")
ax.tick_params(pad=2.0)
ax.grid(True, which="major", color="0.85", lw=0.35, zorder=0)
ax.set_axisbelow(True)

handles, labels = ax.get_legend_handles_labels()
order = [labels.index("NTO"), labels.index("FIFO")]      # NTO first
# lower right, lifted just clear of the NTO curve
ax.legend([handles[i] for i in order], [labels[i] for i in order],
          loc="lower right", bbox_to_anchor=(0.995, 0.055),
          frameon=False, handlelength=1.6, labelspacing=0.35)

# ------------------------------------------------------------------ inset
# lowered so the inset title clears the main top spine
axi = ax.inset_axes([0.150, 0.560, 0.375, 0.340])
t, m, lo, hi = curves["NTO"]
axi.fill_between(t / 1e6, lo, hi, color=C_NTO, alpha=CI_ALPHA, lw=0)
axi.plot(t / 1e6, m, "-", color=C_NTO, lw=0.65)
axi.set_xlim(0, 10)
axi.set_ylim(0, 50)
axi.set_xticks([0, 5, 10])
axi.set_yticks([0, 20, 40])
axi.tick_params(labelsize=6.5, width=0.6, length=1.9, direction="in", pad=1.6)
axi.set_ylabel(r"$I(t)$", fontsize=6.5, labelpad=1.0)
axi.set_title("NTO (zoom)", fontsize=7, pad=2.0)
for sp in axi.spines.values():
    sp.set_linewidth(0.6)
axi.grid(True, color="0.90", lw=0.3)
axi.set_axisbelow(True)
axi.set_facecolor("white")
axi.patch.set_alpha(1.0)

for ext, kw in (("png", {"dpi": 600}),):
    out = HERE / ("%s.%s" % (STEM, ext))
    fig.savefig(out, **kw)
    print("[write]", out)
plt.close(fig)
print("serif font in use:", SERIF)
