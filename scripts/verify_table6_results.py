"""Verify imported Table 6 rows and recompute their runtime summaries."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean

if __package__:
    from .import_table6_results import rate_token, validate_result
else:
    from import_table6_results import rate_token, validate_result


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def verify_results(root: Path, claim: dict) -> dict:
    commands = read_csv(root / claim["evidence"])
    raw_root = root / claim["raw_evidence"]
    inventory = read_csv(raw_root / "source_manifest.csv")
    report = json.loads((raw_root / "import_report.json").read_text(encoding="utf-8"))
    capture = json.loads((root / claim["server_capture"]).read_text(encoding="utf-8"))
    expected = claim["expected_jobs"]
    require(len(commands) == len(inventory) == expected, "Table 6 inventory count")
    require(report["imported_jobs"] == report["expected_jobs"] == expected, "Table 6 import count")
    require(report["commands_sha256"] == claim["command_matrix_sha256"], "Table 6 import matrix")
    require(capture["command_matrix_sha256"] == claim["command_matrix_sha256"], "Table 6 server matrix")
    require(capture["progress"]["final"], "Table 6 server campaign is not final")
    require(not capture["active_campaign_processes"], "Table 6 campaign still active")
    exits = capture["exit_records"]
    require(len(exits) == len({entry["filename"] for entry in exits}) == expected, "Table 6 exit count")
    require(all(entry["exit_code"] == 0 for entry in exits), "Table 6 failed exit")
    fingerprint = json.loads((root / claim["runtime_fingerprint"]).read_text(encoding="utf-8"))
    require(capture["source_sha256"] == fingerprint["remote_executed_sha256"], "Table 6 source fingerprint")
    remote_files = {entry["path"]: entry for entry in capture["files"]}
    require(len(remote_files) == len(capture["files"]) == expected, "Table 6 remote inventory")
    records = []
    paths = set()
    keys = set()
    for index, (command, entry) in enumerate(zip(commands, inventory), start=1):
        key = (command["case"], int(command["K"]), float(command["total_arrival_rate"]), int(command["seed"]))
        require(key not in keys, "Table 6 duplicate command")
        keys.add(key)
        relative = Path(key[0], f"k{key[1]}", rate_token(command["total_arrival_rate"]), f"s{key[3]}", report["result_filename"])
        require(entry["artifact_relative_path"] == relative.as_posix(), "Table 6 inventory path")
        require(int(entry["command_index"]) == index, "Table 6 inventory index")
        source_path = command["output_dir"] + "/" + report["result_filename"]
        require(entry["source_relative_path"] == source_path, "Table 6 source path")
        remote = remote_files[source_path.split("/", 1)[1]]
        path = raw_root / relative
        paths.add(path)
        content = path.read_bytes()
        require(hashlib.sha256(content).hexdigest() == entry["sha256"] == remote["sha256"], f"Table 6 raw hash: {relative}")
        require(len(content) == int(entry["bytes"]) == remote["bytes"], f"Table 6 raw size: {relative}")
        record, errors = validate_result(command, path)
        require(not errors, "; ".join(errors))
        require(record["interference_model"] == "primary", "Table 6 interference model")
        require(float(record["dynvmp_calls"]) == float(record["routing_oracle_calls"]), "Table 6 call counters")
        require(float(record["dynvmp_wall_time_sec"]) == float(record["routing_oracle_wall_time_sec"]), "Table 6 timing counters")
        require(float(record["simulation_wall_time_sec"]) >= float(record["dynvmp_wall_time_sec"]), "Table 6 timing boundary")
        records.append(record)
    require(paths == set(raw_root.rglob(report["result_filename"])), "Table 6 extra or missing raw files")

    grouped = defaultdict(list)
    for record in records:
        grouped[(record["case"], int(record["fixed_k"]))].append(record)
    summaries = read_csv(root / claim["summary_evidence"])
    summary_keys = {(row["case"], int(row["fixed_k"])) for row in summaries}
    require(summary_keys == set(grouped) and len(summaries) == len(grouped) == 10, "Table 6 summary groups")
    metrics = ("dynvmp_calls", "dynvmp_wall_time_sec", "simulation_wall_time_sec")
    for summary in summaries:
        key = (summary["case"], int(summary["fixed_k"]))
        group = grouped[key]
        require(len(group) == int(summary["num_runs"]) == 15, "Table 6 runs per group")
        require(len({row["total_arrival_rate"] for row in group}) == int(summary["num_rates"]) == 5, "Table 6 rates per group")
        for metric in metrics:
            observed = mean(float(row[metric]) for row in group)
            require(math.isclose(observed, float(summary["mean_" + metric]), rel_tol=1e-12, abs_tol=1e-9), f"Table 6 summary: {key}/{metric}")
        for metric, column in (
            ("dynvmp_calls", "dynvmp_call_reduction_vs_k1"),
            ("dynvmp_wall_time_sec", "dynvmp_time_reduction_vs_k1"),
            ("simulation_wall_time_sec", "simulation_time_reduction_vs_k1"),
        ):
            baseline = mean(float(row[metric]) for row in grouped[(key[0], 1)])
            observed = 1.0 - mean(float(row[metric]) for row in group) / baseline
            require(math.isclose(observed, float(summary[column]), rel_tol=1e-12, abs_tol=1e-12), f"Table 6 reduction: {key}/{metric}")

    observed_calls = {}
    observed_times = {}
    for (case, frame), group in sorted(grouped.items()):
        calls = mean(float(row["dynvmp_calls"]) for row in group)
        seconds = mean(float(row["dynvmp_wall_time_sec"]) / int(row["total_slots"]) for row in group)
        require(round(calls, 1) == claim["paper_calls"][case][str(frame)], f"Table 6 paper call count: {case}/{frame}")
        observed_calls.setdefault(case, {})[str(frame)] = calls
        observed_times.setdefault(case, {})[str(frame)] = seconds
    require(observed_calls == claim["observed_calls"], "Table 6 declared observed calls")
    for case, frames in observed_times.items():
        for frame, seconds in frames.items():
            require(math.isclose(seconds, claim["observed_seconds_per_slot"][case][frame], rel_tol=1e-12), "Table 6 declared observed timing")
    mismatches = sum(
        round(seconds, 4 if seconds < 0.1 else 3) != claim["paper_seconds_per_slot"][case][frame]
        for case, frames in observed_times.items() for frame, seconds in frames.items()
    )
    require(claim["timing_status"] in {"paper-timing-mismatch", "exact-source-provenance"}, "Unknown Table 6 timing status")
    expected_mismatches = 0 if claim["timing_status"] == "exact-source-provenance" else 10
    require(mismatches == expected_mismatches, "Table 6 timing mismatch classification changed; review the release gate")
    return {"validated_runs": len(records), "summary_rows": len(summaries), "paper_timing_mismatches": mismatches}
