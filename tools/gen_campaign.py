#!/usr/bin/env python3
"""Build the final campaign spec: a dense rate grid centred on each curve's knee.

The knee of every (scenario, policy) curve is bracketed from a pilot sweep, then
each curve gets its own multiplicative grid around that bracket.  Per-policy
grids are what Section VII-A already describes ("a grid refined separately for
each policy, since the policies operate at very different rates"); the fairness
condition is that the network, DAG set, horizon, seeds and wireless sample paths
are shared, which they are.

Roughly two thirds of the points sit below the knee to draw the flat region and
one third walk through it, which is the shape of the accepted Fig.3(a).
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

# below the knee: draw the flat floor and the gentle rise
BELOW = [0.03, 0.07, 0.13, 0.20, 0.29, 0.39, 0.50, 0.61, 0.71, 0.80]
# through the knee: closely spaced so the upturn reads as near-vertical
THROUGH = [0.88, 0.94, 1.00, 1.06, 1.13, 1.21, 1.30, 1.42, 1.55]


def knee_from_pilot(path: str):
    """(case, policy, solver, fixed_k) -> geometric mid-point of the gate crossing."""
    pts = defaultdict(dict)
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("status") != "ok":
            continue
        key = (r["case"], r["policy"], r["solver"], int(r.get("fixed_k", 1)))
        pts[key][float(r["rate"])] = float(r["completion_ratio"])
    out = {}
    for key, m in pts.items():
        srt = sorted(m.items())
        ok = [a for a, c in srt if c >= 0.95]
        if not ok:
            # never passed the gate: knee is at or below the smallest swept rate
            out[key] = srt[0][0] if srt else None
            continue
        lam = ok[-1]
        nxt = [a for a, _ in srt if a > lam]
        out[key] = (lam * nxt[0]) ** 0.5 if nxt else lam * 1.25
    return out


def grid(knee: float):
    g = sorted({round(knee * m, 4) for m in BELOW + THROUGH})
    return [x for x in g if x >= 5e-4]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", required=True)
    ap.add_argument("--plan", required=True,
                    help="JSON list of {case, config, from_case, slots, seeds, fixed_k[]}")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    knees = knee_from_pilot(args.pilot)
    plan = json.loads(Path(args.plan).read_text())
    POL = [("DCNC-DAG", "exact_dp"), ("DCNC-DAG", "greedy"), ("CTS", "cts"), ("Random", "random")]

    jobs = []
    for item in plan:
        case, config = item["case"], item["config"]
        src = item.get("from_case", case)
        slots = int(item.get("slots", 20000))
        seeds = item.get("seeds", [1])
        kset = item.get("fixed_k", [1])
        for policy, solver in POL:
            if policy == "DCNC-DAG" and solver == "exact_dp":
                ks = kset
            elif len(kset) > 1 and item.get("k_only_exact", True):
                ks = [1]           # the T_f ablation is an exact-mapping study
            else:
                ks = [1]
            base = knees.get((src, policy, solver, 1))
            if base is None:
                print("  !! no pilot knee for %s/%s/%s" % (src, policy, solver))
                continue
            # all T_f curves share the T_f=1 grid so the ablation is readable
            rates = grid(base)
            for k in ks:
                for seed in seeds:
                    for r in rates:
                        jobs.append(dict(case=case, config=config, policy=policy, solver=solver,
                                         fixed_k=k, slots=slots, seed=seed, rate=r))
            print("  %-22s %-16s knee~%-7.3f n_rates=%d  K=%s seeds=%s"
                  % (case, policy + "/" + solver, base, len(rates), ks, seeds))

    Path(args.out).write_text(json.dumps(jobs, indent=1))
    print("\n%d jobs -> %s" % (len(jobs), args.out))


if __name__ == "__main__":
    main()
