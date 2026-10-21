#!/usr/bin/env python3
"""Independently audit and format the Section 7.2 simulation outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Dict, Iterable, List

import numpy as np
import pandas as pd


MAIN_RATES = (0.95, 0.98, 0.99, 1.01, 1.03, 1.05, 1.10)
ABLATION_RATES = (0.45, 0.49, 0.50, 0.51, 0.55, 0.95, 0.98, 0.99, 1.01, 1.03, 1.05, 1.10)
SEEDS = (0, 1, 2, 3, 4)
SLOPE_CUTOFF = 5e-2


def standard_error(values: pd.Series) -> float:
    return float(values.std(ddof=1) / math.sqrt(len(values)))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def assert_rate_seed_grid(runs: pd.DataFrame, policy: str, rates: Iterable[float]) -> None:
    subset = runs[runs["policy"] == policy]
    actual_rates = sorted(float(value) for value in subset["arrival_rate"].unique())
    expected_rates = sorted(float(value) for value in rates)
    if actual_rates != expected_rates:
        raise AssertionError(
            "{} rate grid differs: expected {}, got {}".format(
                policy, expected_rates, actual_rates
            )
        )
    counts = subset.groupby("arrival_rate")["seed"].agg(list)
    for rate, seed_values in counts.items():
        if sorted(int(value) for value in seed_values) != list(SEEDS):
            raise AssertionError("{} rate {} has seeds {}".format(policy, rate, seed_values))


def recompute_summary(runs: pd.DataFrame) -> pd.DataFrame:
    return (
        runs.groupby(["policy", "arrival_rate"], as_index=False)
        .agg(
            completed_throughput=("completed_throughput", "mean"),
            completed_throughput_se=("completed_throughput", standard_error),
            completion_ratio=("completion_ratio", "mean"),
            completion_ratio_se=("completion_ratio", standard_error),
            share_m1_requests=("share_m1_requests", "mean"),
            share_m1_requests_se=("share_m1_requests", standard_error),
            share_m1_calls=("share_m1_calls", "mean"),
            physical_object_backlog_tail_slope=(
                "physical_object_backlog_tail_slope",
                "mean",
            ),
            physical_object_backlog_tail_slope_se=(
                "physical_object_backlog_tail_slope",
                standard_error,
            ),
            physical_workload_tail_slope=("physical_workload_tail_slope", "mean"),
            physical_workload_tail_slope_se=(
                "physical_workload_tail_slope",
                standard_error,
            ),
            virtual_workload_tail_slope=("virtual_workload_tail_slope", "mean"),
            virtual_workload_tail_slope_se=(
                "virtual_workload_tail_slope",
                standard_error,
            ),
            physical_object_flags=("physical_object_flag", "sum"),
            physical_workload_flags=("physical_workload_flag", "sum"),
            virtual_workload_flags=("virtual_workload_flag", "sum"),
            backlog_flags=("backlog_flag", "sum"),
            legacy_object_or_virtual_flags=("legacy_object_or_virtual_flag", "sum"),
        )
        .sort_values(["policy", "arrival_rate"])
        .reset_index(drop=True)
    )


def compare_summaries(expected: pd.DataFrame, actual: pd.DataFrame) -> None:
    key_columns = ["policy", "arrival_rate"]
    if not expected[key_columns].equals(actual[key_columns]):
        raise AssertionError("summary policy/rate keys do not match recomputed keys")
    for column in expected.columns:
        if column in key_columns:
            continue
        left = expected[column].to_numpy(dtype=float)
        right = actual[column].to_numpy(dtype=float)
        if not np.allclose(left, right, rtol=0.0, atol=1e-12, equal_nan=True):
            raise AssertionError("summary column {} differs from raw-data aggregation".format(column))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    campaign_dir = args.campaign_dir
    output_dir = args.output_dir or campaign_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    runs_path = campaign_dir / "runs.csv"
    summary_path = campaign_dir / "summary.csv"
    metadata_path = campaign_dir / "metadata.json"
    lp_path = campaign_dir / "lp_decomposition.csv"
    runs = pd.read_csv(runs_path)
    supplied_summary = pd.read_csv(summary_path).sort_values(
        ["policy", "arrival_rate"]
    ).reset_index(drop=True)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    lp = pd.read_csv(lp_path)

    if len(runs) != 95:
        raise AssertionError("expected 95 raw runs, found {}".format(len(runs)))
    if runs.duplicated(["policy", "arrival_rate", "seed"]).any():
        raise AssertionError("duplicate policy/rate/seed records found")
    if set(runs["slots"].astype(int)) != {100_000}:
        raise AssertionError("not every run used 100000 slots")
    assert_rate_seed_grid(runs, "mixed", MAIN_RATES)
    assert_rate_seed_grid(runs, "single_m1", ABLATION_RATES)

    expected_throughput = runs["completed_requests"] / runs["slots"]
    expected_ratio = runs["completed_requests"] / runs["total_arrivals"]
    if not np.allclose(runs["completed_throughput"], expected_throughput, atol=1e-15):
        raise AssertionError("completed-throughput arithmetic is inconsistent")
    if not np.allclose(runs["completion_ratio"], expected_ratio, atol=1e-15):
        raise AssertionError("completion-ratio arithmetic is inconsistent")

    expected_object_flag = runs["physical_object_backlog_tail_slope"] > SLOPE_CUTOFF
    expected_physical_flag = runs["physical_workload_tail_slope"] > SLOPE_CUTOFF
    expected_virtual_flag = runs["virtual_workload_tail_slope"] > SLOPE_CUTOFF
    expected_backlog_flag = expected_physical_flag | expected_virtual_flag
    expected_legacy_flag = expected_object_flag | expected_virtual_flag
    if not np.array_equal(runs["physical_object_flag"].astype(bool), expected_object_flag):
        raise AssertionError("physical object-count flags cannot be reproduced")
    if not np.array_equal(runs["physical_workload_flag"].astype(bool), expected_physical_flag):
        raise AssertionError("physical workload flags cannot be reproduced")
    if not np.array_equal(runs["virtual_workload_flag"].astype(bool), expected_virtual_flag):
        raise AssertionError("virtual workload flags cannot be reproduced")
    if not np.array_equal(runs["backlog_flag"].astype(bool), expected_backlog_flag):
        raise AssertionError("combined backlog flags cannot be reproduced")
    if not np.array_equal(
        runs["legacy_object_or_virtual_flag"].astype(bool), expected_legacy_flag
    ):
        raise AssertionError("legacy object-or-virtual flags cannot be reproduced")

    main = runs[runs["policy"] == "mixed"]
    ablation = runs[runs["policy"] == "single_m1"]
    paired = main.merge(
        ablation,
        on=["arrival_rate", "seed"],
        suffixes=("_main", "_ablation"),
    )
    if len(paired) != len(MAIN_RATES) * len(SEEDS):
        raise AssertionError("not every main run has a paired ablation run")
    if not (
        paired["arrival_path_sha256_main"]
        == paired["arrival_path_sha256_ablation"]
    ).all():
        raise AssertionError("paired arrival sample paths differ")
    if not (
        paired["wireless_path_sha256_main"]
        == paired["wireless_path_sha256_ablation"]
    ).all():
        raise AssertionError("paired wireless sample paths differ")
    if not (runs.groupby("seed")["wireless_path_sha256"].nunique() == 1).all():
        raise AssertionError("wireless path changes across rates/policies for a seed")
    if runs.groupby("seed")["wireless_path_sha256"].first().nunique() != len(SEEDS):
        raise AssertionError("different logical seeds do not have distinct wireless paths")

    recomputed = recompute_summary(runs)
    compare_summaries(recomputed, supplied_summary)

    if not math.isclose(float(metadata["lp_lambda_star"]), 1.0, abs_tol=1e-12):
        raise AssertionError("metadata lambda* is not 1")
    if str(metadata.get("python_hash_seed")) != "0":
        raise AssertionError("canonical campaign did not fix PYTHONHASHSEED=0")
    if not metadata.get("paired_wireless_paths_verified"):
        raise AssertionError("metadata does not confirm paired wireless paths")
    if len(lp) != 2:
        raise AssertionError("LP decomposition does not contain two mappings")
    if not np.allclose(lp["single_mapping_capacity"], 0.5, atol=1e-12):
        raise AssertionError("a single-mapping capacity differs from 0.5")
    if not np.allclose(lp["mixed_lp_rate"], 0.5, atol=1e-12):
        raise AssertionError("mixed LP rates differ from 0.5/0.5")

    main_summary = recomputed[recomputed["policy"] == "mixed"].copy()
    subcritical = main_summary[main_summary["arrival_rate"] <= 0.99]
    if not (subcritical["backlog_flags"] == 0).all():
        raise AssertionError("a subcritical main run was backlog-flagged")
    if not (subcritical["completion_ratio"] > 0.9997).all():
        raise AssertionError("a subcritical main completion ratio is unexpectedly low")
    if not (
        abs(subcritical["completed_throughput"] - subcritical["arrival_rate"]) < 1e-3
    ).all():
        raise AssertionError("subcritical throughput does not track the offered rate")
    if not (abs(main_summary["share_m1_requests"] - 0.5) < 1e-2).all():
        raise AssertionError("a main mapping share is not close to the LP mixture")

    overloaded = main_summary[main_summary["arrival_rate"] > 1.0]
    fully_flagged = overloaded[overloaded["backlog_flags"] == len(SEEDS)]
    first_flagged_rate = float(fully_flagged["arrival_rate"].min())
    if not math.isclose(first_flagged_rate, 1.05, abs_tol=1e-12):
        raise AssertionError("first workload-based reliable overload flag is not at 1.05")
    legacy_fully_flagged = overloaded[
        overloaded["legacy_object_or_virtual_flags"] == len(SEEDS)
    ]
    legacy_first_flagged_rate = float(legacy_fully_flagged["arrival_rate"].min())
    if not math.isclose(legacy_first_flagged_rate, 1.03, abs_tol=1e-12):
        raise AssertionError("first object-count sensitivity flag is not at 1.03")
    if int(
        main_summary.loc[main_summary["arrival_rate"] == 1.01, "backlog_flags"].iloc[0]
    ) != 0:
        raise AssertionError("the 1.01 main point should not be backlog-flagged")

    single_099 = recomputed[
        (recomputed["policy"] == "single_m1")
        & np.isclose(recomputed["arrival_rate"], 0.99)
    ].iloc[0]
    if not math.isclose(
        float(single_099["completed_throughput"]), 0.5, abs_tol=1e-3
    ):
        raise AssertionError("single-mapping throughput at 0.99 does not saturate at 0.5")

    paper_columns = [
        "arrival_rate",
        "completed_throughput",
        "completed_throughput_se",
        "completion_ratio",
        "completion_ratio_se",
        "share_m1_requests",
        "share_m1_requests_se",
        "physical_object_backlog_tail_slope",
        "physical_workload_tail_slope",
        "virtual_workload_tail_slope",
        "physical_object_flags",
        "physical_workload_flags",
        "virtual_workload_flags",
        "backlog_flags",
        "legacy_object_or_virtual_flags",
    ]
    main_summary[paper_columns].to_csv(output_dir / "paper_table_main.csv", index=False)
    recomputed[recomputed["policy"] == "single_m1"][paper_columns].to_csv(
        output_dir / "paper_table_ablation.csv", index=False
    )

    report: Dict[str, object] = {
        "checks_passed": True,
        "raw_run_count": len(runs),
        "main_run_count": len(main),
        "ablation_run_count": len(ablation),
        "seeds_per_point": len(SEEDS),
        "slots_per_run": 100_000,
        "lp_lambda_star": 1.0,
        "lp_mapping_rates": [0.5, 0.5],
        "single_mapping_capacities": [0.5, 0.5],
        "first_reliably_flagged_rate": first_flagged_rate,
        "overload_resolution_percent": 100.0 * (first_flagged_rate - 1.0),
        "object_count_sensitivity_first_flagged_rate": legacy_first_flagged_rate,
        "object_count_sensitivity_resolution_percent": 100.0
        * (legacy_first_flagged_rate - 1.0),
        "maximum_standard_errors_main": {
            "completed_throughput": float(main_summary["completed_throughput_se"].max()),
            "completion_ratio": float(main_summary["completion_ratio_se"].max()),
            "share_m1_requests": float(main_summary["share_m1_requests_se"].max()),
        },
        "single_m1_at_0p99": {
            "completed_throughput": float(single_099["completed_throughput"]),
            "completed_throughput_se": float(single_099["completed_throughput_se"]),
            "completion_ratio": float(single_099["completion_ratio"]),
        },
        "sha256": {
            "runs.csv": sha256(runs_path),
            "summary.csv": sha256(summary_path),
            "metadata.json": sha256(metadata_path),
            "lp_decomposition.csv": sha256(lp_path),
        },
    }
    (output_dir / "audit_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
