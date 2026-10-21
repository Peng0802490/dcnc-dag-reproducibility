#!/usr/bin/env python3
"""Validate incremental physical metrics against full queue scans."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


KEYS = ["policy", "arrival_rate", "seed"]
EXACT_TEXT = ["arrival_path_sha256", "wireless_path_sha256"]
EXACT_NUMERIC = [
    "total_arrivals",
    "completed_requests",
    "completed_throughput",
    "completion_ratio",
    "mapping_calls",
    "share_m1_requests",
    "share_m1_calls",
]
SLOPES = [
    "physical_object_backlog_tail_slope",
    "physical_workload_tail_slope",
    "virtual_workload_tail_slope",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan-runs", type=Path, required=True)
    parser.add_argument("--incremental-runs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    scan = pd.read_csv(args.scan_runs)
    incremental = pd.read_csv(args.incremental_runs)
    merged = scan.merge(
        incremental,
        on=KEYS,
        suffixes=("_scan", "_incremental"),
        validate="one_to_one",
    )
    if len(merged) != len(scan):
        raise AssertionError("not every completed scan row has an incremental match")

    for column in EXACT_TEXT:
        if not merged["{}_scan".format(column)].equals(
            merged["{}_incremental".format(column)]
        ):
            raise AssertionError("{} differs".format(column))

    exact_numeric_max_differences = {}
    for column in EXACT_NUMERIC:
        difference = np.abs(
            merged["{}_scan".format(column)].astype(float)
            - merged["{}_incremental".format(column)].astype(float)
        )
        maximum = float(difference.max())
        exact_numeric_max_differences[column] = maximum
        if maximum != 0.0:
            raise AssertionError("{} is not bit-exact".format(column))

    slope_max_differences = {}
    for column in SLOPES:
        difference = np.abs(
            merged["{}_scan".format(column)].astype(float)
            - merged["{}_incremental".format(column)].astype(float)
        )
        slope_max_differences[column] = float(difference.max())
    if slope_max_differences["physical_object_backlog_tail_slope"] != 0.0:
        raise AssertionError("object-count slopes differ")
    if slope_max_differences["virtual_workload_tail_slope"] != 0.0:
        raise AssertionError("virtual-workload slopes differ")
    if slope_max_differences["physical_workload_tail_slope"] >= 1e-12:
        raise AssertionError("physical-workload slope difference is at least 1e-12")

    groups = (
        merged.groupby(["policy", "arrival_rate"])
        .size()
        .reset_index(name="matched_seeds")
        .to_dict(orient="records")
    )
    report = {
        "checks_passed": True,
        "matched_rows": int(len(merged)),
        "scan_reference_is_partial_and_non_paper_facing": True,
        "matched_groups": groups,
        "exact_numeric_max_absolute_differences": exact_numeric_max_differences,
        "path_hashes_match_exactly": True,
        "slope_max_absolute_differences": slope_max_differences,
        "acceptance_tolerance_physical_workload_slope": 1e-12,
        "scan_runs_sha256": sha256(args.scan_runs),
        "incremental_runs_sha256": sha256(args.incremental_runs),
        "interpretation": (
            "Incremental collection changes only measurement cost. All compared "
            "simulation behavior is bit-exact; the sub-1e-12 physical slope "
            "difference is floating-point summation order."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
