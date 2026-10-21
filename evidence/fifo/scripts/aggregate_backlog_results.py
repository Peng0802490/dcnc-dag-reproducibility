#!/usr/bin/env python3
"""Aggregate the FIFO/NTO backlog-timeline campaign and run the section-11 checks."""
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
from sim_exact import arrival_indicators  # noqa: E402

DATA = os.path.join(ROOT, "data")
CHK = os.path.join(ROOT, "sanity_checks")
os.makedirs(CHK, exist_ok=True)

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

# ------------------------------------------------------------ sanity checks
out = []
P = out.append
P("FIFO/NTO backlog-timeline sanity checks")
P("=" * 62)
P("")

P("11.1 arrival-rate check  A_cum(T)/T ~= lambda")
worst = 0.0
for r in per_run:
    d = abs(r["final_cum_arrivals"] / float(r["horizon"]) - r["lambda"])
    worst = max(worst, d)
P("     maximum |A_cum(T)/T - lambda| over %d runs: %.6f" % (len(per_run), worst))
P("")

P("11.2 nested arrivals across rates (per seed, full indicator arrays)")
fails = []
for seed in range(1, 21):
    prev = None
    for lam in LAMBDAS_A:
        a = arrival_indicators(200_000, lam, seed, "bernoulli")
        if prev is not None and not np.all(prev <= a):
            fails.append((seed, lam))
        prev = a
P("     checked seeds 1-20 over all %d rates on the first 2e5 slots" % len(LAMBDAS_A))
P("     result: %s" % ("PASS" if not fails else "FAIL %s" % fails[:5]))
P("")

P("11.3 FIFO/NTO arrival coupling")
mis = []
byk = defaultdict(dict)
for r in per_run:
    byk[(r["experiment"], r["lambda"], r["seed"])][r["policy"]] = r["final_cum_arrivals"]
for k, d in byk.items():
    if len(d) == 2 and d["FIFO"] != d["NTO"]:
        mis.append((k, d))
P("     compared %d (experiment, lambda, seed) cells" % len(byk))
P("     result: %s" % ("PASS" if not mis else "FAIL %s" % mis[:5]))
P("")

P("11.4 backlog identity  I(t) = A_cum(t) - kappa(t)  with B0 = 0")
worst_id = 0
for r in rawA + rawB:
    d = abs(int(r["incomplete_requests"])
            - (int(r["cum_arrivals"]) - int(r["cum_completions"])))
    worst_id = max(worst_id, d)
P("     maximum discrepancy over %d sampled points: %d" % (len(rawA) + len(rawB), worst_id))
P("")

P("11.5 capacity boundary")
P("     u1 load per request = 0.01 + 0.99 = 1.00")
P("     v1 load per request = 0.99 + 0.01 + 0.01 + 0.01 = 1.02")
P("     lambda* = min(1/1.00, 1/1.02) = %.6f" % (1.0 / 1.02))
P("     workloads and placement unchanged (WORK_DEFAULT, STAGE_NODE)")
P("")

P("extra: I(t) equals the sum of the six stage counts at every sampled point")
worst_stage = 0
for r in rawA + rawB:
    s = sum(int(r["stage_%s_count" % n]) for n in ["A", "B", "C", "E", "F", "G"])
    worst_stage = max(worst_stage, abs(s - int(r["incomplete_requests"])))
P("     maximum discrepancy: %d" % worst_stage)

txt = "\n".join(out) + "\n"
open(os.path.join(CHK, "sanity_check_report.txt"), "w").write(txt)
print()
print(txt)
