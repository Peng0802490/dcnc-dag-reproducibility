from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


POLICY_ORDER = {"DCNC-DAG-H": 0, "Lazarus": 1, "FlexMoE": 2, "Lazarus-style": 1, "FlexMoE-style": 2}


def parse_seed_list(s: str) -> list[int]:
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def rate_tag(rate: float) -> str:
    return f"rate_{rate:.4f}".replace(".", "p")


def rounded_rates(rates: Iterable[float]) -> list[float]:
    return sorted({round(float(x), 4) for x in rates if np.isfinite(float(x)) and float(x) > 0})


def choose_final_rates(g: pd.DataFrame, supportable_only: bool) -> list[float]:
    g = g.sort_values("arrival_rate")
    rates = g["arrival_rate"].to_numpy(dtype=float)
    comp = g["completion_fraction_mean"].to_numpy(dtype=float)
    pending = g["pending_packets_mean"].to_numpy(dtype=float)
    delay = g["avg_delay_completed_mean"].to_numpy(dtype=float)
    penalty = g["avg_delay_with_penalty_mean"].to_numpy(dtype=float)

    near_mask = comp >= 0.98
    strict_mask = (comp >= 0.995) & (pending <= 50)
    warning_mask = (pending >= 300) | (penalty >= 5.0 * np.maximum(delay, 1.0)) | (comp < 0.98)
    unstable_mask = (comp < 0.95) | (pending >= 1000)

    selected: list[float] = []
    # Low/mid anchors that make final curves readable.
    for x in [2.0, 4.0, 6.0, 8.0, 9.0, 10.0]:
        if x <= rates.max() + 1e-9:
            selected.append(x)

    if near_mask.any():
        stable_max = float(rates[near_mask].max())
        selected.append(stable_max)
    else:
        stable_max = float(rates[0])
        selected.append(stable_max)

    if warning_mask.any():
        warn = float(rates[warning_mask][0])
        idx = list(rates).index(warn)
        lo = float(rates[max(0, idx - 1)])
        hi = warn
        # Dense in the transition interval.
        selected.extend(np.linspace(lo, hi, 7))
        if not supportable_only:
            selected.append(hi)
            selected.append(hi * 1.05)
    elif unstable_mask.any():
        un = float(rates[unstable_mask][0])
        idx = list(rates).index(un)
        lo = float(rates[max(0, idx - 1)])
        selected.extend(np.linspace(lo, un, 7))
        if not supportable_only:
            selected.append(un)
    else:
        # If no warning was found, extend slightly upward in the final template.
        top = float(rates.max())
        prev = float(rates[-2]) if len(rates) >= 2 else max(0.1, top * 0.8)
        selected.extend(np.linspace(prev, top, 5))
        if not supportable_only:
            selected.extend([top * 1.1, top * 1.2])

    if supportable_only:
        # Keep only rates up to the largest rate with completion fraction >= 0.98.
        if near_mask.any():
            cutoff = float(rates[near_mask].max())
            selected = [r for r in selected if r <= cutoff + 1e-9]
        # Still keep a few dense points below cutoff, if available in pilot.
    return rounded_rates(selected)


def main() -> None:
    ap = argparse.ArgumentParser(description="Analyze skewed-MoE pilot and generate 50000-slot final CSV.")
    ap.add_argument("--summary", required=True, help="Path to skewed_moe_summary.csv")
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--final-csv", required=True)
    ap.add_argument("--final-output-root", default="results/skewed_moe_final_50000_seed012_from_pilot")
    ap.add_argument("--final-slots", type=int, default=50000)
    ap.add_argument("--final-seeds", default="0,1,2")
    ap.add_argument("--progress-every", type=int, default=5000)
    ap.add_argument("--fixed-k", type=int, default=1)
    ap.add_argument("--interference-model", default="none")
    ap.add_argument("--tenant-a-fraction", type=float, default=0.60)
    ap.add_argument("--include-overload-point", action="store_true", help="Include one or two points beyond the supportable rate. Default is supportable-only.")
    args = ap.parse_args()

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(args.summary)
    required = [
        "family", "workload", "workload_label", "policy_label", "arrival_rate",
        "avg_delay_completed_mean", "avg_delay_with_penalty_mean", "achieved_throughput_mean",
        "delivered_packets_mean", "pending_packets_mean", "completion_fraction_mean",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise SystemExit(f"Missing columns in summary: {missing}\nAvailable: {list(df.columns)}")

    report_rows = []
    final_rows = []
    seeds = parse_seed_list(args.final_seeds)
    supportable_only = not args.include_overload_point

    for (family, workload, workload_label, policy_label), g in df.groupby(["family", "workload", "workload_label", "policy_label"]):
        g = g.sort_values("arrival_rate")
        rates = g["arrival_rate"].to_numpy(dtype=float)
        comp = g["completion_fraction_mean"].to_numpy(dtype=float)
        pending = g["pending_packets_mean"].to_numpy(dtype=float)
        delay = g["avg_delay_completed_mean"].to_numpy(dtype=float)
        penalty = g["avg_delay_with_penalty_mean"].to_numpy(dtype=float)
        throughput = g["achieved_throughput_mean"].to_numpy(dtype=float)

        strict_mask = (comp >= 0.995) & (pending <= 50)
        near_mask = comp >= 0.98
        warning_mask = (pending >= 300) | (penalty >= 5.0 * np.maximum(delay, 1.0)) | (comp < 0.98)
        unstable_mask = (comp < 0.95) | (pending >= 1000)
        collapse_mask = comp < 0.5

        def max_rate(mask):
            vals = rates[mask]
            return float(vals.max()) if len(vals) else np.nan

        def first_rate(mask):
            vals = rates[mask]
            return float(vals.min()) if len(vals) else np.nan

        max_thr_idx = int(np.nanargmax(throughput)) if len(throughput) else 0
        final_rates = choose_final_rates(g, supportable_only=supportable_only)

        report_rows.append({
            "family": family,
            "workload": workload,
            "workload_label": workload_label,
            "policy_label": policy_label,
            "strict_stable_rate_completion>=0.995_pending<=50": max_rate(strict_mask),
            "near_stable_rate_completion>=0.98": max_rate(near_mask),
            "first_warning_rate": first_rate(warning_mask),
            "first_unstable_rate": first_rate(unstable_mask),
            "first_collapse_rate": first_rate(collapse_mask),
            "max_tested_rate": float(rates.max()) if len(rates) else np.nan,
            "max_observed_throughput": float(np.nanmax(throughput)) if len(throughput) else np.nan,
            "rate_at_max_observed_throughput": float(rates[max_thr_idx]) if len(rates) else np.nan,
            "recommended_final_rates": ",".join(f"{r:.4f}" for r in final_rates),
        })
        for r in final_rates:
            for seed in seeds:
                output_dir = f"{args.final_output_root}/{workload}/{rate_tag(r)}/{policy_label}/seed_{seed}"
                cmd = (
                    f"python scripts/run_skewed_moe_case.py --workload {workload} --policy {policy_label} "
                    f"--rate {r:.4f} --tenant-a-fraction {args.tenant_a_fraction:.4f} --output-dir {output_dir} "
                    f"--slots {args.final_slots} --seed {seed} --fixed-k {args.fixed_k} "
                    f"--interference-model {args.interference_model} --progress-every {args.progress_every}"
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
                    "tenant_a_fraction": f"{args.tenant_a_fraction:.4f}",
                    "output_dir": output_dir,
                    "command": cmd,
                })

    report = pd.DataFrame(report_rows)
    report["policy_order"] = report["policy_label"].map(lambda x: POLICY_ORDER.get(str(x), 99))
    report = report.sort_values(["workload", "policy_order", "policy_label"]).drop(columns=["policy_order"])
    report.to_csv(out / "skewed_moe_pilot_knee_report.csv", index=False)

    final_csv = Path(args.final_csv)
    final_csv.parent.mkdir(parents=True, exist_ok=True)
    with final_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(final_rows[0].keys()))
        writer.writeheader()
        writer.writerows(final_rows)

    print("\n=== Skewed MoE pilot knee report ===")
    cols = ["workload_label", "policy_label", "near_stable_rate_completion>=0.98", "first_warning_rate", "first_unstable_rate", "recommended_final_rates"]
    print(report[cols].to_string(index=False))
    print(f"\nwrote: {out / 'skewed_moe_pilot_knee_report.csv'}")
    print(f"wrote final CSV: {final_csv}")
    print(f"final commands: {len(final_rows)}")


if __name__ == "__main__":
    main()
