from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


MOE_WORKLOAD_ORDER = ["Mixtral-8x7B", "Llama-4-Maverick"]
MOE_POLICY_ORDER = ["DCNC-DAG-H", "Lazarus", "FlexMoE"]
GRAPH_WORKLOAD_ORDER = ["ResNet-50", "Inception-V3"]
GRAPH_POLICY_ORDER = ["DCNC-DAG-H", "HSDAG"]

LINE_MARKERS = {
    "DCNC-DAG-H": "o",
    "Lazarus": "s",
    "FlexMoE": "^",
    "HSDAG": "D",
}


def ordered(items, preferred):
    items = list(items)
    out = [x for x in preferred if x in items]
    out += [x for x in items if x not in out]
    return out


def make_series_label(workload: str, policy: str) -> str:
    if workload == "Mixtral-8x7B":
        prefix = "Mixtral"
    elif workload == "Llama-4-Maverick":
        prefix = "Llama"
    elif workload == "ResNet-50":
        prefix = "Resnet-50"
    elif workload == "Inception-V3":
        prefix = "Inception-V3"
    else:
        prefix = workload
    return f"{prefix}: {policy}"


def plot_moe(summary: pd.DataFrame, out_dir: Path, metric: str) -> None:
    df = summary[summary["family"] == "moe"].copy()
    if df.empty:
        print("[skip] no MoE data")
        return

    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    for workload in ordered(df["workload_label"].unique(), MOE_WORKLOAD_ORDER):
        wg = df[df["workload_label"] == workload]
        for policy in ordered(wg["policy_label"].unique(), MOE_POLICY_ORDER):
            pg = wg[wg["policy_label"] == policy].sort_values("x_moe_tokens_2pow10")
            ax.plot(
                pg["x_moe_tokens_2pow10"],
                pg[metric],
                marker=LINE_MARKERS.get(policy, "o"),
                linewidth=1.8,
                markersize=4.5,
                label=make_series_label(workload, policy),
            )

    ax.set_xlabel(r"Number of tokens ($\times 2^{10}$)")
    ax.set_ylabel("Average processing delay")
    ax.grid(True, alpha=0.3)
    ax.legend(frameon=True, fontsize=8, ncol=1)
    fig.tight_layout()
    for ext in ["png", "pdf", "eps"]:
        path = out_dir / f"MoE.{ext}"
        fig.savefig(path, dpi=300, bbox_inches="tight")
        print(f"[write] {path}")
    plt.close(fig)


def plot_graph(summary: pd.DataFrame, out_dir: Path, metric: str) -> None:
    df = summary[summary["family"] == "graph"].copy()
    if df.empty:
        print("[skip] no computation-graph data")
        return

    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    for workload in ordered(df["workload_label"].unique(), GRAPH_WORKLOAD_ORDER):
        wg = df[df["workload_label"] == workload]
        for policy in ordered(wg["policy_label"].unique(), GRAPH_POLICY_ORDER):
            pg = wg[wg["policy_label"] == policy].sort_values("x_graph_images_1e3")
            ax.plot(
                pg["x_graph_images_1e3"],
                pg[metric],
                marker=LINE_MARKERS.get(policy, "o"),
                linewidth=1.8,
                markersize=4.5,
                label=make_series_label(workload, policy),
            )

    ax.set_xlabel(r"Number of images ($\times 10^3$)")
    ax.set_ylabel("Average processing delay")
    ax.grid(True, alpha=0.3)
    ax.legend(frameon=True, fontsize=8, ncol=1)
    fig.tight_layout()
    for ext in ["png", "pdf", "eps"]:
        path = out_dir / f"computation.{ext}"
        fig.savefig(path, dpi=300, bbox_inches="tight")
        print(f"[write] {path}")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description="Plot AI benchmark figures from summarized AI benchmark CSV.")
    ap.add_argument("--summary", default="results/ai_benchmarks_final_5000_seed012_merged/ai_benchmarks_summary.csv")
    ap.add_argument("--output-dir", default="results/ai_benchmarks_final_5000_seed012_merged/figures")
    ap.add_argument(
        "--metric",
        default="avg_delay_with_penalty_mean",
        choices=["avg_delay_with_penalty_mean", "avg_delay_completed_mean"],
        help="Paper-style AI figures in the previous script used penalty delay. Use avg_delay_completed_mean if you want completed-only delay.",
    )
    args = ap.parse_args()

    summary_path = Path(args.summary)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(summary_path)
    if args.metric not in df.columns:
        raise RuntimeError(f"Metric {args.metric!r} not found in {summary_path}. Available columns: {list(df.columns)}")
    plot_moe(df, out_dir, args.metric)
    plot_graph(df, out_dir, args.metric)


if __name__ == "__main__":
    main()
