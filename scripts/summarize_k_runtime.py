from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from common import ensure_dir, save_dataframe


DEFAULT_PATTERNS = [
    "edge_experiments_all_results.csv",
    "wireless_benchmark_all_results.csv",
]


def _read_result_tables(input_root: Path) -> pd.DataFrame:
    paths: list[Path] = []
    for pattern in DEFAULT_PATTERNS:
        paths.extend(sorted(input_root.rglob(pattern)))

    # Fallback for case-local outputs such as driving_milan_results.csv.
    if not paths:
        paths = sorted(input_root.rglob("*.csv"))

    if not paths:
        raise SystemExit(f"No result CSV files found under {input_root}")

    frames = []
    for path in paths:
        try:
            df = pd.read_csv(path)
        except Exception as exc:  # pragma: no cover - defensive for arbitrary user CSV files
            print(f"[skip] cannot read {path}: {exc}")
            continue
        if "fixed_k" not in df.columns or "total_arrival_rate" not in df.columns:
            continue
        df["source_csv"] = str(path)
        frames.append(df)

    if not frames:
        raise SystemExit(f"No DCNC-DAG result CSVs with fixed_k and total_arrival_rate found under {input_root}")

    return pd.concat(frames, ignore_index=True)


def _numeric(df: pd.DataFrame, col: str, default: float = 0.0) -> None:
    if col not in df.columns:
        df[col] = default
    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(default)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Summarize different-K runtime/complexity metrics from DCNC-DAG result CSV files. "
            "By default, it keeps only exact DynVMP runs: policy=DCNC-DAG and dcnc_solver=dynvmp_bridge."
        )
    )
    ap.add_argument("--input-root", required=True, help="Directory containing result CSV files or point-run subdirectories.")
    ap.add_argument("--output-dir", required=True, help="Directory for the merged and summarized CSV files.")
    ap.add_argument("--case", nargs="*", default=None, help="Optional case names to keep, e.g., driving_milan driving_random.")
    ap.add_argument("--include-non-dynvmp", action="store_true", help="Do not filter to exact DynVMP DCNC-DAG runs.")
    args = ap.parse_args()

    input_root = Path(args.input_root)
    out_dir = ensure_dir(args.output_dir)

    df = _read_result_tables(input_root)

    # Backward-compatible defaults for old CSV files.
    _numeric(df, "routing_oracle_calls", 0)
    _numeric(df, "routing_cache_hits", 0)
    _numeric(df, "routing_oracle_wall_time_sec", 0.0)
    _numeric(df, "simulation_wall_time_sec", 0.0)
    _numeric(df, "dynvmp_calls", 0)
    _numeric(df, "dynvmp_wall_time_sec", 0.0)
    _numeric(df, "fixed_k", 1)
    _numeric(df, "total_arrival_rate", 0.0)
    _numeric(df, "avg_delay_completed", 0.0)
    _numeric(df, "avg_delay_with_penalty", 0.0)
    _numeric(df, "delivered_packets", 0)
    _numeric(df, "pending_packets", 0)
    _numeric(df, "total_slots", 0)

    # If the CSV came from the older code, derive DynVMP columns from generic routing-oracle columns.
    exact_mask = (df.get("policy", "") == "DCNC-DAG") & (df.get("dcnc_solver", "") == "dynvmp_bridge")
    missing_dynvmp_calls = exact_mask & (df["dynvmp_calls"] == 0) & (df["routing_oracle_calls"] > 0)
    df.loc[missing_dynvmp_calls, "dynvmp_calls"] = df.loc[missing_dynvmp_calls, "routing_oracle_calls"]
    missing_dynvmp_time = exact_mask & (df["dynvmp_wall_time_sec"] == 0) & (df["routing_oracle_wall_time_sec"] > 0)
    df.loc[missing_dynvmp_time, "dynvmp_wall_time_sec"] = df.loc[missing_dynvmp_time, "routing_oracle_wall_time_sec"]

    if args.case:
        df = df[df["case"].astype(str).isin(args.case)].copy()

    if not args.include_non_dynvmp:
        df = df[exact_mask].copy()

    dedup_cols = [
        "case",
        "policy",
        "dcnc_solver",
        "seed",
        "total_arrival_rate",
        "fixed_k",
        "interference_model",
        "source_csv",
    ]
    dedup_cols = [c for c in dedup_cols if c in df.columns]
    df = df.drop_duplicates(subset=dedup_cols, keep="last").reset_index(drop=True)

    save_dataframe(df, out_dir / "k_runtime_merged_runs.csv")

    if df.empty:
        raise SystemExit("No rows left after filtering. Check --case or use --include-non-dynvmp.")

    group_cols = [
        c for c in ["case", "policy", "dcnc_solver", "interference_model", "fixed_k", "total_arrival_rate", "total_slots"]
        if c in df.columns
    ]
    summary = (
        df.groupby(group_cols, as_index=False)
        .agg(
            seeds=("seed", "nunique"),
            mean_delay_completed=("avg_delay_completed", "mean"),
            std_delay_completed=("avg_delay_completed", "std"),
            mean_delay_with_penalty=("avg_delay_with_penalty", "mean"),
            std_delay_with_penalty=("avg_delay_with_penalty", "std"),
            mean_delivered_packets=("delivered_packets", "mean"),
            mean_pending_packets=("pending_packets", "mean"),
            mean_dynvmp_calls=("dynvmp_calls", "mean"),
            std_dynvmp_calls=("dynvmp_calls", "std"),
            mean_dynvmp_wall_time_sec=("dynvmp_wall_time_sec", "mean"),
            std_dynvmp_wall_time_sec=("dynvmp_wall_time_sec", "std"),
            mean_simulation_wall_time_sec=("simulation_wall_time_sec", "mean"),
            std_simulation_wall_time_sec=("simulation_wall_time_sec", "std"),
        )
    )

    # Optional normalized columns for tables. They are derived from the three primary metrics.
    if "total_slots" in summary.columns:
        slots = summary["total_slots"].replace(0, np.nan)
        summary["mean_dynvmp_calls_per_slot"] = summary["mean_dynvmp_calls"] / slots
    calls = summary["mean_dynvmp_calls"].replace(0, np.nan)
    summary["mean_dynvmp_time_per_call_ms"] = 1000.0 * summary["mean_dynvmp_wall_time_sec"] / calls

    save_dataframe(summary, out_dir / "k_runtime_summary.csv")
    print(f"[done] wrote {out_dir / 'k_runtime_merged_runs.csv'}")
    print(f"[done] wrote {out_dir / 'k_runtime_summary.csv'}")


if __name__ == "__main__":
    main()
