"""Shared aggregation for archived reproduction and newly executed campaigns."""
from __future__ import annotations

from collections import defaultdict
import csv
import json
import os
from pathlib import Path
import subprocess
import sys

import pandas as pd

from dcnc_sim.paper_metrics import normalize_record
from delay_lower_bound import run_lower_bound, export_lower_bounds

ROOT = Path(__file__).resolve().parents[1]


def summarize_rows(kind, rows):
    """Average per-seed metrics; do not pool requests across seeds."""
    df = pd.DataFrame(rows)
    if kind in ("main", "frames"):
        keys = ["case", "policy", "solver", "fixed_k", "rate"]
        delay, ratio = "avg_delay_completed", "completion_ratio"
    elif kind == "workflow":
        keys = ["workflow", "policy", "total_arrival_rate"]
        delay, ratio = "avg_delay_completed", "job_completion_ratio"
    elif kind in ("moe_50000", "moe_100000"):
        keys = ["model", "policy", "arrival_rate"]
        delay, ratio = "mean_completion_delay", "completion_ratio"
    elif kind == "capacity":
        from run_new_7_2_wireless_mixed_mapping import summarize_runs, verify_paired_arrivals
        verify_paired_arrivals(df)
        return summarize_runs(df)
    else:
        raise ValueError(f"No scalar summary for {kind!r}")
    for col in (keys[-1], delay, ratio):
        df[col] = pd.to_numeric(df[col])
    if "fixed_k" in keys:
        df["fixed_k"] = pd.to_numeric(df["fixed_k"])
    agg = dict(seeds=("seed", "size"), avg_delay_completed=(delay, "mean"),
               delay_se=(delay, "sem"), completion_ratio=(ratio, "mean"))
    if kind == "moe_100000":
        df["mean_service_delay_lower_bound"] = pd.to_numeric(df["mean_service_delay_lower_bound"])
        agg["mean_lower_bound"] = ("mean_service_delay_lower_bound", "mean")
    result = df.groupby(keys, as_index=False).agg(**agg)
    # A missing seed metric must not silently become a mean over fewer seeds.
    counts = df.groupby(keys, as_index=False).agg(delay_count=(delay, "count"), ratio_count=(ratio, "count"))
    result.loc[counts.delay_count < result.seeds, ["avg_delay_completed", "delay_se"]] = float("nan")
    result.loc[counts.ratio_count < result.seeds, "completion_ratio"] = float("nan")
    return result


def aggregate_records(jobs, runs_dir, destination, *, protocol_id=None):
    """Read each raw record once and write identical exports for both callers."""
    runs_dir, destination = Path(runs_dir), Path(destination)
    groups, jobs_by_kind = defaultdict(list), defaultdict(list)
    lower_bound_rows = []
    if len({job["id"] for job in jobs}) != len(jobs):
        raise ValueError("Duplicate job IDs in the input manifest")
    for job in jobs:
        path = runs_dir / job["id"] / "result.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        if protocol_id is not None:
            if record.get("protocol_id") != protocol_id or record.get("job") != job:
                raise ValueError(f"Campaign protocol/job mismatch: {path}")
        elif "job" in record and record["job"] != job:
            raise ValueError(f"Job manifest mismatch: {path}")
        try:
            row = normalize_record(job["kind"], record, slots=job.get("params", {}).get("slots"))
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(f"Invalid metrics in {path}: {exc}") from exc
        groups[job["kind"]].append(row)
        jobs_by_kind[job["kind"]].append(job)
        if job["kind"] != "fifo":
            try:
                lower_bound_rows.append(run_lower_bound(job, record))
            except (ValueError, TypeError, KeyError) as exc:
                raise ValueError(f"Invalid lower-bound metrics in {path}: {exc}") from exc
    export_lower_bounds(lower_bound_rows, destination / "delay_lower_bound")
    for kind, rows in groups.items():
        dest = destination / kind
        dest.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(dest / "runs.csv", index=False)
        if kind in ("main", "frames"):
            with (dest / "runs.jsonl").open("w", encoding="utf-8") as stream:
                for row in rows:
                    stream.write(json.dumps(row, allow_nan=False) + "\n")
        if kind != "fifo":
            summarize_rows(kind, rows).to_csv(dest / "summary.csv", index=False)
            continue
        data = dest / "data"
        data.mkdir(exist_ok=True)
        for experiment in ("A", "B"):
            with (data / f"experiment_{experiment}_raw_trajectories.csv").open("w", newline="") as stream:
                writer, first = csv.writer(stream), True
                for job in jobs_by_kind[kind]:
                    if job["params"]["experiment"] != experiment:
                        continue
                    with (runs_dir / job["id"] / "trajectory.csv").open(newline="") as source:
                        reader = csv.reader(source)
                        header = next(reader)
                        if first:
                            writer.writerow(header)
                            first = False
                        writer.writerows(reader)
        env = dict(os.environ, DCNC_FIFO_DATA_DIR=str(data.resolve()))
        subprocess.run([sys.executable, str(ROOT / "scripts/aggregate_backlog.py")], env=env, check=True)
    return dict(groups)
