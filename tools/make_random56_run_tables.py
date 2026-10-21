#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate CSV run tables for random5/random6 experiments.

The generated CSV follows the same shape as Wireless_*_Run_Table.csv:
stage, benchmark, workload, case, policy_label, total_arrival_rate, slots,
seed_start, seeds, fixed_k, dcnc_solver, interference_model, progress_every,
output_dir, actual_result_dir, command.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

BENCHMARKS = ["milan", "random", "roofnet", "flocklab"]
WORKLOADS = ["random5", "random6"]


def fmt_rate(x: float) -> str:
    return f"{x:.4f}"


def parse_list(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


def parse_rates(s: str) -> list[float]:
    return [float(x.strip()) for x in s.split(",") if x.strip()]


def build_command(
    *,
    runner: str,
    case: str,
    slots: int,
    seed_start: int,
    seeds: int,
    rate: str,
    policy_label: str,
    fixed_k: int,
    dcnc_solver: str,
    interference_model: str,
    progress_every: int,
    output_dir: str,
) -> str:
    base = (
        f"PYTHONPATH=src python {runner} "
        f"--case {case} "
        f"--slots {slots} "
        f"--seed-start {seed_start} "
        f"--seeds {seeds} "
        f"--rate {rate} "
    )
    if policy_label.startswith("Exact"):
        return (
            base
            + f"--policies DCNC-DAG "
            + f"--dcnc-solver {dcnc_solver} "
            + f"--dynvmp-cmd \"$DCNC_DYNVMP_CMD\" "
            + f"--fixed-k {fixed_k} "
            + f"--interference-model {interference_model} "
            + f"--progress-every {progress_every} "
            + f"--output-dir {output_dir}"
        )
    if policy_label == "Heuristic":
        return (
            base
            + f"--policies DCNC-DAG "
            + f"--dcnc-solver {dcnc_solver} "
            + f"--fixed-k {fixed_k} "
            + f"--interference-model {interference_model} "
            + f"--progress-every {progress_every} "
            + f"--output-dir {output_dir}"
        )
    if policy_label == "CTS":
        return (
            base
            + f"--policies CTS "
            + f"--fixed-k {fixed_k} "
            + f"--interference-model {interference_model} "
            + f"--progress-every {progress_every} "
            + f"--output-dir {output_dir}"
        )
    if policy_label == "Randomized":
        return (
            base
            + f"--policies Random "
            + f"--fixed-k {fixed_k} "
            + f"--interference-model {interference_model} "
            + f"--progress-every {progress_every} "
            + f"--output-dir {output_dir}"
        )
    raise ValueError(f"unknown policy_label={policy_label!r}")


def append_policy_row(rows: list[dict], args, benchmark: str, workload: str, rate: float, policy_label: str, fixed_k: int, dcnc_solver: str, subdir: str):
    case = f"{benchmark}_{workload}"
    r = fmt_rate(rate)
    if policy_label.startswith("Exact"):
        out_dir = f"{args.result_root}/{args.stage}/points/{subdir}/{case}/k{fixed_k}/r{r}/s{args.seed_start}"
    else:
        out_dir = f"{args.result_root}/{args.stage}/points/{subdir}/{case}/r{r}/s{args.seed_start}"
    cmd = build_command(
        runner=args.runner,
        case=case,
        slots=args.slots,
        seed_start=args.seed_start,
        seeds=args.seeds,
        rate=r,
        policy_label=policy_label,
        fixed_k=fixed_k,
        dcnc_solver=dcnc_solver,
        interference_model=args.interference_model,
        progress_every=args.progress_every,
        output_dir=out_dir,
    )
    rows.append({
        "stage": args.stage,
        "benchmark": benchmark,
        "workload": workload,
        "case": case,
        "policy_label": policy_label,
        "total_arrival_rate": r,
        "slots": args.slots,
        "seed_start": args.seed_start,
        "seeds": args.seeds,
        "fixed_k": fixed_k,
        "dcnc_solver": dcnc_solver,
        "interference_model": args.interference_model,
        "progress_every": args.progress_every,
        "output_dir": out_dir,
        "actual_result_dir": f"{out_dir}/{case}",
        "command": cmd,
    })


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--stage", default="random56_pilot")
    ap.add_argument("--slots", type=int, default=2000)
    ap.add_argument("--seed-start", type=int, default=0)
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--rates", default="0.01,0.02,0.03,0.05,0.08,0.10,0.15,0.20,0.30,0.50,0.80,1.00")
    ap.add_argument("--benchmarks", default=",".join(BENCHMARKS))
    ap.add_argument("--workloads", default=",".join(WORKLOADS))
    ap.add_argument("--progress-every", type=int, default=200)
    ap.add_argument("--runner", default="scripts/run_wireless_benchmark_experiments.py")
    ap.add_argument("--interference-model", default="primary")
    ap.add_argument("--result-root", default="results_paper_edge")
    ap.add_argument("--policies", default="exact,heuristic,cts,random", help="comma-separated: exact,heuristic,cts,random")
    ap.add_argument("--exact-ks", default="1", help="comma-separated exact fixed-K values")
    args = ap.parse_args()

    benchmarks = parse_list(args.benchmarks)
    workloads = parse_list(args.workloads)
    rates = parse_rates(args.rates)
    policies = set(parse_list(args.policies.lower()))
    exact_ks = [int(x) for x in parse_list(args.exact_ks)]

    rows: list[dict] = []
    for benchmark in benchmarks:
        for workload in workloads:
            for rate in rates:
                if "exact" in policies:
                    for k in exact_ks:
                        append_policy_row(rows, args, benchmark, workload, rate, f"Exact-K{k}", k, "dynvmp_bridge", "exact")
                if "heuristic" in policies:
                    append_policy_row(rows, args, benchmark, workload, rate, "Heuristic", 1, "greedy", "heuristic")
                if "cts" in policies:
                    append_policy_row(rows, args, benchmark, workload, rate, "CTS", 1, "", "cts")
                if "random" in policies:
                    append_policy_row(rows, args, benchmark, workload, rate, "Randomized", 1, "", "random")

    fieldnames = [
        "stage", "benchmark", "workload", "case", "policy_label",
        "total_arrival_rate", "slots", "seed_start", "seeds",
        "fixed_k", "dcnc_solver", "interference_model", "progress_every",
        "output_dir", "actual_result_dir", "command",
    ]
    out = Path(args.out)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"[OK] wrote {out} with {len(rows)} commands")


if __name__ == "__main__":
    main()
