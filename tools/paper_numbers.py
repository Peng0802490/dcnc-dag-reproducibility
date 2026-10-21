#!/usr/bin/env python3
"""Print exactly the numbers Section VII quotes, straight from the plotted CSVs.

For each figure panel: lambda-hat under the 0.95 completion gate, the completion
ratio there, the ratio at the first rejected rate, and the resulting multiples.
Anything the paper states about these curves should be copied from here.
"""
import csv
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else PACKAGE_ROOT / "results" / "plots"

PANELS = [
    ("Fig.3(a) driving / Milan", "driving_milan",
     [("Exact-K1.csv", "DCNC-DAG"), ("Heuristic.csv", "DCNC-DAG-H"),
      ("CTS.csv", "CTS"), ("Randomized.csv", "Randomized")]),
    ("Fig.3(b) driving / random", "driving_random",
     [("Exact-K1.csv", "DCNC-DAG"), ("Heuristic.csv", "DCNC-DAG-H"),
      ("CTS.csv", "CTS"), ("Randomized.csv", "Randomized")]),
    ("Fig.4(a) random DAGs / Milan", "random_milan",
     [("Exact-K1.csv", "DCNC-DAG"), ("Heuristic.csv", "DCNC-DAG-H"),
      ("CTS.csv", "CTS"), ("Randomized.csv", "Randomized")]),
    ("Fig.4(b) random DAGs / random", "random_random",
     [("Exact-K1.csv", "DCNC-DAG"), ("Heuristic.csv", "DCNC-DAG-H"),
      ("CTS.csv", "CTS"), ("Randomized.csv", "Randomized")]),
    ("Fig.4(c) random DAGs / RoofNet", "random_roofnet",
     [("Exact-K1.csv", "DCNC-DAG"), ("Heuristic.csv", "DCNC-DAG-H"),
      ("CTS.csv", "CTS"), ("Randomized.csv", "Randomized")]),
    ("Fig.4(d) random DAGs / FlockLab", "random_flocklab",
     [("Exact-K1.csv", "DCNC-DAG"), ("Heuristic.csv", "DCNC-DAG-H"),
      ("CTS.csv", "CTS"), ("Randomized.csv", "Randomized")]),
    ("Fig.5(a) frame length / Milan", "driving_milan_K",
     [("Exact-K%d.csv" % k, "T_f=%d" % k) for k in (1, 4, 16, 64, 256)]),
    ("Fig.5(b) frame length / random", "driving_random_K",
     [("Exact-K%d.csv" % k, "T_f=%d" % k) for k in (1, 4, 16, 64, 256)]),
]


def read(path):
    with path.open() as f:
        return [(float(r["total_arrival_rate"]), float(r["avg_delay_completed"]),
                 float(r["completion_ratio"])) for r in csv.DictReader(f)]


for title, d, curves in PANELS:
    print("=" * 78)
    print(title)
    lams, crs, nxt_crs = {}, {}, {}
    for fn, label in curves:
        p = ROOT / d / fn
        if not p.exists():
            print("   %-12s MISSING" % label)
            continue
        pts = read(p)
        ok = [x for x in pts if x[2] >= 0.95]
        if not ok:
            print("   %-12s never passes the 0.95 gate (best cr=%.3f)" % (label, max(x[2] for x in pts)))
            continue
        lam, _, cr = ok[-1]
        after = [x for x in pts if x[0] > lam]
        lams[label], crs[label] = lam, cr
        nxt_crs[label] = after[0][2] if after else None
        print("   %-12s lam95=%-8.4g cr=%-6.3f  first-rejected cr=%-7s  points=%-3d  peak delay=%.0f at r=%g"
              % (label, lam, cr,
                 ("%.3f" % after[0][2]) if after else "none plotted",
                 len(pts), max(x[1] for x in pts), pts[-1][0]))
    if "DCNC-DAG" in lams:
        base = lams["DCNC-DAG"]
        for other in ("DCNC-DAG-H", "CTS", "Randomized"):
            if other in lams:
                print("      DCNC-DAG / %-11s = %.2fx" % (other, base / lams[other]))
        if "DCNC-DAG-H" in lams:
            print("      DCNC-DAG-H retains %.0f%% of the exact threshold" % (100 * lams["DCNC-DAG-H"] / base))
    if lams and all(k.startswith("T_f") for k in lams):
        print("      lam95 by T_f: " + ", ".join("%s -> %.4g" % (k, lams[k]) for k in lams))
    if crs:
        print("      completion ratio at lam95 in [%.3f, %.3f]" % (min(crs.values()), max(crs.values())))
        vals = [v for v in nxt_crs.values() if v is not None]
        if vals:
            print("      completion ratio at the first rejected rate in [%.3f, %.3f]" % (min(vals), max(vals)))
