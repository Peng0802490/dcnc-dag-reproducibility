#!/usr/bin/env python3
"""Validate and copy only canonical per-run Table 6 CSV evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMMANDS = ROOT / "evidence" / "table6" / "commands.csv"
RESULT_NAME = "edge_experiments_all_results.csv"
REQUIRED_RESULT_FIELDS = {
    "case",
    "policy",
    "seed",
    "total_slots",
    "total_arrival_rate",
    "fixed_k",
    "dcnc_solver",
    "dynvmp_calls",
    "dynvmp_wall_time_sec",
    "simulation_wall_time_sec",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rate_token(value: str) -> str:
    return "r" + format(float(value), ".12g").replace(".", "p")


def source_result_path(input_root: Path, output_dir: str) -> Path:
    relative = Path(output_dir.replace("\\", "/"))
    candidates = [input_root / relative / RESULT_NAME]
    if relative.parts and relative.parts[0] == input_root.name:
        candidates.insert(0, input_root.joinpath(*relative.parts[1:]) / RESULT_NAME)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def validate_result(command: dict[str, str], path: Path) -> tuple[dict[str, str] | None, list[str]]:
    errors: list[str] = []
    if not path.is_file():
        return None, [f"missing result: {path}"]
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            fields = set(reader.fieldnames or [])
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        return None, [f"cannot read {path}: {exc}"]
    missing_fields = sorted(REQUIRED_RESULT_FIELDS - fields)
    if missing_fields:
        errors.append(f"{path}: missing columns {missing_fields}")
    if len(rows) != 1:
        errors.append(f"{path}: expected exactly one result row, found {len(rows)}")
    if errors:
        return None, errors

    row = rows[0]
    string_checks = {
        "case": command["case"],
        "policy": command["policy"],
        "dcnc_solver": command["solver"],
    }
    for field, expected in string_checks.items():
        if row[field] != expected:
            errors.append(f"{path}: {field}={row[field]!r}, expected {expected!r}")

    integer_checks = {
        "seed": int(command["seed"]),
        "total_slots": int(command["slots"]),
        "fixed_k": int(command["K"]),
    }
    for field, expected in integer_checks.items():
        try:
            observed = int(float(row[field]))
        except (TypeError, ValueError):
            errors.append(f"{path}: {field} is not numeric: {row[field]!r}")
            continue
        if observed != expected:
            errors.append(f"{path}: {field}={observed}, expected {expected}")

    try:
        observed_rate = float(row["total_arrival_rate"])
        expected_rate = float(command["total_arrival_rate"])
        if not math.isclose(observed_rate, expected_rate, rel_tol=0.0, abs_tol=1e-12):
            errors.append(
                f"{path}: total_arrival_rate={observed_rate}, expected {expected_rate}"
            )
    except (TypeError, ValueError):
        errors.append(
            f"{path}: total_arrival_rate is not numeric: {row['total_arrival_rate']!r}"
        )

    for field in ("dynvmp_calls", "dynvmp_wall_time_sec", "simulation_wall_time_sec"):
        try:
            value = float(row[field])
        except (TypeError, ValueError):
            errors.append(f"{path}: {field} is not numeric: {row[field]!r}")
            continue
        if not math.isfinite(value) or value <= 0:
            errors.append(f"{path}: {field} must be finite and positive, found {value}")
        if field == "dynvmp_calls" and math.isfinite(value) and not value.is_integer():
            errors.append(f"{path}: dynvmp_calls must be an integer, found {value}")
    return (row if not errors else None), errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--commands-csv", type=Path, default=DEFAULT_COMMANDS)
    args = parser.parse_args()

    input_root = args.input_root
    output_root = args.output_root
    if not input_root.is_dir():
        parser.error(f"input root does not exist: {input_root}")
    if output_root.exists():
        parser.error(f"output root already exists; refusing to overwrite: {output_root}")

    with args.commands_csv.open(newline="", encoding="utf-8") as handle:
        commands = list(csv.DictReader(handle))
    if not commands:
        parser.error("commands CSV contains no jobs")

    validated: list[tuple[int, dict[str, str], Path]] = []
    errors: list[str] = []
    seen_keys: set[tuple[str, int, float, int]] = set()
    for index, command in enumerate(commands, start=1):
        key = (
            command["case"],
            int(command["K"]),
            float(command["total_arrival_rate"]),
            int(command["seed"]),
        )
        if key in seen_keys:
            errors.append(f"duplicate command key: {key}")
            continue
        seen_keys.add(key)
        path = source_result_path(input_root, command["output_dir"])
        row, row_errors = validate_result(command, path)
        errors.extend(row_errors)
        if row is not None:
            validated.append((index, command, path))

    if errors:
        print(
            f"Table 6 import rejected: {len(errors)} validation issue(s); "
            f"validated {len(validated)}/{len(commands)} jobs.",
            file=sys.stderr,
        )
        for error in errors[:50]:
            print(f"  - {error}", file=sys.stderr)
        if len(errors) > 50:
            print(f"  - ... {len(errors) - 50} additional issue(s)", file=sys.stderr)
        return 2

    output_root.mkdir(parents=True)
    manifest_rows = []
    for index, command, source in validated:
        destination_relative = Path(
            command["case"],
            f"k{int(command['K'])}",
            rate_token(command["total_arrival_rate"]),
            f"s{int(command['seed'])}",
            RESULT_NAME,
        )
        destination = output_root / destination_relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        manifest_rows.append(
            {
                "command_index": index,
                "case": command["case"],
                "K": int(command["K"]),
                "total_arrival_rate": command["total_arrival_rate"],
                "seed": int(command["seed"]),
                "source_relative_path": f"{command['output_dir']}/{RESULT_NAME}",
                "artifact_relative_path": destination_relative.as_posix(),
                "bytes": destination.stat().st_size,
                "sha256": sha256(destination),
            }
        )

    manifest_path = output_root / "source_manifest.csv"
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(manifest_rows[0]))
        writer.writeheader()
        writer.writerows(manifest_rows)

    report = {
        "schema_version": 1,
        "imported_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "input_root_name": input_root.name,
        "commands_sha256": sha256(args.commands_csv),
        "expected_jobs": len(commands),
        "imported_jobs": len(validated),
        "result_filename": RESULT_NAME,
    }
    (output_root / "import_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"validated and imported {len(validated)} Table 6 result file(s)")
    print(f"output root: {output_root}")
    print("next: review the import, generate summaries, then refresh artifact hashes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
