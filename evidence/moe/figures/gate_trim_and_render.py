#!/usr/bin/env python3
"""Build the plot CSV with the canonical gate_trim rule and render the figures
with the published MoE plotting script, so the style matches Fig. 4(c)-(d)."""
import csv
import os
import shutil
import subprocess
from collections import defaultdict

DELIV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIGDIR = os.path.join(DELIV, "figures")
os.makedirs(FIGDIR, exist_ok=True)


def gate_trim(points, gate=0.95):
    """Verbatim rule from tools/build_plot_csvs.py: keep up to lambda-hat plus
    at most one rejected point, and drop that point when its delay does not
    exceed the delay at lambda-hat (survivorship)."""
    ok = [i for i, pt in enumerate(points) if pt[2] >= gate]
    if not ok:
        return points
    last = ok[-1]
    if last + 1 < len(points) and points[last + 1][1] > points[last][1]:
        return points[:last + 2]
    return points[:last + 1]


rows = list(csv.DictReader(open(os.path.join(DELIV, "summary", "delay_curve_data.csv"))))
by = defaultdict(list)
for r in rows:
    by[(r["workload"], r["policy"])].append(
        (float(r["arrival_rate"]), float(r["avg_delay_completed"]), float(r["completion_ratio"])))

out = []
print("curve extents after gate_trim:")
for key in sorted(by):
    pts = sorted(by[key])
    kept = gate_trim(pts)
    print("   %-16s %-11s  %2d/%2d points, up to rate %.3f (ratio %.4f)"
          % (key[0], key[1], len(kept), len(pts), kept[-1][0], kept[-1][2]))
    for rate, delay, ratio in kept:
        out.append({"workload": key[0], "policy": key[1],
                    "arrival_rate": rate, "avg_delay_completed": delay})

csv_path = os.path.join(FIGDIR, "skewed_moe_completed_delay_plot_data.csv")
with open(csv_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["workload", "policy", "arrival_rate", "avg_delay_completed"])
    w.writeheader()
    w.writerows(out)
print("\nplot CSV:", csv_path, "(%d rows)" % len(out))

# Reuse the plotting script shipped beside this file.
script = "02_plot_skewed_moe_completed_delay_from_csv.py"
print("\nrunning published plotting script ...")
p = subprocess.run(["python", script], cwd=FIGDIR, capture_output=True, text=True)
print(p.stdout[-2500:])
if p.returncode != 0:
    print("STDERR:", p.stderr[-2500:])
print("rc =", p.returncode)
