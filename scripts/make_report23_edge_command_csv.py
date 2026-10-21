#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

"""Generate tmux-scheduler CSV command tables for the Report-2.3 workload on the
AI_RAN_SmartFactory_24 edge-end collaborative network.

Each CSV row is one total-arrival-rate point.  The command in that row runs all
selected policies and all selected seeds for that single rate, writing into a
rate-specific output directory so concurrent tmux jobs do not overwrite one
another.
"""

import argparse
import csv
import json
from pathlib import Path
from typing import Iterable, List

DEFAULT_PILOT_RATES = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.80, 1.00, 1.20, 1.40, 1.60, 1.80, 2.00, 2.20, 2.40]
DEFAULT_MAIN_TEMPLATE_RATES = [0.40, 0.60, 0.80, 1.00, 1.20, 1.40, 1.60]
DEFAULT_POLICIES = ["DCNC-DAG", "DCNC-DAG-Cost", "CTS", "Static-MinCost", "Random"]


def _fmt_rate(rate: float) -> str:
    return f"{rate:.4f}".rstrip("0").rstrip(".")


def _rate_tag(rate: float) -> str:
    return _fmt_rate(rate).replace(".", "p")


def _parse_rates(values: Iterable[str] | None) -> List[float]:
    if not values:
        return []
    out: List[float] = []
    for item in values:
        for part in str(item).replace(",", " ").split():
            if part:
                out.append(float(part))
    return out


def _rates_from_knee_json(path: Path) -> List[float]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rates = data.get("recommended_long_run_rates") or []
    return [float(x) for x in rates]


def main() -> None:
    ap = argparse.ArgumentParser(description="Create one-arrival-rate-per-row CSV commands for report23_edge experiments.")
    ap.add_argument("--stage", choices=["smoke", "pilot", "main"], default="pilot")
    ap.add_argument("--output-csv", type=Path, default=None)
    ap.add_argument("--rates", nargs="*", default=None, help="Override rate list. Accepts space-separated or comma-separated values.")
    ap.add_argument("--knee-json", type=Path, default=None, help="For main stage, read recommended_long_run_rates from analyze_knee.py output.")
    ap.add_argument("--slots", type=int, default=None)
    ap.add_argument("--seeds", type=int, default=None)
    ap.add_argument("--seed-start", type=int, default=0)
    ap.add_argument("--fixed-k", type=int, default=4)
    ap.add_argument("--interference-model", choices=["none", "primary"], default="primary")
    ap.add_argument("--resource-cost-weight", type=float, default=1.0)
    ap.add_argument("--min-completion-ratio", type=float, default=0.98)
    ap.add_argument("--progress-every", type=int, default=250)
    ap.add_argument("--case", default="report23_edge")
    ap.add_argument("--policies", nargs="*", default=DEFAULT_POLICIES)
    ap.add_argument("--results-root", default="results_report23_edge")
    ap.add_argument("--repo-dir", default='${HOME}/dcnc_dag_py3', help="Path used inside generated shell commands.")
    args = ap.parse_args()

    rates = _parse_rates(args.rates)
    if args.knee_json is not None:
        rates = _rates_from_knee_json(args.knee_json)
    if not rates:
        if args.stage == "smoke":
            rates = [0.10, 0.20]
        elif args.stage == "pilot":
            rates = DEFAULT_PILOT_RATES
        else:
            rates = DEFAULT_MAIN_TEMPLATE_RATES

    if args.slots is None:
        slots = 200 if args.stage == "smoke" else 1500 if args.stage == "pilot" else 10000
    else:
        slots = args.slots
    if args.seeds is None:
        seeds = 1 if args.stage == "smoke" else 2 if args.stage == "pilot" else 5
    else:
        seeds = args.seeds

    if args.output_csv is None:
        out_csv = Path("experiments/report23_edge") / f"report23_edge_{args.stage}_commands.csv"
    else:
        out_csv = args.output_csv
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    policy_part = " ".join(args.policies)
    rows = []
    for rate in rates:
        rate_str = _fmt_rate(rate)
        out_dir = f"{args.results_root}/{args.stage}_point_runs/rate_{_rate_tag(rate)}"
        cmd = (
            f"cd {args.repo_dir} && "
            f"source ./setup_runtime_env.sh && "
            f"python scripts/run_edge_experiments.py "
            f"--output-dir {out_dir} "
            f"--cases {args.case} "
            f"--policies {policy_part} "
            f"--rate {rate_str} "
            f"--slots {slots} "
            f"--seeds {seeds} "
            f"--seed-start {args.seed_start} "
            f"--interference-model {args.interference_model} "
            f"--fixed-k {args.fixed_k} "
            f"--resource-cost-weight {args.resource_cost_weight:g} "
            f"--min-completion-ratio {args.min_completion_ratio:g} "
            f"--progress-every {args.progress_every}"
        )
        rows.append({
            "stage": args.stage,
            "case": args.case,
            "total_arrival_rate": rate_str,
            "K": str(args.fixed_k),
            "seed": f"{args.seed_start}-{args.seed_start + seeds - 1}",
            "slots": str(slots),
            "seeds": str(seeds),
            "policies": " ".join(args.policies),
            "output_dir": out_dir,
            "command": cmd,
        })

    fieldnames = ["stage", "case", "total_arrival_rate", "K", "seed", "slots", "seeds", "policies", "output_dir", "command"]
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {out_csv} ({len(rows)} commands)")


if __name__ == "__main__":
    main()
