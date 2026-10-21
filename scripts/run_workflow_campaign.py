#!/usr/bin/env python3
"""Run all three workflow seeds and aggregate the paper-facing results.

The command matrix is shipped inside this artifact.  The merged CSV applies
the completion-ratio gate and survivorship-aware plotting rule used by the
paper.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "inputs/command_csv/workflow_random_allnodes_final_50000_seed0_dense_v2.csv"
DEFAULT_OUT = ROOT / "results/workflow_random_allnodes_50000_seed012"
PYTHON = Path(sys.executable)
POLICY_ORDER = ["DCNC-DAG-H", "CTS", "Random"]
MAX_RATES = {
    ("srasearch22", "DCNC-DAG-H"): 0.16,
    ("srasearch22", "CTS"): 0.09,
    ("srasearch22", "Random"): 0.04,
    ("sipht31", "DCNC-DAG-H"): 0.32,
    ("sipht31", "CTS"): 0.225,
    ("sipht31", "Random"): 0.075,
}


def rate_tag(rate: float) -> str:
    return f"{rate:.4f}".replace(".", "p")


def build_jobs(out_root: Path) -> list[dict]:
    with MATRIX.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    jobs = []
    for row in rows:
        max_rate = MAX_RATES[(row["workflow"], row["policy_label"])]
        if float(row["rate"]) > max_rate + 1e-12:
            continue
        for seed in (0, 1, 2):
            output_dir = (
                out_root
                / row["workflow"]
                / f"rate_{rate_tag(float(row['rate']))}"
                / row["policy_label"]
                / f"seed_{seed}"
            )
            jobs.append({**row, "seed": seed, "output_dir": output_dir})
    return jobs


def run_job(job: dict) -> dict:
    output_dir = Path(job["output_dir"])
    result_csv = output_dir / "workflow_case_results.csv"
    if result_csv.exists():
        return {"status": "cached", "result": str(result_csv), **job}

    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(PYTHON),
        "scripts/run_workflow_case.py",
        "--config", f"legacy_inputs/{job['config']}",
        "--output-dir", str(output_dir),
        "--slots", job["slots"],
        "--seeds", "1",
        "--seed-start", str(job["seed"]),
        "--rate", job["rate"],
        "--policy", job["policy_arg"],
        "--fixed-k", job["fixed_k"],
        "--interference-model", "primary",
        "--progress-every", "5000",
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    started = time.time()
    completed = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    (output_dir / "run.log").write_text(completed.stdout, encoding="utf-8")
    status = "ok" if completed.returncode == 0 and result_csv.exists() else "error"
    return {
        "status": status,
        "returncode": completed.returncode,
        "wall_sec": round(time.time() - started, 2),
        "result": str(result_csv),
        **job,
    }


def collect_results(out_root: Path) -> pd.DataFrame:
    paths = sorted(out_root.glob("**/workflow_case_results.csv"))
    if not paths:
        raise RuntimeError("no workflow result CSV files found")
    frames = [pd.read_csv(path).assign(source_csv=str(path)) for path in paths]
    raw = pd.concat(frames, ignore_index=True)
    raw["workflow"] = raw["workflow"].replace(
        {
            "workflow_srasearch22": "SRA-Search-22",
            "workflow_sipht31": "SIPHT-31",
        }
    )
    matrix = pd.read_csv(MATRIX)
    keep = matrix.apply(
        lambda row: float(row["rate"])
        <= MAX_RATES[(row["workflow"], row["policy_label"])] + 1e-12,
        axis=1,
    )
    allowed = matrix.loc[
        keep, ["workflow_label", "policy_label", "rate"]
    ].rename(
        columns={
            "workflow_label": "workflow",
            "policy_label": "policy_display",
            "rate": "total_arrival_rate",
        }
    )
    raw = raw.merge(
        allowed.drop_duplicates(),
        on=["workflow", "policy_display", "total_arrival_rate"],
        how="inner",
    )
    raw = raw.drop_duplicates(
        subset=["workflow", "policy_display", "total_arrival_rate", "seed"],
        keep="last",
    )
    return raw


def summarize(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    keys = ["workflow", "policy_display", "total_arrival_rate"]
    summary = (
        raw.groupby(keys, as_index=False)
        .agg(
            seeds=("seed", "nunique"),
            avg_delay_completed=("avg_delay_completed", "mean"),
            delay_std=("avg_delay_completed", "std"),
            completion_ratio=("job_completion_ratio", "mean"),
            completion_ratio_std=("job_completion_ratio", "std"),
        )
        .sort_values(keys)
    )
    summary["delay_se"] = summary["delay_std"] / summary["seeds"].map(math.sqrt)
    summary["completion_ratio_se"] = (
        summary["completion_ratio_std"] / summary["seeds"].map(math.sqrt)
    )
    if (summary["seeds"] != 3).any():
        bad = summary.loc[summary["seeds"] != 3, keys + ["seeds"]]
        raise RuntimeError(f"not every point has three seeds:\n{bad.to_string(index=False)}")

    threshold_rows = []
    plot_parts = []
    for (workflow, policy), group in summary.groupby(["workflow", "policy_display"]):
        group = group.sort_values("total_arrival_rate").reset_index(drop=True)
        accepted = group[group["completion_ratio"] >= 0.95]
        if accepted.empty:
            raise RuntimeError(f"no accepted rate for {workflow}/{policy}")
        accepted_index = int(accepted.index.max())
        threshold = group.loc[accepted_index]
        keep_through = accepted_index
        rejected = group.index[group.index > accepted_index]
        if len(rejected):
            first_rejected = int(rejected[0])
            if (
                group.loc[first_rejected, "completion_ratio"] < 0.95
                and group.loc[first_rejected, "avg_delay_completed"]
                > threshold["avg_delay_completed"]
            ):
                keep_through = first_rejected
        plot_parts.append(group.loc[:keep_through])
        threshold_rows.append(
            {
                "workflow": workflow,
                "policy": policy,
                "lambda_hat": threshold["total_arrival_rate"],
                "completion_ratio_at_lambda_hat": threshold["completion_ratio"],
                "delay_at_lambda_hat": threshold["avg_delay_completed"],
                "delay_se_at_lambda_hat": threshold["delay_se"],
            }
        )

    plot = pd.concat(plot_parts, ignore_index=True)
    plot = plot.rename(
        columns={
            "policy_display": "policy",
            "total_arrival_rate": "arrival_rate",
        }
    )[["workflow", "policy", "arrival_rate", "avg_delay_completed", "delay_se"]]
    thresholds = pd.DataFrame(threshold_rows)
    return summary, thresholds, plot


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--workers", type=int, default=80)
    args = parser.parse_args()
    args.out_root.mkdir(parents=True, exist_ok=True)

    jobs = build_jobs(args.out_root)
    statuses = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(run_job, job): job for job in jobs}
        for index, future in enumerate(as_completed(futures), 1):
            result = future.result()
            statuses.append(result)
            if result["status"] == "error" or index % 20 == 0 or index == len(jobs):
                print(
                    f"{index}/{len(jobs)} status={result['status']} "
                    f"workflow={result['workflow']} policy={result['policy_label']} "
                    f"rate={result['rate']} seed={result['seed']}",
                    flush=True,
                )

    status_df = pd.DataFrame(statuses)
    status_df.to_csv(args.out_root / "status.csv", index=False)
    errors = status_df[status_df["status"] == "error"]
    if not errors.empty:
        raise RuntimeError(f"{len(errors)} workflow jobs failed; inspect status.csv")

    raw = collect_results(args.out_root)
    summary, thresholds, plot = summarize(raw)
    raw.to_csv(args.out_root / "workflow_three_seed_raw.csv", index=False)
    summary.to_csv(args.out_root / "workflow_three_seed_summary.csv", index=False)
    thresholds.to_csv(args.out_root / "workflow_three_seed_thresholds.csv", index=False)
    plot.to_csv(args.out_root / "plot_completed_delay_data.csv", index=False)
    print(thresholds.to_string(index=False))


if __name__ == "__main__":
    main()
