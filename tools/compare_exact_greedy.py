#!/usr/bin/env python3
"""Side-by-side exact vs greedy on each candidate config, averaged over seeds.

Reports the seed-averaged completion ratio at every swept rate plus the 0.95-gate
threshold for each solver, so the question "does an exact minimum-cost mapping
actually buy throughput on this instance" gets a number rather than an eyeball.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

acc = defaultdict(list)
for line in Path(sys.argv[1]).read_text().splitlines():
    if not line.strip():
        continue
    r = json.loads(line)
    if r.get("status") != "ok":
        continue
    acc[(r["case"], r["solver"], float(r["rate"]))].append(
        (float(r["completion_ratio"]), float(r["avg_delay_completed"])))


def curve(case, solver):
    out = {}
    for (c, s, rate), v in acc.items():
        if c == case and s == solver:
            out[rate] = (sum(x[0] for x in v) / len(v), sum(x[1] for x in v) / len(v), len(v))
    return dict(sorted(out.items()))


def lam(c):
    ok = [r for r, v in c.items() if v[0] >= 0.95]
    return ok[-1] if ok else None


for case in sorted({k[0] for k in acc}):
    e, g = curve(case, "exact_dp"), curve(case, "greedy")
    le, lg = lam(e), lam(g)
    ratio = ("%.2fx" % (le / lg)) if le and lg else "-"
    print("=" * 72)
    print("%-8s  exact lam95=%-7s   greedy lam95=%-7s   ratio=%s" % (case, le, lg, ratio))
    print("   %-8s %-22s %-22s" % ("rate", "exact (cr / delay)", "greedy (cr / delay)"))
    for r in sorted(set(e) | set(g)):
        ev, gv = e.get(r), g.get(r)
        mark = ""
        if ev and gv and ev[0] >= 0.95 > gv[0]:
            mark = "   <-- exact passes, greedy fails"
        print("   %-8g %-22s %-22s%s"
              % (r,
                 "%.3f / %8.1f" % (ev[0], ev[1]) if ev else "-",
                 "%.3f / %8.1f" % (gv[0], gv[1]) if gv else "-",
                 mark))
