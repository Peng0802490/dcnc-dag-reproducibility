#!/usr/bin/env python3
"""Summarise a sweep: per (case, policy) show the curve and the 0.95-gate threshold.

lam95 is the largest swept rate whose end-of-horizon completion ratio is >= 0.95
(the paper's gate); 'next' is the first rejected rate, so a curve whose 'next' is
SCAN-END was truncated before the policy actually broke.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

path = sys.argv[1]
only = sys.argv[2] if len(sys.argv) > 2 else None
detail = "--detail" in sys.argv

rows = defaultdict(dict)
for line in Path(path).read_text().splitlines():
    if not line.strip():
        continue
    r = json.loads(line)
    if r.get("status") != "ok":
        continue
    tag = (r["case"], r["policy"] + ("" if r["policy"] != "DCNC-DAG" else "/" + r["solver"]),
           r.get("fixed_k", 1))
    rows[tag][float(r["rate"])] = (r["avg_delay_completed"], r["completion_ratio"])

order = {"DCNC-DAG/exact_dp": 0, "DCNC-DAG/greedy": 1, "CTS": 2, "Random": 3}
for case in sorted({k[0] for k in rows}):
    if only and only not in case:
        continue
    print("=" * 78)
    print(case)
    for tag in sorted([k for k in rows if k[0] == case],
                      key=lambda k: (k[2], order.get(k[1], 9))):
        pts = sorted(rows[tag].items())
        ok = [(a, v[1]) for a, v in pts if v[1] >= 0.95]
        lam = ok[-1][0] if ok else None
        cr = ok[-1][1] if ok else None
        nxt = [(a, v[1]) for a, v in pts if lam is not None and a > lam]
        label = tag[1] + (" K=%d" % tag[2] if tag[2] != 1 else "")
        print("  %-22s n=%-3d lam95=%-7s cr=%-7s next=%s"
              % (label, len(pts), lam, ("%.3f" % cr) if cr is not None else "-",
                 ("%g (cr=%.3f)" % nxt[0]) if nxt else "SCAN-END <-- extend"))
        if detail:
            for a, (d, c) in pts:
                print("        r=%-8g delay=%-10.2f cr=%.3f" % (a, d, c))
