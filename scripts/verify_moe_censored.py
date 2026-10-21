"""Verify the archived 100k-slot MoE figure data without rerunning simulation."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def run_key(row: dict) -> tuple:
    return row["model"], row["policy"], float(row["arrival_rate"]), int(row["seed"])


def verify_results(root: Path = ROOT) -> dict:
    base = root / "evidence/moe_censored"
    inventory = json.loads((base / "import_manifest.json").read_text(encoding="utf-8"))
    names = set()
    for entry in inventory["files"]:
        path = (base / entry["path"]).resolve()
        require(path.is_relative_to(base.resolve()), "MoE unsafe inventory path")
        require(entry["path"] not in names, "MoE duplicate inventory path")
        names.add(entry["path"])
        content = path.read_bytes()
        require(len(content) == entry["bytes"], f"MoE raw size: {entry['path']}")
        require(hashlib.sha256(content).hexdigest() == entry["sha256"], f"MoE raw hash: {entry['path']}")

    protocol = json.loads((base / "protocol.json").read_text(encoding="utf-8"))
    completion = json.loads((base / "completion.json").read_text(encoding="utf-8"))
    require(completion["protocol_id"] == protocol["protocol_id"], "MoE protocol identity")
    require(completion["completed_jobs"] == completion["expected_jobs"] == protocol["expected_jobs"] == 321, "MoE job count")
    require(protocol["horizon"] == 100000 and protocol["seeds"] == [0, 1, 2], "MoE horizon/seeds")
    for relative, expected in protocol["source_sha256"].items():
        require(hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected, f"MoE simulator source: {relative}")
    reference = root / "evidence/moe/figures/skewed_moe_completed_delay_plot_data.csv"
    require(hashlib.sha256(reference.read_bytes()).hexdigest() == protocol["reference_plot_csv_sha256"], "MoE reference grid hash")
    compatibility = base / "runtime_compatibility_server64.json"
    require(hashlib.sha256(compatibility.read_bytes()).hexdigest() == protocol["compatible_runtime_reuse"]["compatibility_record_sha256"], "MoE runtime compatibility hash")

    expected_keys = {
        (model, policy, rate, seed)
        for model, policies in protocol["rates"].items()
        for policy, rates in policies.items()
        for rate in rates for seed in protocol["seeds"]
    }
    rows = read_csv(base / "run_results.csv")
    require(len(rows) == len(expected_keys) == 321, "MoE row count")
    require({run_key(row) for row in rows} == expected_keys, "MoE run matrix")
    json_rows = [json.loads(path.read_text(encoding="utf-8")) for path in (base / "runs").glob("*.json")]
    by_key = {run_key(row): row for row in json_rows}
    require(len(json_rows) == len(by_key) == 321 and set(by_key) == expected_keys, "MoE JSON run matrix")
    pending_paths = set()
    groups = defaultdict(list)
    pending_records = 0
    numeric_fields = (
        "horizon", "total_arrivals", "total_completions", "unfinished_requests",
        "completion_ratio", "completed_delay_sum_slots", "mean_completion_delay",
        "unfinished_age_sum_slots", "mean_unfinished_age_slots",
        "mean_service_delay_lower_bound", "fixed_100000_penalty_comparison",
    )
    for row in rows:
        key = run_key(row)
        record = by_key[key]
        require(row["protocol_id"] == record["protocol_id"] == protocol["protocol_id"], "MoE row protocol")
        for field in numeric_fields:
            require(float(row[field]) == float(record[field]), f"MoE CSV/JSON mismatch: {key}/{field}")
        horizon = int(row["horizon"])
        require(horizon == protocol["horizon"], "MoE run horizon")
        pending = (base / row["pending_arrivals_file"]).resolve()
        require(pending.is_relative_to((base / "pending_arrivals").resolve()), "MoE unsafe pending path")
        require(pending not in pending_paths, "MoE duplicate pending file")
        pending_paths.add(pending)
        require(hashlib.sha256(pending.read_bytes()).hexdigest() == row["pending_arrivals_sha256"] == record["pending_arrivals_sha256"], "MoE pending hash")
        identities = set()
        age_sum = 0
        with gzip.open(pending, "rt", encoding="utf-8", newline="") as stream:
            for request in csv.DictReader(stream):
                born = int(request["arrival_slot"])
                age = int(request["delay_lower_bound_slots"])
                require(int(request["cutoff_T"]) == horizon and 0 <= born < horizon and age == horizon - born, "MoE pending age")
                require(request["request_id"] not in identities, "MoE duplicate request")
                identities.add(request["request_id"])
                age_sum += age
        arrivals = int(row["total_arrivals"])
        completed = int(row["total_completions"])
        require(arrivals > 0 and len(identities) == int(row["unfinished_requests"]) == arrivals - completed, "MoE arrival accounting")
        require(age_sum == int(row["unfinished_age_sum_slots"]), "MoE age sum")
        completed_sum = float(row["completed_delay_sum_slots"])
        expected = (completed_sum + age_sum) / arrivals
        require(math.isclose(expected, float(row["mean_service_delay_lower_bound"]), rel_tol=1e-12), "MoE lower-bound formula")
        require(math.isclose(completed / arrivals, float(row["completion_ratio"]), rel_tol=1e-12), "MoE completion ratio")
        require(math.isclose(completed_sum / completed, float(row["mean_completion_delay"]), rel_tol=1e-12), "MoE completed-only formula")
        groups[key[:3]].append(row)
        pending_records += len(identities)
    require(pending_paths == {path.resolve() for path in (base / "pending_arrivals").glob("*.csv.gz")}, "MoE extra pending file")
    require(pending_records == 179264, "MoE pending record count")
    plotted = read_csv(base / "plot_data.csv")
    require(len(plotted) == len(groups) == 107, "MoE aggregate count")
    plot_keys = {(row["model"], row["policy"], float(row["arrival_rate"])) for row in plotted}
    require(plot_keys == set(groups), "MoE aggregate grid")
    fields = {
        "mean_lower_bound": "mean_service_delay_lower_bound",
        "mean_completed_only": "mean_completion_delay",
        "mean_penalized": "fixed_100000_penalty_comparison",
        "completion_ratio": "completion_ratio",
        "mean_unfinished_age": "mean_unfinished_age_slots",
    }
    for row in plotted:
        group = groups[(row["model"], row["policy"], float(row["arrival_rate"]))]
        require(int(row["seeds"]) == len(group) == 3, "MoE aggregate seeds")
        for plotted_field, raw_field in fields.items():
            expected = mean(float(run[raw_field]) for run in group)
            require(math.isclose(expected, float(row[plotted_field]), rel_tol=1e-12, abs_tol=1e-9), f"MoE aggregate: {plotted_field}")
    display = displayed_rows(plotted)
    require(len(display) == 106, "MoE display count")
    return {"runs": len(rows), "pending_records": pending_records, "aggregate_points": len(plotted), "displayed_points": len(display)}


def displayed_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows if not (row["model"] == "llama" and row["policy"] == "DCNC-DAG-H" and float(row["arrival_rate"]) == 1.05)]


if __name__ == "__main__":
    print(json.dumps(verify_results(), indent=2))
