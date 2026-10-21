from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


POLICY_ORDER = ["DCNC-DAG-H", "Lazarus-style", "FlexMoE-style", "HSDAG-style"]
WORKLOAD_ORDER = ["mixtral_8x7b_macro", "llama4_maverick_macro", "resnet50_macro", "inception_v3_macro"]


def policy_label(policy: str) -> str:
    return {
        "DCNC-DAG-H": "DCNC-DAG-H",
        "Lazarus-style": "Lazarus",
        "FlexMoE-style": "FlexMoE",
        "HSDAG-style": "HSDAG",
    }.get(policy, policy)


def workload_label(workload: str) -> str:
    return {
        "mixtral_8x7b_macro": "Mixtral-8x7B",
        "llama4_maverick_macro": "Llama-4-Maverick",
        "resnet50_macro": "ResNet-50",
        "inception_v3_macro": "Inception-V3",
    }.get(workload, workload)


def main() -> None:
    ap = argparse.ArgumentParser(description="Merge and summarize AI benchmark point-run results.")
    ap.add_argument("--input-root", default="results/ai_benchmarks_final_5000_seed012")
    ap.add_argument("--output-dir", default="results/ai_benchmarks_final_5000_seed012_merged")
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
    all_df["policy_label"] = all_df["policy"].map(policy_label)
    all_df["workload_label"] = all_df["workload"].map(workload_label)
    all_df["x_moe_tokens_2pow10"] = all_df["arrival_rate"] * 200.0
    all_df["x_graph_images_1e3"] = all_df["arrival_rate"] * 10.0

    all_df = all_df.sort_values(["family", "workload", "policy", "arrival_rate", "seed"])
    all_df.to_csv(out / "ai_benchmarks_all_results.csv", index=False)

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
        routing_oracle_calls_mean=("routing_oracle_calls", "mean"),
        routing_cache_hits_mean=("routing_cache_hits", "mean"),
        seeds=("seed", "nunique"),
    )
    summary["x_moe_tokens_2pow10"] = summary["arrival_rate"] * 200.0
    summary["x_graph_images_1e3"] = summary["arrival_rate"] * 10.0
    summary = summary.sort_values(["family", "workload", "policy", "arrival_rate"])
    summary.to_csv(out / "ai_benchmarks_summary.csv", index=False)

    for family, g in summary.groupby("family"):
        g.to_csv(out / f"ai_benchmarks_{family}_summary.csv", index=False)

    # Minimal plot data CSVs.
    moe = summary[summary["family"] == "moe"][[
        "workload_label", "policy_label", "arrival_rate", "x_moe_tokens_2pow10", "avg_delay_with_penalty_mean", "avg_delay_completed_mean"
    ]].copy()
    moe.to_csv(out / "plot_data_moe.csv", index=False)

    graph = summary[summary["family"] == "graph"][[
        "workload_label", "policy_label", "arrival_rate", "x_graph_images_1e3", "avg_delay_with_penalty_mean", "avg_delay_completed_mean", "achieved_throughput_mean"
    ]].copy()
    graph.to_csv(out / "plot_data_computation_graph.csv", index=False)

    print(f"loaded point files: {len(frames)}")
    print(f"wrote: {out / 'ai_benchmarks_all_results.csv'}")
    print(f"wrote: {out / 'ai_benchmarks_summary.csv'}")
    print("\nSummary preview:")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
