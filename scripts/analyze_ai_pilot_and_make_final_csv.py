from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


POLICY_ORDER = {
    "DCNC-DAG-H": 0,
    "Lazarus": 1,
    "FlexMoE": 2,
    "HSDAG": 1,
    "Lazarus-style": 1,
    "FlexMoE-style": 2,
    "HSDAG-style": 1,
}


def parse_seed_list(s: str) -> list[int]:
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def rate_tag(rate: float) -> str:
    return f"rate_{rate:.4f}".replace(".", "p")


def clamp_rate(x: float, min_rate: float = 0.001) -> float:
    return max(min_rate, float(x))


def rounded_rates(rates: Iterable[float]) -> list[float]:
    vals = sorted({round(float(r), 4) for r in rates if np.isfinite(float(r)) and float(r) > 0})
    return vals


def choose_dense_rates(g: pd.DataFrame) -> list[float]:
    """Choose a dense final grid from broad-pilot summary for one workload-policy pair."""
    g = g.sort_values("arrival_rate")
    rates = list(map(float, g["arrival_rate"].to_list()))
    comp = g["completion_ratio_mean"].to_numpy()
    pending = g["pending_packets_mean"].to_numpy()
    delay = g["avg_delay_completed_mean"].to_numpy()
    penalty = g["avg_delay_with_penalty_mean"].to_numpy()

    unstable_mask = (comp < 0.95) | (pending >= 200)
    warning_mask = (pending >= 50) | (penalty >= 5.0 * np.maximum(delay, 1.0))
    near_mask = comp >= 0.98

    # Base low-load anchors from pilot rates.
    selected = []
    selected.extend(rates[:3])

    if near_mask.any():
        selected.append(max(np.array(rates)[near_mask]))

    if warning_mask.any():
        first_warn = float(np.array(rates)[warning_mask][0])
        # previous pilot point before warning, if available
        idx = rates.index(first_warn)
        if idx > 0:
            lo = rates[idx - 1]
        else:
            lo = clamp_rate(first_warn * 0.5)
        hi = first_warn
        # Dense around warning.
        for x in np.linspace(lo, hi, 6):
            selected.append(float(x))
        # Add one slightly above warning.
        selected.append(hi * 1.15)
    elif unstable_mask.any():
        first_unstable = float(np.array(rates)[unstable_mask][0])
        idx = rates.index(first_unstable)
        lo = rates[idx - 1] if idx > 0 else clamp_rate(first_unstable * 0.5)
        hi = first_unstable
        for x in np.linspace(lo, hi, 7):
            selected.append(float(x))
    else:
        # No warning found: extend near the upper end of the broad-pilot grid.
        top = rates[-1]
        prev = rates[-2] if len(rates) >= 2 else top * 0.5
        selected.extend(np.linspace(prev, top, 5))
        selected.extend([top * 1.25, top * 1.5])

    if unstable_mask.any():
        first_unstable = float(np.array(rates)[unstable_mask][0])
        idx = rates.index(first_unstable)
        lo = rates[idx - 1] if idx > 0 else clamp_rate(first_unstable * 0.5)
        hi = first_unstable
        for x in np.linspace(lo, hi, 6):
            selected.append(float(x))
        selected.append(hi)
        # Add collapse point if it exists.
        selected.extend(list(np.array(rates)[comp < 0.5][:1]))

    # Add workload-family sensible anchors.
    family = str(g.iloc[0]["family"])
    if family == "moe":
        selected.extend([0.05, 0.10, 0.20, 0.40, 0.80, 1.00])
    else:
        selected.extend([0.05, 0.10, 0.20, 0.40, 0.80, 1.00])

    return rounded_rates(selected)


def main() -> None:
    ap = argparse.ArgumentParser(description="Analyze AI broad-pilot results and generate dense 50000-slot final CSV.")
    ap.add_argument("--summary", required=True, help="Path to ai_benchmarks_summary.csv")
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--final-csv", required=True)
    ap.add_argument("--final-output-root", default="results/ai_benchmarks_final_50000_seed012_from_pilot")
    ap.add_argument("--final-slots", type=int, default=50000)
    ap.add_argument("--final-seeds", default="0,1,2")
    ap.add_argument("--progress-every", type=int, default=5000)
    ap.add_argument("--fixed-k", type=int, default=1)
    ap.add_argument("--interference-model", default="none")
    args = ap.parse_args()

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary = pd.read_csv(args.summary)

    required = [
        "family", "workload", "workload_label", "policy_label", "arrival_rate",
        "avg_delay_completed_mean", "avg_delay_with_penalty_mean",
        "achieved_throughput_mean", "delivered_packets_mean", "pending_packets_mean",
    ]
    missing = [c for c in required if c not in summary.columns]
    if missing:
        raise SystemExit(f"Missing columns in summary: {missing}\nAvailable: {list(summary.columns)}")

    df = summary.copy()
    total = df["delivered_packets_mean"] + df["pending_packets_mean"]
    df["completion_ratio_mean"] = np.where(total > 0, df["delivered_packets_mean"] / total, np.nan)
    df["delay_penalty_ratio"] = df["avg_delay_with_penalty_mean"] / df["avg_delay_completed_mean"].clip(lower=1.0)
    df = df.sort_values(["family", "workload", "policy_label", "arrival_rate"])
    df.to_csv(out / "ai_pilot_summary_with_completion_ratio.csv", index=False)

    report_rows = []
    final_rows = []
    seeds = parse_seed_list(args.final_seeds)

    for (family, workload, workload_label, policy_label), g in df.groupby(["family", "workload", "workload_label", "policy_label"]):
        g = g.sort_values("arrival_rate")
        rates = g["arrival_rate"].to_numpy(dtype=float)
        comp = g["completion_ratio_mean"].to_numpy(dtype=float)
        pending = g["pending_packets_mean"].to_numpy(dtype=float)
        delay = g["avg_delay_completed_mean"].to_numpy(dtype=float)
        penalty = g["avg_delay_with_penalty_mean"].to_numpy(dtype=float)
        throughput = g["achieved_throughput_mean"].to_numpy(dtype=float)

        strict_mask = (comp >= 0.995) & (pending <= 10)
        near_mask = comp >= 0.98
        warning_mask = (pending >= 50) | (penalty >= 5.0 * np.maximum(delay, 1.0))
        unstable_mask = (comp < 0.95) | (pending >= 200)
        collapse_mask = comp < 0.5

        def max_rate(mask):
            vals = rates[mask]
            return float(vals.max()) if len(vals) else np.nan

        def first_rate(mask):
            vals = rates[mask]
            return float(vals.min()) if len(vals) else np.nan

        max_thr_idx = int(np.nanargmax(throughput)) if len(throughput) else 0
        final_rates = choose_dense_rates(g)

        report_rows.append({
            "family": family,
            "workload": workload,
            "workload_label": workload_label,
            "policy_label": policy_label,
            "strict_stable_rate_completion>=0.995_pending<=10": max_rate(strict_mask),
            "near_stable_rate_completion>=0.98": max_rate(near_mask),
            "first_warning_rate_pending>=50_or_penalty_delay_5x_completed": first_rate(warning_mask),
            "first_unstable_rate_completion<0.95_or_pending>=200": first_rate(unstable_mask),
            "first_collapse_rate_completion<0.5": first_rate(collapse_mask),
            "max_tested_rate": float(rates.max()) if len(rates) else np.nan,
            "max_observed_throughput": float(np.nanmax(throughput)) if len(throughput) else np.nan,
            "rate_at_max_observed_throughput": float(rates[max_thr_idx]) if len(rates) else np.nan,
            "recommended_final_rates": ",".join(f"{r:.4f}" for r in final_rates),
        })

        for r in final_rates:
            for seed in seeds:
                output_dir = f"{args.final_output_root}/{workload}/{rate_tag(r)}/{policy_label}/seed_{seed}"
                cmd = (
                    f"python scripts/run_ai_workload_case.py --workload {workload} --policy {policy_label} "
                    f"--rate {r:.4f} --output-dir {output_dir} --slots {args.final_slots} --seed {seed} "
                    f"--fixed-k {args.fixed_k} --interference-model {args.interference_model} --progress-every {args.progress_every}"
                )
                final_rows.append({
                    "family": family,
                    "workload": workload,
                    "policy": policy_label,
                    "arrival_rate": f"{r:.4f}",
                    "slots": args.final_slots,
                    "seed": seed,
                    "fixed_k": args.fixed_k,
                    "interference_model": args.interference_model,
                    "output_dir": output_dir,
                    "command": cmd,
                })

    report = pd.DataFrame(report_rows)
    report["policy_order"] = report["policy_label"].map(lambda x: POLICY_ORDER.get(str(x), 99))
    report = report.sort_values(["family", "workload", "policy_order", "policy_label"]).drop(columns=["policy_order"])
    report.to_csv(out / "ai_pilot_knee_report.csv", index=False)
    report.to_csv(out / "ai_pilot_knee_report_compact.csv", index=False)

    final_csv = Path(args.final_csv)
    final_csv.parent.mkdir(parents=True, exist_ok=True)
    with final_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(final_rows[0].keys()))
        writer.writeheader()
        writer.writerows(final_rows)

    print("\n=== AI pilot knee report ===")
    print(report[["family", "workload_label", "policy_label", "near_stable_rate_completion>=0.98", "first_warning_rate_pending>=50_or_penalty_delay_5x_completed", "first_unstable_rate_completion<0.95_or_pending>=200", "recommended_final_rates"]].to_string(index=False))
    print(f"\nwrote: {out / 'ai_pilot_summary_with_completion_ratio.csv'}")
    print(f"wrote: {out / 'ai_pilot_knee_report.csv'}")
    print(f"wrote final CSV: {final_csv}")


if __name__ == "__main__":
    main()
