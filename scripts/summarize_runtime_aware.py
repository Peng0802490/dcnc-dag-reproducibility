from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from common import ensure_dir, save_dataframe


def _read_all(input_root: Path) -> pd.DataFrame:
    paths = sorted(input_root.rglob("runtime_aware_all_results.csv"))
    if not paths:
        paths = sorted(input_root.rglob("*_runtime_aware_results.csv"))
    if not paths:
        raise SystemExit(f"No runtime-aware result CSVs found under {input_root}")
    frames = []
    for path in paths:
        try:
            df = pd.read_csv(path)
        except Exception as exc:
            print(f"[skip] {path}: {exc}")
            continue
        df["source_csv"] = str(path)
        frames.append(df)
    if not frames:
        raise SystemExit("No readable result CSVs found")
    return pd.concat(frames, ignore_index=True)


def _numeric(df: pd.DataFrame, col: str, default: float = 0.0) -> None:
    if col not in df.columns:
        df[col] = default
    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(default)


def _add_reductions(summary: pd.DataFrame) -> pd.DataFrame:
    # Compare async_reuse to ideal_fixed_k at the same case/rate/slot_sec/seed group
    # when both are available.  Positive oracle_time_reduction_vs_ideal means async
    # used less wall-clock oracle time.
    base_keys = [c for c in ["case", "total_arrival_rate", "slot_sec", "dcnc_solver", "interference_model"] if c in summary.columns]
    if not base_keys or "mode" not in summary.columns:
        return summary
    ideals = summary[summary["mode"] == "ideal_fixed_k"].copy()
    ideals = ideals[base_keys + ["mean_service_delay", "mean_oracle_wall_time_sec", "mean_oracle_calls"]]
    ideals = ideals.rename(
        columns={
            "mean_service_delay": "ideal_mean_service_delay",
            "mean_oracle_wall_time_sec": "ideal_mean_oracle_wall_time_sec",
            "mean_oracle_calls": "ideal_mean_oracle_calls",
        }
    )
    out = summary.merge(ideals, on=base_keys, how="left")
    out["service_delay_ratio_vs_ideal"] = out["mean_service_delay"] / out["ideal_mean_service_delay"].replace(0, np.nan)
    out["oracle_time_reduction_vs_ideal"] = 1.0 - out["mean_oracle_wall_time_sec"] / out["ideal_mean_oracle_wall_time_sec"].replace(0, np.nan)
    out["oracle_call_reduction_vs_ideal"] = 1.0 - out["mean_oracle_calls"] / out["ideal_mean_oracle_calls"].replace(0, np.nan)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Summarize runtime-aware asynchronous DCNC-DAG results.")
    ap.add_argument("--input-root", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--case", nargs="*", default=None)
    ap.add_argument("--mode", nargs="*", default=None)
    args = ap.parse_args()

    input_root = Path(args.input_root)
    out_dir = ensure_dir(args.output_dir)
    df = _read_all(input_root)

    for col in [
        "seed", "total_slots", "slot_sec", "total_arrival_rate", "avg_service_delay_completed", "avg_service_delay_with_penalty",
        "avg_service_control_wait_completed", "avg_service_network_delay_completed", "routing_oracle_calls",
        "routing_oracle_wall_time_sec", "simulation_wall_time_sec", "dynvmp_calls_per_slot",
        "dynvmp_time_per_call_ms", "async_mapping_updates", "async_refresh_triggers",
        "async_control_wait_avg_slots_injected", "async_control_wait_p95_slots_injected",
        "async_effective_update_interval_avg_slots", "async_mapping_age_avg_slots",
        "async_mapping_age_max_slots", "async_controller_utilization", "completed_service_units",
        "pending_service_units", "mean_physical_backlog", "max_physical_backlog", "mean_vq_link_sum", "mean_vq_node_sum",
    ]:
        _numeric(df, col, 0.0)

    if args.case:
        df = df[df["case"].astype(str).isin(args.case)].copy()
    if args.mode:
        df = df[df["mode"].astype(str).isin(args.mode)].copy()

    dedup_cols = [c for c in ["run_id", "case", "mode", "seed", "total_arrival_rate", "slot_sec", "source_csv"] if c in df.columns]
    if dedup_cols:
        df = df.drop_duplicates(subset=dedup_cols, keep="last").reset_index(drop=True)
    save_dataframe(df, out_dir / "runtime_aware_merged_runs.csv")

    group_cols = [c for c in [
        "case", "mode", "routing_mode", "dcnc_solver", "interference_model", "fixed_k",
        "slot_sec", "oracle_workers", "oracle_min_delay_slots", "async_refresh_policy", "total_arrival_rate", "total_slots"
    ] if c in df.columns]

    summary = (
        df.groupby(group_cols, as_index=False)
        .agg(
            seeds=("seed", "nunique"),
            mean_service_delay=("avg_service_delay_completed", "mean"),
            std_service_delay=("avg_service_delay_completed", "std"),
            mean_service_delay_with_penalty=("avg_service_delay_with_penalty", "mean"),
            mean_control_wait_completed=("avg_service_control_wait_completed", "mean"),
            mean_network_delay_completed=("avg_service_network_delay_completed", "mean"),
            mean_control_wait_injected=("async_control_wait_avg_slots_injected", "mean"),
            mean_control_wait_p95_injected=("async_control_wait_p95_slots_injected", "mean"),
            mean_oracle_calls=("routing_oracle_calls", "mean"),
            std_oracle_calls=("routing_oracle_calls", "std"),
            mean_oracle_wall_time_sec=("routing_oracle_wall_time_sec", "mean"),
            std_oracle_wall_time_sec=("routing_oracle_wall_time_sec", "std"),
            mean_oracle_time_per_call_ms=("dynvmp_time_per_call_ms", "mean"),
            mean_simulation_wall_time_sec=("simulation_wall_time_sec", "mean"),
            mean_mapping_updates=("async_mapping_updates", "mean"),
            mean_refresh_triggers=("async_refresh_triggers", "mean"),
            mean_effective_update_interval_slots=("async_effective_update_interval_avg_slots", "mean"),
            mean_mapping_age_slots=("async_mapping_age_avg_slots", "mean"),
            max_mapping_age_slots=("async_mapping_age_max_slots", "max"),
            mean_controller_utilization=("async_controller_utilization", "mean"),
            mean_completed_service_units=("completed_service_units", "mean"),
            mean_pending_service_units=("pending_service_units", "mean"),
            mean_physical_backlog=("mean_physical_backlog", "mean"),
            max_physical_backlog=("max_physical_backlog", "max"),
            mean_vq_link_sum=("mean_vq_link_sum", "mean"),
            mean_vq_node_sum=("mean_vq_node_sum", "mean"),
        )
    )
    summary["mean_oracle_calls_per_slot"] = summary["mean_oracle_calls"] / summary["total_slots"].replace(0, np.nan)
    summary["mean_control_wait_completed_sec"] = summary["mean_control_wait_completed"] * summary["slot_sec"]
    summary["mean_network_delay_completed_sec"] = summary["mean_network_delay_completed"] * summary["slot_sec"]
    summary["mean_service_delay_sec"] = summary["mean_service_delay"] * summary["slot_sec"]
    summary = _add_reductions(summary)

    save_dataframe(summary, out_dir / "runtime_aware_summary.csv")

    # A compact table for papers: one row per case/mode/rate/slot_sec.
    keep_cols = [c for c in [
        "case", "mode", "total_arrival_rate", "slot_sec", "seeds",
        "mean_service_delay", "mean_control_wait_completed", "mean_network_delay_completed",
        "mean_oracle_calls", "mean_oracle_wall_time_sec", "mean_oracle_time_per_call_ms",
        "mean_oracle_calls_per_slot", "mean_effective_update_interval_slots", "mean_mapping_age_slots",
        "mean_controller_utilization", "service_delay_ratio_vs_ideal", "oracle_time_reduction_vs_ideal",
        "oracle_call_reduction_vs_ideal",
    ] if c in summary.columns]
    save_dataframe(summary[keep_cols], out_dir / "runtime_aware_paper_table.csv")
    print(f"[done] wrote {out_dir / 'runtime_aware_merged_runs.csv'}")
    print(f"[done] wrote {out_dir / 'runtime_aware_summary.csv'}")
    print(f"[done] wrote {out_dir / 'runtime_aware_paper_table.csv'}")


if __name__ == "__main__":
    main()
