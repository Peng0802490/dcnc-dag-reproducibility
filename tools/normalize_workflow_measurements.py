"""Optional new workload normalization from public measurements.

This tool does not explain or regenerate the historical fixed r/xi factors.
It requires explicit user-chosen scales and writes a separate comparison table.
"""
import argparse
import csv
import math
from pathlib import Path
from input_builders import CONSTRUCTION, read_csv


def normalize(value, scale, minimum=None, maximum=None):
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("Normalization scales must be positive and finite")
    if minimum is not None and (not math.isfinite(minimum) or minimum < 0):
        raise ValueError("Minimum must be nonnegative and finite")
    if maximum is not None and (not math.isfinite(maximum) or maximum < 0):
        raise ValueError("Maximum must be nonnegative and finite")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError("Minimum exceeds maximum")
    if value in ("", None):
        return None
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError("Measurements must be nonnegative and finite")
    result = value / scale
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def comparison(workflow, seconds_per_unit, bytes_per_unit, minimum=None, maximum=None):
    rows = []
    specs = [
        ("workflow_node_parameters.csv", "r", "public_runtime_seconds", seconds_per_unit),
        ("workflow_edge_parameters.csv", "xi", "public_shared_bytes", bytes_per_unit),
    ]
    for filename, metric, measurement, scale in specs:
        for row in read_csv(CONSTRUCTION / filename):
            if row["workflow"] != workflow:
                continue
            value = normalize(row[measurement], scale, minimum, maximum)
            rows.append(dict(workflow=workflow, metric=metric,
                item=row["service_task"] if metric == "r" else row["source"] + " -> " + row["target"],
                public_measurement=row[measurement], units_per_workload=scale,
                minimum=minimum, maximum=maximum, new_normalized_value=value,
                archived_fixed_value=row[metric],
                status="measurement_unavailable" if value is None else "new_normalization_not_historical"))
    return rows


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workflow", choices=["srasearch22", "sipht31"], required=True)
    p.add_argument("--seconds-per-unit", type=float, required=True)
    p.add_argument("--bytes-per-unit", type=float, required=True)
    p.add_argument("--minimum", type=float)
    p.add_argument("--maximum", type=float)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    rows = comparison(a.workflow, a.seconds_per_unit, a.bytes_per_unit, a.minimum, a.maximum)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
