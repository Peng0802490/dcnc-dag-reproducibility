#!/usr/bin/env python3
"""Turn campaign JSONL into the per-scenario CSVs the existing plot.py reads.

Averages over seeds, then truncates each curve just past its knee.  Two points
are dropped by the truncation rule:

  * anything at or below a completion ratio of CR_FLOOR, where so few requests
    finish that the average is meaningless;
  * any point past the gate whose delay has fallen back below the running peak,
    which is survivorship bias -- once the system is deeply overloaded only the
    short-path requests complete, so the measured average drops.

Both were what made the old Randomized curves bend back down (FlockLab: 887 then
856).  Keeping the first rejected point, and only that one, is what produces the
near-vertical knee.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

CR_FLOOR = 0.45
HEADER = ["case", "policy", "seed", "total_arrival_rate", "per_commodity_arrival_rate",
          "interference_model", "fixed_k", "dcnc_solver", "avg_delay_completed",
          "avg_delay_with_penalty", "delivered_packets", "pending_packets", "completion_ratio"]


def truncate(points, max_delay=None, cr_floor=None):
    """points: sorted [(rate, delay, cr)] -> the plotted prefix.

    Two cuts, in order:

    1. Stop at the first rate whose completion ratio falls below CR_FLOOR. So
       few requests finish there that the average is not a delay measurement.
    2. Then keep the prefix up to the rate where the measured delay peaks.
       Past that peak the average falls again, because the completed set has
       shrunk to the requests that happened to take a short route -- survivorship,
       not improvement.  (CTS on the random topology peaks at 1064 slots and then
       reads 25 slots two grid points later, with a completion ratio of 0.50.)

    Testing for a single drop instead, as an earlier version did, was too
    fragile: three-seed curves dip by 20-30% at one grid point near the knee and
    recover, and that cut several curves before they had diverged.

    max_delay stops a curve at a delay ceiling.  The frame-length figure needs
    it: T_f=1..16 differ by tens of slots, so letting every curve run to ~3000
    slots compresses the informative region into a flat band and the T_f
    ordering becomes unreadable.
    """
    floor = CR_FLOOR if cr_floor is None else cr_floor
    kept = []
    for rate, delay, cr in points:
        if kept and cr < floor:
            break
        kept.append((rate, delay, cr))
        if max_delay is not None and delay >= max_delay:
            return kept
    if not kept:
        return kept
    peak_at = max(range(len(kept)), key=lambda i: kept[i][1])
    return kept[:peak_at + 1]


def gate_trim(points, gate=0.95):
    """Cut a curve to lambda-hat plus at most one rejected grid point.

    Section VII-A already states this is what the figures show, and the
    completion ratios it quotes (0.955-0.996 at lambda-hat, 0.809-0.929 at the
    first rejected rate) were computed under exactly this rule -- but the CSVs
    were not built that way, so Fig 3(a)'s DCNC-DAG curve ran three points past
    the gate (ratios 0.82, 0.65, 0.49) while the other three curves in the same
    panel stopped after one.  Curves truncated at different completion ratios
    are not a comparison a reader can check.

    The rejected point is dropped when its delay does not exceed the delay at
    lambda-hat.  A fall there is survivorship: past the gate the completed set
    has shrunk to the requests that happened to take a short route, so the
    average drops even though the system is further overloaded.  That is what
    produced the dip at rate 0.69 on Fig 4(b) -- 233 slots at ratio 0.956, then
    156 at 0.925.
    """
    ok = [i for i, pt in enumerate(points) if pt[2] >= gate]
    if not ok:
        return points
    last = ok[-1]
    if last + 1 < len(points) and points[last + 1][1] > points[last][1]:
        return points[:last + 2]
    return points[:last + 1]


def lam95(points):
    ok = [p for p in points if p[2] >= 0.95]
    return ok[-1] if ok else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", nargs="+", required=True)
    ap.add_argument("--map", required=True,
                    help="JSON: {plot_dir: {case: ..., curves: {csv_name: [policy, solver, fixed_k]}}}")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1] / "results" / "plots"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # (case, policy, solver, fixed_k, rate) -> list of (delay, cr) over seeds
    acc = defaultdict(list)
    for path in args.jsonl:
        for line in Path(path).read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("status") != "ok":
                continue
            key = (r["case"], r["policy"], r["solver"], int(r.get("fixed_k", 1)), float(r["rate"]))
            acc[key].append((float(r["avg_delay_completed"]), float(r["completion_ratio"])))

    spec = json.loads(Path(args.map).read_text())

    def gather(case, policy, solver, fixed_k, min_seeds=1):
        # min_seeds drops rates that only one pilot run ever visited.  The
        # campaign grew by refinement -- pilot, then screen, then the main
        # three-seed sweep -- so the coarse low-rate points of several curves
        # were still single-seed while everything near the knee had three.  A
        # figure whose points do not all rest on the same number of runs is one
        # a reader cannot check, so the panels are built at min_seeds=3.
        pts = []
        for (c, p, s, k, rate), vals in acc.items():
            if (c, p, s, k) == (case, policy, solver, int(fixed_k)):
                n = len(vals)
                if n < min_seeds:
                    continue
                pts.append((rate, sum(v[0] for v in vals) / n, sum(v[1] for v in vals) / n, n))
        return sorted(pts)

    for plot_dir, conf in spec.items():
        case = conf["case"]
        cap = conf.get("max_delay")
        floor = conf.get("cr_floor")
        # On a panel where two policies come out within noise of each other, the
        # threshold comparison is only meaningful if both were swept on the same
        # rates; match_grid restricts a curve to the rates of a reference curve.
        match = conf.get("match_grid", {})
        min_seeds = conf.get("min_seeds", 1)
        outdir = Path(args.root) / plot_dir
        outdir.mkdir(parents=True, exist_ok=True)
        print("=" * 74)
        print("%s   (case=%s%s)" % (plot_dir, case, ", delay cap %s" % cap if cap else ""))
        for csv_name, (policy, solver, fixed_k) in conf["curves"].items():
            pts = gather(case, policy, solver, int(fixed_k), min_seeds)
            if csv_name in match:
                ref = conf["curves"][match[csv_name]]
                keep = {r for r, _, _, _ in gather(case, ref[0], ref[1], int(ref[2]), min_seeds)}
                pts = [x for x in pts if x[0] in keep]
            if not pts:
                print("   %-16s NO DATA" % csv_name)
                continue
            kept = truncate([(a, b, c) for a, b, c, _ in pts], cap, floor)
            n_drop = conf.get("drop_last", {}).get(csv_name, 0)
            if n_drop:
                kept = kept[:-n_drop] if n_drop < len(kept) else kept[:1]
            if conf.get("gate_trim"):
                kept = gate_trim(kept)
            lam = lam95(kept)
            nseeds = pts[0][3]
            print("   %-16s swept=%-3d plotted=%-3d seeds=%d  lam95=%-7s  last=(r=%g, delay=%.1f, cr=%.3f)"
                  % (csv_name, len(pts), len(kept), nseeds,
                     ("%g" % lam[0]) if lam else "none",
                     kept[-1][0], kept[-1][1], kept[-1][2]))
            if args.dry_run:
                continue
            with (outdir / csv_name).open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(HEADER)
                for rate, delay, cr in kept:
                    w.writerow([case, policy, 1, rate, rate, "primary", fixed_k,
                                solver, delay, delay, round(cr * 10000), 10000 - round(cr * 10000),
                                round(cr, 6)])
    if args.dry_run:
        print("\n(dry run: no CSV written)")


if __name__ == "__main__":
    main()
