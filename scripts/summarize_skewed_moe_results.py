from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd


POLICY_LABELS = {
    "DCNC-DAG-H": "DCNC-DAG-H",
    "Lazarus-style": "Lazarus",
    "FlexMoE-style": "FlexMoE",
}
WORKLOAD_LABELS = {
    "mixtral_skewed_pr_multitenant": "Mixtral-skewed",
    "llama_skewed_pr_multitenant": "Llama-skewed",
}


def main() -> None:
    ap = argparse.ArgumentParser(description="Merge and summarize skewed MoE serving point-run results.")
    ap.add_argument("--input-root", required=True)
    ap.add_argument("--output-dir", required=True)
    args = ap.parse_args()

    root = Path(args.input_root)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    frames = []
    for p in sorted(root.rglob("ai_workload_case_result.csv")):
        rel = p.relative_to(root).parts
        df = pd.read_csv(p)
        df["source_csv"] = str(p)
        if len(rel) >= 4:
            df["workload_dir"] = rel[0]
            df["rate_dir"] = rel[1]
            df["policy_dir"] = rel[2]
            df["seed_dir"] = rel[3]
        frames.append(df)
    if not frames:
        raise SystemExit(f"No ai_workload_case_result.csv found under {root}")

    all_df = pd.concat(frames, ignore_index=True)
    all_df["policy_label"] = all_df["policy"].map(lambda x: POLICY_LABELS.get(str(x), str(x)))
    all_df["workload_label"] = all_df["workload"].map(lambda x: WORKLOAD_LABELS.get(str(x), str(x)))
    if "completion_fraction" not in all_df.columns:
        total = all_df["delivered_packets"] + all_df["pending_packets"]
        all_df["completion_fraction"] = all_df["delivered_packets"] / total.where(total > 0, 1)

    all_df = all_df.sort_values(["workload", "policy_label", "arrival_rate", "seed"])
    all_df.to_csv(out / "skewed_moe_all_results.csv", index=False)

    summary = all_df.groupby(
        ["family", "workload", "workload_label", "policy", "policy_label", "arrival_rate"],
        as_index=False,
    ).agg(
        avg_delay_completed_mean=("avg_delay_completed", "mean"),
        avg_delay_completed_std=("avg_delay_completed", "std"),
        avg_delay_with_penalty_mean=("avg_delay_with_penalty", "mean"),
        avg_delay_with_penalty_std=("avg_delay_with_penalty", "std"),
        achieved_throughput_mean=("achieved_throughput", "mean"),
        achieved_throughput_std=("achieved_throughput", "std"),
        delivered_packets_mean=("delivered_packets", "mean"),
        pending_packets_mean=("pending_packets", "mean"),
        completion_fraction_mean=("completion_fraction", "mean"),
        completion_fraction_std=("completion_fraction", "std"),
        routing_oracle_calls_mean=("routing_oracle_calls", "mean"),
        routing_cache_hits_mean=("routing_cache_hits", "mean"),
        seeds=("seed", "nunique"),
    )
    summary = summary.sort_values(["workload", "policy_label", "arrival_rate"])
    summary.to_csv(out / "skewed_moe_summary.csv", index=False)

    plot_data = summary[[
        "workload_label", "policy_label", "arrival_rate", "avg_delay_completed_mean",
        "avg_delay_with_penalty_mean", "achieved_throughput_mean", "completion_fraction_mean",
        "pending_packets_mean",
    ]].copy()
    plot_data.to_csv(out / "plot_data_skewed_moe.csv", index=False)

    print(f"loaded point files: {len(frames)}")
    print(f"wrote: {out / 'skewed_moe_all_results.csv'}")
    print(f"wrote: {out / 'skewed_moe_summary.csv'}")
    print("\nSummary preview:")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
