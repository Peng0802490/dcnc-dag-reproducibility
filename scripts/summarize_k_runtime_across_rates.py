#!/usr/bin/env python3
from pathlib import Path
import argparse
import re
import sys
import pandas as pd


RUNTIME_COLS = [
    "dynvmp_calls",
    "dynvmp_wall_time_sec",
    "simulation_wall_time_sec",
]

DELAY_CANDIDATES = [
    "avg_packet_delay",
    "average_packet_delay",
    "avg_delay",
    "avg_delay_completed",
    "avg_delay_with_penalty",
    "mean_delay",
]


def parse_rate_token(token: str):
    # r0p42 -> 0.42
    if not token.startswith("r"):
        return None
    s = token[1:].replace("p", ".")
    try:
        return float(s)
    except ValueError:
        return None


def infer_case_from_path(path: Path, allowed_cases):
    parts = list(path.parts)
    if allowed_cases:
        for p in parts:
            if p in allowed_cases:
                return p
    for p in parts:
        if p.startswith("driving_"):
            return p
    for i, p in enumerate(parts):
        if re.fullmatch(r"k\d+", p) and i > 0:
            return parts[i - 1]
    return None


def infer_k_from_path(path: Path):
    for p in path.parts:
        m = re.fullmatch(r"k(\d+)", p)
        if m:
            return int(m.group(1))
    return None


def infer_rate_from_path(path: Path):
    for p in path.parts:
        if re.fullmatch(r"r[0-9]+(?:p[0-9]+)?", p):
            return parse_rate_token(p)
    return None


def infer_seed_from_path(path: Path):
    for p in path.parts:
        m = re.fullmatch(r"s(\d+)", p)
        if m:
            return int(m.group(1))
    return None


def fill_or_infer(df: pd.DataFrame, col: str, value):
    if col not in df.columns:
        df[col] = value
    else:
        df[col] = df[col].where(df[col].notna(), value)
    return df


def add_reduction_vs_k1(summary: pd.DataFrame, metric: str, out_col: str):
    values = []
    for _, row in summary.iterrows():
        case = row["case"]
        base = summary[(summary["case"] == case) & (summary["fixed_k"] == 1)]
        if base.empty:
            values.append(float("nan"))
            continue
        base_val = float(base.iloc[0][metric])
        cur_val = float(row[metric])
        if base_val == 0:
            values.append(float("nan"))
        else:
            values.append(1.0 - cur_val / base_val)
    summary[out_col] = values
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--commands-csv", default=None)
    parser.add_argument("--case", nargs="*", default=None)
    args = parser.parse_args()

    input_root = Path(args.input_root)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(input_root.rglob("edge_experiments_all_results.csv"))
    if not files:
        raise SystemExit(f"No edge_experiments_all_results.csv found under {input_root}")

    rows = []
    bad_files = []

    for f in files:
        try:
            df = pd.read_csv(f)
        except Exception as e:
            bad_files.append((str(f), f"read_error: {e}"))
            continue

        if df.empty:
            bad_files.append((str(f), "empty_csv"))
            continue

        case_val = infer_case_from_path(f, args.case)
        k_val = infer_k_from_path(f)
        rate_val = infer_rate_from_path(f)
        seed_val = infer_seed_from_path(f)

        if "K" in df.columns and "fixed_k" not in df.columns:
            df["fixed_k"] = df["K"]

        if "arrival_rate" in df.columns and "total_arrival_rate" not in df.columns:
            df["total_arrival_rate"] = df["arrival_rate"]

        df = fill_or_infer(df, "case", case_val)
        df = fill_or_infer(df, "fixed_k", k_val)
        df = fill_or_infer(df, "total_arrival_rate", rate_val)
        df = fill_or_infer(df, "seed", seed_val)

        df["_result_file"] = str(f)
        rows.append(df)

    if not rows:
        raise SystemExit("No valid CSV rows were loaded.")

    all_df = pd.concat(rows, ignore_index=True)

    # Fallback names for older partially updated outputs.
    if "dynvmp_calls" not in all_df.columns and "routing_oracle_calls" in all_df.columns:
        all_df["dynvmp_calls"] = all_df["routing_oracle_calls"]

    if "dynvmp_wall_time_sec" not in all_df.columns and "routing_oracle_wall_time_sec" in all_df.columns:
        all_df["dynvmp_wall_time_sec"] = all_df["routing_oracle_wall_time_sec"]

    if "simulation_wall_time_sec" not in all_df.columns:
        for cand in ["sim_wall_time_sec", "total_wall_time_sec", "elapsed_wall_time_sec"]:
            if cand in all_df.columns:
                all_df["simulation_wall_time_sec"] = all_df[cand]
                break

    if args.case:
        all_df = all_df[all_df["case"].isin(args.case)].copy()

    for col in ["fixed_k", "total_arrival_rate", "seed"] + RUNTIME_COLS:
        if col in all_df.columns:
            all_df[col] = pd.to_numeric(all_df[col], errors="coerce")

    missing = [c for c in RUNTIME_COLS if c not in all_df.columns]
    if missing:
        print("ERROR: missing required runtime columns:", missing, file=sys.stderr)
        print("Available columns:", list(all_df.columns), file=sys.stderr)
        raise SystemExit(1)

    suspicious = []
    for _, r in all_df.iterrows():
        if pd.isna(r["dynvmp_calls"]) or r["dynvmp_calls"] <= 0:
            suspicious.append((r.get("_result_file", ""), "dynvmp_calls <= 0 or NaN"))
        if pd.isna(r["dynvmp_wall_time_sec"]) or r["dynvmp_wall_time_sec"] < 0:
            suspicious.append((r.get("_result_file", ""), "dynvmp_wall_time_sec < 0 or NaN"))
        if pd.isna(r["simulation_wall_time_sec"]) or r["simulation_wall_time_sec"] <= 0:
            suspicious.append((r.get("_result_file", ""), "simulation_wall_time_sec <= 0 or NaN"))

    merged_path = output_dir / "k_runtime_merged_runs.csv"
    all_df.to_csv(merged_path, index=False)

    delay_cols = [c for c in DELAY_CANDIDATES if c in all_df.columns]
    for c in delay_cols:
        all_df[c] = pd.to_numeric(all_df[c], errors="coerce")

    group_cols = ["case", "fixed_k"]

    agg = {
        "num_runs": ("dynvmp_calls", "size"),
        "num_rates": ("total_arrival_rate", "nunique"),
        "min_arrival_rate": ("total_arrival_rate", "min"),
        "max_arrival_rate": ("total_arrival_rate", "max"),

        "mean_dynvmp_calls": ("dynvmp_calls", "mean"),
        "std_dynvmp_calls": ("dynvmp_calls", "std"),
        "min_dynvmp_calls": ("dynvmp_calls", "min"),
        "max_dynvmp_calls": ("dynvmp_calls", "max"),

        "mean_dynvmp_wall_time_sec": ("dynvmp_wall_time_sec", "mean"),
        "std_dynvmp_wall_time_sec": ("dynvmp_wall_time_sec", "std"),
        "min_dynvmp_wall_time_sec": ("dynvmp_wall_time_sec", "min"),
        "max_dynvmp_wall_time_sec": ("dynvmp_wall_time_sec", "max"),

        "mean_simulation_wall_time_sec": ("simulation_wall_time_sec", "mean"),
        "std_simulation_wall_time_sec": ("simulation_wall_time_sec", "std"),
        "min_simulation_wall_time_sec": ("simulation_wall_time_sec", "min"),
        "max_simulation_wall_time_sec": ("simulation_wall_time_sec", "max"),
    }

    for c in delay_cols:
        agg[f"mean_{c}"] = (c, "mean")
        agg[f"std_{c}"] = (c, "std")

    summary = (
        all_df
        .groupby(group_cols, dropna=False)
        .agg(**agg)
        .reset_index()
        .sort_values(group_cols)
    )

    for metric, out_col in [
        ("mean_dynvmp_calls", "dynvmp_call_reduction_vs_k1"),
        ("mean_dynvmp_wall_time_sec", "dynvmp_time_reduction_vs_k1"),
        ("mean_simulation_wall_time_sec", "simulation_time_reduction_vs_k1"),
    ]:
        summary = add_reduction_vs_k1(summary, metric, out_col)

    summary_path = output_dir / "paper_table_k_runtime_across_rates.csv"
    summary.to_csv(summary_path, index=False)

    by_rate_agg = {
        "num_runs": ("dynvmp_calls", "size"),
        "mean_dynvmp_calls": ("dynvmp_calls", "mean"),
        "std_dynvmp_calls": ("dynvmp_calls", "std"),
        "mean_dynvmp_wall_time_sec": ("dynvmp_wall_time_sec", "mean"),
        "std_dynvmp_wall_time_sec": ("dynvmp_wall_time_sec", "std"),
        "mean_simulation_wall_time_sec": ("simulation_wall_time_sec", "mean"),
        "std_simulation_wall_time_sec": ("simulation_wall_time_sec", "std"),
    }

    for c in delay_cols:
        by_rate_agg[f"mean_{c}"] = (c, "mean")
        by_rate_agg[f"std_{c}"] = (c, "std")

    by_rate = (
        all_df
        .groupby(["case", "fixed_k", "total_arrival_rate"], dropna=False)
        .agg(**by_rate_agg)
        .reset_index()
        .sort_values(["case", "fixed_k", "total_arrival_rate"])
    )

    by_rate_path = output_dir / "k_runtime_summary_by_rate.csv"
    by_rate.to_csv(by_rate_path, index=False)

    report_path = output_dir / "k_runtime_validation_report.txt"
    with open(report_path, "w", encoding="utf-8") as w:
        w.write("DCNC-DAG K-runtime validation report\n")
        w.write("=" * 60 + "\n")
        w.write(f"Input root: {input_root}\n")
        w.write(f"Found result CSV files: {len(files)}\n")
        w.write(f"Loaded rows after filtering: {len(all_df)}\n")
        if args.commands_csv:
            cmd_path = Path(args.commands_csv)
            w.write(f"Commands CSV: {cmd_path}\n")
            if cmd_path.exists():
                try:
                    cmd_df = pd.read_csv(cmd_path)
                    w.write(f"Commands in CSV: {len(cmd_df)}\n")
                except Exception as e:
                    w.write(f"Could not read commands CSV: {e}\n")
            else:
                w.write("Commands CSV does not exist.\n")
        w.write("\n")

        w.write("Run counts by case and K:\n")
        w.write(summary[["case", "fixed_k", "num_runs", "num_rates"]].to_string(index=False))
        w.write("\n\n")

        w.write("Core mean values by case and K:\n")
        core_cols = [
            "case",
            "fixed_k",
            "mean_dynvmp_calls",
            "mean_dynvmp_wall_time_sec",
            "mean_simulation_wall_time_sec",
            "dynvmp_call_reduction_vs_k1",
            "dynvmp_time_reduction_vs_k1",
            "simulation_time_reduction_vs_k1",
        ]
        w.write(summary[core_cols].to_string(index=False))
        w.write("\n\n")

        if bad_files:
            w.write(f"Bad files: {len(bad_files)}\n")
            for item in bad_files[:30]:
                w.write(str(item) + "\n")
            w.write("\n")

        if suspicious:
            w.write(f"Suspicious rows: {len(suspicious)}\n")
            for item in suspicious[:30]:
                w.write(str(item) + "\n")
            w.write("\n")
        else:
            w.write("Suspicious rows: 0\n")

    print(f"Loaded result CSV files: {len(files)}")
    print(f"Merged runs: {merged_path}")
    print(f"By-rate summary: {by_rate_path}")
    print(f"Paper table: {summary_path}")
    print(f"Validation report: {report_path}")
    print()
    print("Preview of paper table:")
    preview_cols = [
        "case",
        "fixed_k",
        "num_runs",
        "num_rates",
        "mean_dynvmp_calls",
        "mean_dynvmp_wall_time_sec",
        "mean_simulation_wall_time_sec",
        "dynvmp_call_reduction_vs_k1",
        "dynvmp_time_reduction_vs_k1",
        "simulation_time_reduction_vs_k1",
    ]
    print(summary[preview_cols].to_string(index=False))


if __name__ == "__main__":
    main()
