from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def _num(x):
    return pd.to_numeric(x, errors="coerce")


def main() -> None:
    ap = argparse.ArgumentParser(description="Analyze pilot-scan CSV and suggest arrival-rate points around the saturation knee.")
    ap.add_argument("--csv", required=True, type=Path, help="CSV produced by scripts/run_edge_experiments.py or scripts/run_project_case.py")
    ap.add_argument("--case", default=None, help="Optional case filter, e.g. report23_milan")
    ap.add_argument("--policy", default="DCNC-DAG-Cost", help="Policy used to identify the knee")
    ap.add_argument("--completion-threshold", type=float, default=0.98)
    ap.add_argument("--delay-factor", type=float, default=3.0, help="Also mark overload if avg delay exceeds delay_factor times the minimum stable delay")
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    if args.case and "case" in df.columns:
        df = df[df["case"].astype(str) == args.case]
    if "policy" not in df.columns:
        raise SystemExit("CSV has no policy column")
    df = df[df["policy"].astype(str) == args.policy].copy()
    if df.empty:
        raise SystemExit(f"No rows after filtering policy={args.policy!r} case={args.case!r}")

    for col in ["total_arrival_rate", "job_completion_ratio", "avg_delay_with_penalty", "job_throughput", "pending_jobs"]:
        if col in df.columns:
            df[col] = _num(df[col])

    metrics = [c for c in ["job_completion_ratio", "avg_delay_with_penalty", "job_throughput", "pending_jobs", "completed_total_cost_norm_per_job"] if c in df.columns]
    grouped = df.groupby("total_arrival_rate", as_index=False)[metrics].mean(numeric_only=True).sort_values("total_arrival_rate")

    stable = grouped["job_completion_ratio"] >= args.completion_threshold if "job_completion_ratio" in grouped.columns else pd.Series([True] * len(grouped))
    min_stable_delay = None
    if "avg_delay_with_penalty" in grouped.columns and stable.any():
        min_stable_delay = float(grouped.loc[stable, "avg_delay_with_penalty"].min())
        stable = stable & (grouped["avg_delay_with_penalty"] <= args.delay_factor * max(min_stable_delay, 1e-12))

    grouped["stable_by_rule"] = stable
    first_unstable_idx = None
    for idx, ok in zip(grouped.index, grouped["stable_by_rule"]):
        if not bool(ok):
            first_unstable_idx = idx
            break

    rates = grouped["total_arrival_rate"].tolist()
    if first_unstable_idx is None:
        knee_rate = None
        long_run_rates = rates[-3:] if len(rates) >= 3 else rates
        note = "No unstable point found. Extend the pilot grid upward."
    else:
        pos = list(grouped.index).index(first_unstable_idx)
        knee_rate = float(grouped.loc[first_unstable_idx, "total_arrival_rate"])
        candidates = []
        for j in [pos - 2, pos - 1, pos, pos + 1]:
            if 0 <= j < len(rates):
                candidates.append(float(rates[j]))
        long_run_rates = sorted(set(candidates))
        note = "Use the last stable point, knee point, and next overloaded point for long-run comparison."

    out_dir = args.out_dir or args.csv.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_csv = out_dir / "knee_summary.csv"
    report_json = out_dir / "knee_recommendation.json"
    grouped.to_csv(summary_csv, index=False)
    report = {
        "input_csv": str(args.csv),
        "case": args.case,
        "policy": args.policy,
        "completion_threshold": args.completion_threshold,
        "delay_factor": args.delay_factor,
        "min_stable_delay": min_stable_delay,
        "knee_rate": knee_rate,
        "recommended_long_run_rates": long_run_rates,
        "note": note,
    }
    report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(grouped.to_string(index=False))
    print("\nRecommendation:")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nwrote {summary_csv}")
    print(f"wrote {report_json}")


if __name__ == "__main__":
    main()
