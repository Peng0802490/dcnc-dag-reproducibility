#!/usr/bin/env python3
"""All figures for the FIFO/NTO backlog-timeline campaign."""
from __future__ import annotations

import csv
import os
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
FIG = os.path.join(ROOT, "figures")
os.makedirs(FIG, exist_ok=True)

COL = {"FIFO": "#d62728", "NTO": "#1f77b4"}
LAMBDAS_A = [0.50, 0.60, 0.70, 0.76, 0.80, 0.85, 0.90, 0.95]
LAMBDAS_B = [0.70, 0.80, 0.90]
STAGES = ["A", "B", "C", "E", "F", "G"]

plt.rcParams.update({
    "font.family": "serif", "font.size": 9, "axes.labelsize": 9,
    "legend.fontsize": 8, "xtick.labelsize": 8, "ytick.labelsize": 8,
    "pdf.fonttype": 42, "ps.fonttype": 42,
})


def tag(lam):
    return ("%.2f" % lam).replace(".", "p")


def save(fig, stem):
    for ext in ("pdf", "png"):
        p = os.path.join(FIG, "%s.%s" % (stem, ext))
        fig.savefig(p, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print("[write]", stem)


def load(n):
    with open(os.path.join(DATA, n)) as f:
        return list(csv.DictReader(f))


aggA, aggB = load("experiment_A_aggregate_trajectories.csv"), load("experiment_B_aggregate_trajectories.csv")
finals = load("aggregate_final_summary.csv")

TR = defaultdict(lambda: defaultdict(list))
for r in aggA:
    TR[("A", float(r["lambda"]))][r["policy"]].append(
        (int(r["time"]), float(r["mean_backlog"]), float(r["ci95_low"]), float(r["ci95_high"])))
for r in aggB:
    TR[("B", float(r["lambda"]))][r["policy"]].append(
        (int(r["time"]), float(r["mean_backlog"]), float(r["ci95_low"]), float(r["ci95_high"])))
for k in TR:
    for p in TR[k]:
        TR[k][p].sort()


def draw(ax, exp, lam, legend=True, xscale=1e6):
    for pol in ("NTO", "FIFO"):
        pts = TR[(exp, lam)][pol]
        t = np.array([p[0] for p in pts]) / xscale
        m = np.array([p[1] for p in pts])
        lo = np.array([p[2] for p in pts]); hi = np.array([p[3] for p in pts])
        ax.plot(t, m, "-", lw=1.3, color=COL[pol], label=pol)
        ax.fill_between(t, lo, hi, color=COL[pol], alpha=0.25, lw=0)
    ax.grid(alpha=0.22)
    if legend:
        ax.legend(frameon=False, loc="upper left")


# ----------------------------------------------------------------- A1
for lam in LAMBDAS_A:
    fig, ax = plt.subplots(figsize=(5.4, 3.5))
    draw(ax, "A", lam)
    ax.set_xlabel(r"Time $t$ ($\times 10^{6}$ slots)")
    ax.set_ylabel(r"Incomplete requests $I(t)$")
    ax.set_title(r"$\lambda=%.2f$, $B_0=0$, $T=2\times10^{6}$, 20 seeds; band = 95%% CI of the mean"
                 % lam, fontsize=7.5)
    save(fig, "A1_backlog_lambda_" + tag(lam))

# ----------------------------------------------------------------- A2
for mode in ("common_scale", "auto_scale"):
    fig, axes = plt.subplots(2, 4, figsize=(13.5, 6.0), sharex=True,
                             sharey=(mode == "common_scale"))
    for ax, lam in zip(axes.ravel(), LAMBDAS_A):
        draw(ax, "A", lam, legend=(lam == LAMBDAS_A[0]))
        ax.set_title(r"$\lambda=%.2f$" % lam, fontsize=8)
    for ax in axes[1]:
        ax.set_xlabel(r"$t$ ($\times 10^{6}$ slots)")
    for ax in axes[:, 0]:
        ax.set_ylabel(r"$I(t)$")
    fig.suptitle(r"$B_0=0$, $T=2\times10^{6}$, 20 seeds; bands = 95%% CI (%s)"
                 % mode.replace("_", " "), fontsize=9)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    save(fig, "A2_backlog_all_rates_" + mode)

# ----------------------------------------------------------------- A3, A4
fin = {(r["experiment"], float(r["lambda"]), r["policy"]): r for r in finals}
for stem, key, lo, hi, ylab, zero in [
        ("A3_final_backlog_vs_lambda", "mean_final_backlog",
         "ci95_low_final_backlog", "ci95_high_final_backlog",
         r"Mean final backlog $I(T)$", False),
        ("A4_backlog_slope_vs_lambda", "mean_slope_last_half",
         "ci95_low_slope", "ci95_high_slope",
         r"Mean backlog slope over the last half (requests/slot)", True)]:
    fig, ax = plt.subplots(figsize=(5.4, 3.5))
    for pol in ("NTO", "FIFO"):
        m = np.array([float(fin[("A", l, pol)][key]) for l in LAMBDAS_A])
        el = m - np.array([float(fin[("A", l, pol)][lo]) for l in LAMBDAS_A])
        eh = np.array([float(fin[("A", l, pol)][hi]) for l in LAMBDAS_A]) - m
        ax.errorbar(LAMBDAS_A, m, yerr=[el, eh], marker="o", ms=4, lw=1.4,
                    capsize=3, color=COL[pol], label=pol)
    if zero:
        ax.axhline(0.0, color="0.35", ls="--", lw=1.0)
    else:
        ax.set_yscale("symlog", linthresh=10)
    ax.set_xlabel(r"Arrival rate $\lambda$ (requests/slot)")
    ax.set_ylabel(ylab)
    ax.grid(alpha=0.22); ax.legend(frameon=False)
    save(fig, stem)

# ----------------------------------------------------------------- A5
rawA = load("experiment_A_raw_trajectories.csv")
seedtr = defaultdict(lambda: defaultdict(list))
for r in rawA:
    seedtr[(float(r["lambda"]), r["policy"])][int(r["seed"])].append(
        (int(r["time"]), int(r["incomplete_requests"])))
for lam in LAMBDAS_A:
    fig, ax = plt.subplots(figsize=(5.4, 3.5))
    for pol in ("NTO", "FIFO"):
        for s, pts in sorted(seedtr[(lam, pol)].items()):
            pts.sort()
            ax.plot([p[0] / 1e6 for p in pts], [p[1] for p in pts],
                    "-", lw=0.5, color=COL[pol], alpha=0.30)
        pts = TR[("A", lam)][pol]
        ax.plot([p[0] / 1e6 for p in pts], [p[1] for p in pts],
                "-", lw=1.8, color=COL[pol], label=pol + " mean")
    ax.set_xlabel(r"Time $t$ ($\times 10^{6}$ slots)")
    ax.set_ylabel(r"Incomplete requests $I(t)$")
    ax.set_title(r"$\lambda=%.2f$: 20 individual seeds (thin) and the mean (thick)" % lam,
                 fontsize=7.5)
    ax.grid(alpha=0.22); ax.legend(frameon=False, loc="upper left")
    save(fig, "A5_seed_trajectories_lambda_" + tag(lam))

# ----------------------------------------------------------------- B1
for lam in LAMBDAS_B:
    fig, ax = plt.subplots(figsize=(5.4, 3.5))
    draw(ax, "B", lam, xscale=1e6)
    ax.set_xlabel(r"Time $t$ ($\times 10^{6}$ slots)")
    ax.set_ylabel(r"Incomplete requests $I(t)$")
    ax.set_title(r"$\lambda=%.2f$, $B_0=0$, $T=10^{7}$, 10 seeds; band = 95%% CI" % lam,
                 fontsize=7.5)
    save(fig, "B1_long_horizon_lambda_" + tag(lam))

fig, axes = plt.subplots(1, 3, figsize=(13.5, 3.4), sharex=True)
for ax, lam in zip(axes, LAMBDAS_B):
    draw(ax, "B", lam, legend=(lam == LAMBDAS_B[0]))
    ax.set_title(r"$\lambda=%.2f$" % lam, fontsize=8)
    ax.set_xlabel(r"$t$ ($\times 10^{6}$ slots)")
axes[0].set_ylabel(r"$I(t)$")
fig.suptitle(r"$B_0=0$, $T=10^{7}$, 10 seeds; bands = 95% CI of the mean", fontsize=9)
fig.tight_layout(rect=[0, 0, 1, 0.94])
save(fig, "B1_long_horizon_summary")

# ----------------------------------------------------------------- B2
for lam in LAMBDAS_B:
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 3.4))
    for pol in ("NTO", "FIFO"):
        ptsA = TR[("A", lam)][pol]
        axes[0].plot([p[0] / 1e6 for p in ptsA], [p[1] for p in ptsA],
                     "-", lw=1.3, color=COL[pol], label=pol)
        ptsB = TR[("B", lam)][pol]
        axes[1].plot([p[0] / 1e6 for p in ptsB], [p[1] for p in ptsB],
                     "-", lw=1.3, color=COL[pol], label=pol)
    axes[0].set_title(r"Experiment A: $T=2\times10^{6}$", fontsize=8)
    axes[1].set_title(r"Experiment B: $T=10^{7}$", fontsize=8)
    for ax in axes:
        ax.set_xlabel(r"$t$ ($\times 10^{6}$ slots)")
        ax.grid(alpha=0.22)
    axes[0].set_ylabel(r"$I(t)$")
    axes[0].legend(frameon=False, loc="upper left")
    fig.suptitle(r"$\lambda=%.2f$, $B_0=0$" % lam, fontsize=9)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    save(fig, "B2_short_vs_long_lambda_" + tag(lam))

# ----------------------------------------------------------------- C1
stage_tr = defaultdict(lambda: defaultdict(list))
for r in rawA:
    lam = float(r["lambda"])
    if lam in LAMBDAS_B and r["policy"] == "FIFO":
        stage_tr[lam][int(r["time"])].append([int(r["stage_%s_count" % s]) for s in STAGES])
cmap = plt.get_cmap("tab10")
for lam in LAMBDAS_B:
    fig, ax = plt.subplots(figsize=(5.4, 3.5))
    times = sorted(stage_tr[lam])
    arr = np.array([np.mean(stage_tr[lam][t], axis=0) for t in times])
    for i, s in enumerate(STAGES):
        ax.plot(np.array(times) / 1e6, arr[:, i], "-", lw=1.2, color=cmap(i),
                label="stage %s" % s)
    ax.set_xlabel(r"Time $t$ ($\times 10^{6}$ slots)")
    ax.set_ylabel("Mean requests at stage")
    ax.set_title(r"FIFO per-stage occupancy, $\lambda=%.2f$, 20 seeds" % lam, fontsize=8)
    ax.grid(alpha=0.22); ax.legend(frameon=False, ncol=2, fontsize=7)
    save(fig, "C1_stage_backlog_FIFO_lambda_" + tag(lam))

print("figures written to", FIG)
