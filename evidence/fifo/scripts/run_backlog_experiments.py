#!/usr/bin/env python3
"""FIFO/NTO backlog-timeline campaign (experiments A and B).

Instance, mapping, workloads, capacities, scheduler definitions and the arrival
process are those of the existing re-entrant simulator; only B0, the horizon,
the sampled rates and the sampling interval are set by the requirements
document.  Arrivals come from a lambda-independent uniform stream thresholded at
lambda, so a seed's sample paths are nested in lambda and are shared by FIFO and
NTO.

Time convention: sample i is taken after every event of slot t = i * dt is
resolved, and is reported at time = t + 1 (slots elapsed).  A final sample at
time = T is appended from the run totals so the horizon itself is always present.
"""
from __future__ import annotations

import csv
import os
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sim_exact import simulate, STAGE_NODE, WORK_DEFAULT  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data")
os.makedirs(OUT, exist_ok=True)

STAGE_NAMES = ["A", "B", "C", "E", "F", "G"]
LAMBDAS_A = [0.50, 0.60, 0.70, 0.76, 0.80, 0.85, 0.90, 0.95]
LAMBDAS_B = [0.70, 0.80, 0.90]
SEEDS_A = list(range(1, 21))
SEEDS_B = list(range(1, 11))
POLICIES = ("FIFO", "NTO")

COLS = (["experiment", "lambda", "seed", "policy", "time", "cum_arrivals",
         "cum_completions", "incomplete_requests", "completed_throughput",
         "completion_ratio", "unfinished_workload_total",
         "unfinished_workload_u1", "unfinished_workload_v1"]
        + ["stage_%s_count" % s for s in STAGE_NAMES])


def one_run(job):
    exp, lam, seed, pol, T, dt = job
    res = simulate(lam=lam, seed=seed, policy=pol, T=T, M0=0, arith="int",
                   arrivals="bernoulli", n_segments=20, sample_every=dt)
    stage = res["sample_stage"]
    kap = res["sample_completed"]
    arr = res["sample_arrivals"]
    rows = []
    n = len(kap)
    for i in range(n):
        t = i * dt + 1                      # slots elapsed after slot i*dt
        counts = [int(x) for x in stage[i]]
        wl = [c * w for c, w in zip(counts, WORK_DEFAULT)]
        u1 = sum(x for x, nd in zip(wl, STAGE_NODE) if nd == 0)
        v1 = sum(x for x, nd in zip(wl, STAGE_NODE) if nd == 1)
        a, k = int(arr[i]), int(kap[i])
        rows.append([exp, lam, seed, pol, t, a, k, a - k,
                     k / float(t), (k / float(a) if a else ""),
                     round(u1 + v1, 6), round(u1, 6), round(v1, 6)] + counts)
    # final sample at the horizon itself
    counts = [int(x) for x in res["stage_count"]]
    wl = [c * w for c, w in zip(counts, WORK_DEFAULT)]
    u1 = sum(x for x, nd in zip(wl, STAGE_NODE) if nd == 0)
    v1 = sum(x for x, nd in zip(wl, STAGE_NODE) if nd == 1)
    a, k = int(res["arrivals_total"]), int(res["completed"])
    rows.append([exp, lam, seed, pol, T, a, k, a - k,
                 k / float(T), (k / float(a) if a else ""),
                 round(u1 + v1, 6), round(u1, 6), round(v1, 6)] + counts)
    return rows


def build(exp, lams, seeds, T, dt):
    return [(exp, lam, s, pol, T, dt)
            for lam in lams for s in seeds for pol in POLICIES]


def run(exp, jobs, path, workers):
    print("%s: %d runs -> %s" % (exp, len(jobs), path), flush=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        done = 0
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for rows in ex.map(one_run, jobs, chunksize=1):
                w.writerows(rows)
                done += 1
                if done % 40 == 0:
                    print("   %d/%d" % (done, len(jobs)), flush=True)
    print("%s written" % path, flush=True)


if __name__ == "__main__":
    workers = int(os.environ.get("BACKLOG_WORKERS", "60"))
    stage = sys.argv[1] if len(sys.argv) > 1 else "AB"
    if "A" in stage:
        run("A", build("A", LAMBDAS_A, SEEDS_A, 2_000_000, 2_000),
            os.path.join(OUT, "experiment_A_raw_trajectories.csv"), workers)
    if "B" in stage:
        run("B", build("B", LAMBDAS_B, SEEDS_B, 10_000_000, 10_000),
            os.path.join(OUT, "experiment_B_raw_trajectories.csv"), workers)
    print("ALL_DONE_BACKLOG", flush=True)
