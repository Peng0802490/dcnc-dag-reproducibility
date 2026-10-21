from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from dcnc_sim.plotting import plot_delay_curve
from common import ensure_dir, save_dataframe


def _policy_display(row: pd.Series) -> str:
    policy = str(row.get("policy", ""))
    solver = str(row.get("dcnc_solver", ""))
    fixed_k = int(row.get("fixed_k", 1))
    if policy == "CTS":
        return "CTS"
    if policy == "Random":
        return "Random"
    if policy == "DCNC-DAG" and solver == "greedy":
        return "DCNC-DAG-H"
    if policy == "DCNC-DAG" and solver == "dynvmp_bridge":
        return "Exact-K={}".format(fixed_k)
    if policy == "DCNC-DAG":
        return "DCNC-DAG"
    return policy


def main() -> None:
    ap = argparse.ArgumentParser(description="Merge many single-point edge-experiment runs into one combined result table and per-case plots.")
    ap.add_argument("--input-root", required=True, help="Root directory containing many subdirectories with edge_experiments_all_results.csv files.")
    ap.add_argument("--output-dir", required=True)
    args = ap.parse_args()

    input_root = Path(args.input_root)
    out_dir = ensure_dir(args.output_dir)

    csv_paths = sorted(input_root.rglob("edge_experiments_all_results.csv"))
    if not csv_paths:
        raise SystemExit("No edge_experiments_all_results.csv files found under {}".format(input_root))

    frames = []
    for path in csv_paths:
        df = pd.read_csv(path)
        df["source_csv"] = str(path)
        frames.append(df)

    all_df = pd.concat(frames, ignore_index=True)
    dedup_cols = [
        "case",
        "policy",
        "dcnc_solver",
        "seed",
        "total_arrival_rate",
        "fixed_k",
        "interference_model",
    ]
    dedup_cols = [c for c in dedup_cols if c in all_df.columns]
    all_df = all_df.drop_duplicates(subset=dedup_cols, keep="last").reset_index(drop=True)
    all_df["policy_display"] = all_df.apply(_policy_display, axis=1)

    # Backward-compatible defaults: old CSV files do not contain the timing columns.
    for col, default in {
        "routing_oracle_wall_time_sec": 0.0,
        "simulation_wall_time_sec": 0.0,
        "dynvmp_calls": 0,
        "dynvmp_wall_time_sec": 0.0,
    }.items():
        if col not in all_df.columns:
            all_df[col] = default

    save_dataframe(all_df, out_dir / "edge_all_policies_merged.csv")

    summary = (
        all_df.groupby(["case", "policy_display", "total_arrival_rate"], as_index=False)
        .agg(
            mean_delay_penalty=("avg_delay_with_penalty", "mean"),
            std_delay_penalty=("avg_delay_with_penalty", "std"),
            mean_delay_completed=("avg_delay_completed", "mean"),
            mean_pending=("pending_packets", "mean"),
            mean_delivered=("delivered_packets", "mean"),
            mean_oracle_calls=("routing_oracle_calls", "mean"),
            mean_cache_hits=("routing_cache_hits", "mean"),
            mean_routing_oracle_wall_time_sec=("routing_oracle_wall_time_sec", "mean"),
            mean_simulation_wall_time_sec=("simulation_wall_time_sec", "mean"),
            mean_dynvmp_calls=("dynvmp_calls", "mean"),
            mean_dynvmp_wall_time_sec=("dynvmp_wall_time_sec", "mean"),
        )
    )
    save_dataframe(summary, out_dir / "edge_summary_mean_std.csv")

    fig_dir = ensure_dir(out_dir / "figures")
    for case_name, case_df in summary.groupby("case"):
        plot_df = case_df.rename(columns={
            "policy_display": "policy",
            "mean_delay_penalty": "avg_delay_with_penalty",
        })
        plot_delay_curve(
            plot_df,
            x="total_arrival_rate",
            y="avg_delay_with_penalty",
            hue="policy",
            out_path=fig_dir / ("{}_final_delay_curve.png".format(case_name)),
            xlabel="Total arrival rate per slot",
            ylabel="Average delay with unfinished-packet penalty",
        )


if __name__ == "__main__":
    main()
