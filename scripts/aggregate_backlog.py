#!/usr/bin/env python3
"""Aggregate FIFO/NTO backlog trajectories."""
from __future__ import annotations

import csv
import math
import os
import statistics as st
import sys
from collections import defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE = os.path.join(ROOT, "scripts")
sys.path.insert(0, CODE)


DATA = os.environ["DCNC_FIFO_DATA_DIR"]



LAMBDAS_A = [0.50, 0.60, 0.70, 0.76, 0.80, 0.85, 0.90, 0.95]
LAMBDAS_B = [0.70, 0.80, 0.90]
TCRIT = {5: 2.776, 10: 2.262, 20: 2.093}


def tcrit(n):
    return TCRIT.get(n, 2.093 if n >= 20 else 2.262)


def load(path):
    with open(path) as f:
        return list(csv.DictReader(f))


rawA = load(os.path.join(DATA, "experiment_A_raw_trajectories.csv"))
rawB = load(os.path.join(DATA, "experiment_B_raw_trajectories.csv"))
print("rows: A=%d B=%d" % (len(rawA), len(rawB)))

AGG_COLS = ["experiment", "lambda", "policy", "time", "n_seeds", "mean_backlog",
            "median_backlog", "sd_backlog", "se_backlog", "ci95_low", "ci95_high",
            "q25_backlog", "q75_backlog"]


def aggregate(raw, out_path):
    g = defaultdict(list)
    for r in raw:
        g[(r["experiment"], float(r["lambda"]), r["policy"], int(r["time"]))].append(
            int(r["incomplete_requests"]))
    rows = []
    for k in sorted(g, key=lambda x: (x[1], x[2], x[3])):
        v = sorted(g[k])
        n = len(v)
        m = st.mean(v)
        sd = st.stdev(v) if n > 1 else 0.0
        se = sd / math.sqrt(n) if n > 1 else 0.0
        h = tcrit(n) * se
        rows.append(dict(zip(AGG_COLS, [k[0], k[1], k[2], k[3], n, m,
                                        st.median(v), sd, se, m - h, m + h,
                                        float(np.percentile(v, 25)),
                                        float(np.percentile(v, 75))])))
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=AGG_COLS); w.writeheader(); w.writerows(rows)
    print("%s: %d rows" % (os.path.basename(out_path), len(rows)))
    return rows


aggA = aggregate(rawA, os.path.join(DATA, "experiment_A_aggregate_trajectories.csv"))
aggB = aggregate(rawB, os.path.join(DATA, "experiment_B_aggregate_trajectories.csv"))

# ------------------------------------------------- per-run summary + slopes
runs = defaultdict(list)
for r in rawA + rawB:
    runs[(r["experiment"], float(r["lambda"]), int(r["seed"]), r["policy"])].append(
        (int(r["time"]), int(r["incomplete_requests"]), int(r["cum_arrivals"]),
         int(r["cum_completions"])))

PR_COLS = ["experiment", "lambda", "seed", "policy", "horizon",
           "final_cum_arrivals", "final_cum_completions", "final_backlog",
           "final_completed_throughput", "final_completion_ratio",
           "backlog_slope_last_half"]
per_run = []
for k in sorted(runs, key=lambda x: (x[0], x[1], x[3], x[2])):
    pts = sorted(runs[k])
    T = pts[-1][0]
    half = [p for p in pts if p[0] >= T / 2.0]
    xs = np.array([p[0] for p in half], dtype=float)
    ys = np.array([p[1] for p in half], dtype=float)
    slope = float(np.polyfit(xs, ys, 1)[0]) if len(xs) > 1 else 0.0
    a, kap = pts[-1][2], pts[-1][3]
    per_run.append(dict(zip(PR_COLS, [k[0], k[1], k[2], k[3], T, a, kap, a - kap,
                                      kap / float(T), (kap / float(a) if a else ""),
                                      slope])))
with open(os.path.join(DATA, "per_run_summary.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=PR_COLS); w.writeheader(); w.writerows(per_run)
print("per_run_summary.csv: %d rows" % len(per_run))

# ------------------------------------------------- aggregate final summary
FS_COLS = ["experiment", "lambda", "policy", "horizon", "n_seeds",
           "mean_final_backlog", "median_final_backlog", "sd_final_backlog",
           "ci95_low_final_backlog", "ci95_high_final_backlog",
           "mean_completion_ratio", "mean_completed_throughput",
           "mean_backlog_over_T", "mean_slope_last_half", "median_slope_last_half",
           "sd_slope_last_half", "ci95_low_slope", "ci95_high_slope",
           "fraction_positive_slope"]
gf = defaultdict(list)
for r in per_run:
    gf[(r["experiment"], r["lambda"], r["policy"])].append(r)

final_rows = []
for k in sorted(gf, key=lambda x: (x[0], x[1], x[2])):
    v = gf[k]
    n = len(v)
    fb = [x["final_backlog"] for x in v]
    sl = [x["backlog_slope_last_half"] for x in v]
    cr = [float(x["final_completion_ratio"]) for x in v if x["final_completion_ratio"] != ""]
    th = [x["final_completed_throughput"] for x in v]
    T = v[0]["horizon"]
    mb, sb = st.mean(fb), (st.stdev(fb) if n > 1 else 0.0)
    hb = tcrit(n) * sb / math.sqrt(n) if n > 1 else 0.0
    ms, ss = st.mean(sl), (st.stdev(sl) if n > 1 else 0.0)
    hs = tcrit(n) * ss / math.sqrt(n) if n > 1 else 0.0
    final_rows.append(dict(zip(FS_COLS, [
        k[0], k[1], k[2], T, n, mb, st.median(fb), sb, mb - hb, mb + hb,
        (st.mean(cr) if cr else ""), st.mean(th), mb / float(T),
        ms, st.median(sl), ss, ms - hs, ms + hs,
        sum(1 for x in sl if x > 0) / float(n)])))
with open(os.path.join(DATA, "aggregate_final_summary.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=FS_COLS); w.writeheader(); w.writerows(final_rows)
print("aggregate_final_summary.csv: %d rows" % len(final_rows))

# ------------------------------------------------- candidate rate table
CT_COLS = ["lambda", "NTO_mean_final_backlog", "FIFO_mean_final_backlog",
           "NTO_mean_slope_last_half", "NTO_slope_ci95_low", "NTO_slope_ci95_high",
           "FIFO_mean_slope_last_half", "FIFO_slope_ci95_low", "FIFO_slope_ci95_high",
           "NTO_mean_completion_ratio", "FIFO_mean_completion_ratio",
           "FIFO_fraction_positive_slope", "FIFO_over_NTO_final_backlog"]
idx = {(r["lambda"], r["policy"]): r for r in final_rows if r["experiment"] == "A"}
cand = []
for lam in LAMBDAS_A:
    n_, f_ = idx[(lam, "NTO")], idx[(lam, "FIFO")]
    ratio = (f_["mean_final_backlog"] / n_["mean_final_backlog"]
             if n_["mean_final_backlog"] else "")
    cand.append(dict(zip(CT_COLS, [
        lam, n_["mean_final_backlog"], f_["mean_final_backlog"],
        n_["mean_slope_last_half"], n_["ci95_low_slope"], n_["ci95_high_slope"],
        f_["mean_slope_last_half"], f_["ci95_low_slope"], f_["ci95_high_slope"],
        n_["mean_completion_ratio"], f_["mean_completion_ratio"],
        f_["fraction_positive_slope"], ratio])))
with open(os.path.join(DATA, "candidate_rate_table.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=CT_COLS); w.writeheader(); w.writerows(cand)
print("candidate_rate_table.csv: %d rows" % len(cand))

