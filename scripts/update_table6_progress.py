#!/usr/bin/env python3
"""Update the machine-readable and human-readable Table 6 progress records."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
CLAIMS_PATH = ROOT / "manifests" / "claims.json"
PROGRESS_PATH = ROOT / "evidence" / "table6" / "progress.json"
STATUS_PATH = ROOT / "evidence" / "table6" / "STATUS.md"
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
SNAPSHOT_FIELDS = (
    "checked_server_local",
    "last_event_server_local",
    "latest_sampled_log_server_local",
    "completed",
    "running",
    "queued",
    "failed",
    "all_csv_files",
    "scheduler_active",
    "sampled_logs_advancing",
    "error_pattern_files",
    "remote_result_root",
)


def progress_record_issues(progress: dict, expected_jobs: int) -> list[str]:
    """Return fail-closed consistency issues for one progress snapshot."""
    issues: list[str] = []
    if progress.get("schema_version") != 1:
        issues.append("schema_version must equal 1")
    timestamps: dict[str, datetime] = {}
    for field in (
        "checked_server_local",
        "last_event_server_local",
        "latest_sampled_log_server_local",
    ):
        try:
            timestamps[field] = datetime.strptime(progress[field], TIMESTAMP_FORMAT)
        except (KeyError, TypeError, ValueError):
            issues.append(
                f"{field} must use server-local format YYYY-MM-DD HH:MM:SS"
            )

    checked = timestamps.get("checked_server_local")
    if checked is not None:
        for field in ("last_event_server_local", "latest_sampled_log_server_local"):
            observed = timestamps.get(field)
            if observed is not None and observed > checked:
                issues.append(f"{field} cannot be later than checked_server_local")

    count_fields = ("completed", "running", "queued", "failed")
    counts: list[int] = []
    for field in count_fields:
        value = progress.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            issues.append(f"{field} must be a non-negative integer")
        else:
            counts.append(value)
    if len(counts) == len(count_fields) and sum(counts) != expected_jobs:
        issues.append(
            "completed + running + queued + failed must equal "
            f"{expected_jobs}"
        )

    for field in ("all_csv_files", "error_pattern_files"):
        value = progress.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            issues.append(f"{field} must be a non-negative integer")

    for field in ("scheduler_active", "sampled_logs_advancing", "final"):
        if not isinstance(progress.get(field), bool):
            issues.append(f"{field} must be a boolean")

    remote_root = progress.get("remote_result_root")
    if (
        not isinstance(remote_root, str)
        or not remote_root
        or "/" in remote_root
        or "\\" in remote_root
        or Path(remote_root).name != remote_root
        or remote_root in (".", "..")
    ):
        issues.append("remote_result_root must be one non-empty basename")

    expected_final = (
        progress.get("completed") == expected_jobs
        and progress.get("running") == 0
        and progress.get("queued") == 0
        and progress.get("failed") == 0
    )
    if progress.get("final") is not expected_final:
        issues.append("final flag disagrees with the job counts")
    return issues


def progress_from_snapshot(snapshot: dict, expected_jobs: int) -> dict:
    """Select updater fields from a probe snapshot and recompute finality."""
    if snapshot.get("schema_version") != 1:
        raise ValueError("snapshot schema_version must equal 1")
    missing = [field for field in SNAPSHOT_FIELDS if field not in snapshot]
    if missing:
        raise ValueError("snapshot is missing fields: " + ", ".join(missing))
    progress = {
        "schema_version": 1,
        **{field: snapshot[field] for field in SNAPSHOT_FIELDS},
    }
    progress["final"] = (
        progress["completed"] == expected_jobs
        and progress["running"] == 0
        and progress["queued"] == 0
        and progress["failed"] == 0
    )
    return progress


def load_snapshot(source: str) -> dict:
    raw = (
        sys.stdin.read()
        if source == "-"
        else Path(source).read_text(encoding="utf-8")
    )
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("snapshot JSON must contain one object")
    return parsed


def progress_transition_issues(previous: dict, current: dict) -> list[str]:
    """Reject stale or regressing observations of the same campaign."""
    issues: list[str] = []
    if current.get("remote_result_root") != previous.get("remote_result_root"):
        issues.append("remote_result_root cannot change in an in-place progress update")

    for field in (
        "checked_server_local",
        "last_event_server_local",
        "latest_sampled_log_server_local",
    ):
        try:
            old = datetime.strptime(previous[field], TIMESTAMP_FORMAT)
            new = datetime.strptime(current[field], TIMESTAMP_FORMAT)
        except (KeyError, TypeError, ValueError):
            continue
        if field == "checked_server_local" and new <= old:
            issues.append(f"{field} must advance beyond the recorded snapshot")
        elif field != "checked_server_local" and new < old:
            issues.append(f"{field} cannot move backward")

    for field in ("completed", "failed", "all_csv_files"):
        old = previous.get(field)
        new = current.get(field)
        if isinstance(old, int) and isinstance(new, int) and new < old:
            issues.append(f"{field} cannot decrease")
    if previous.get("final") is True and current.get("final") is not True:
        issues.append("a final campaign snapshot cannot become non-final")
    return issues


def render_status(progress: dict, table6: dict) -> str:
    alignment_note = (
        "Invocation counts and times match the corrected LaTeX source at its "
        "printed precision. See `evidence/table6/paper_update/`; the older PDF "
        "timing mismatch is historical. No updated compiled PDF was verified."
        if table6.get("timing_status") == "exact-source-provenance"
        else "Invocation counts match the paper at its printed precision; "
        "measured times differ. The timing reconciliation gate remains open."
    )
    evidence_note = (
        f"All {table6['expected_jobs']} per-run CSVs are archived under "
        f"`{table6['raw_evidence']}`. The generated summary is "
        f"`{table6['summary_evidence']}`. {alignment_note}"
        if table6.get("raw_evidence") and progress["final"]
        else "This status is informational. Import the compact per-run CSVs "
        "and generated summaries after completion, then reconcile the paper "
        "with the evidence before closing its release gate."
    )
    activity = "active" if progress["scheduler_active"] else "not observed"
    log_activity = (
        "sampled job logs were still advancing through bridge calls"
        if progress["sampled_logs_advancing"]
        else "sampled job logs did not advance during this check"
    )
    error_scan = (
        "no matching log files"
        if progress["error_pattern_files"] == 0
        else f"{progress['error_pattern_files']} matching log file(s); inspect before release"
    )
    return f"""# Table 6 DynVMP campaign status

Last checked against the remote scheduler: server-local {progress['checked_server_local']}.

- Protocol: {table6['expected_jobs']} jobs, {table6['slots']:,} slots, seeds {'/'.join(map(str, table6['seeds']))}, real `{table6['solver']}`.
- Completed successfully: {progress['completed']}.
- Running: {progress['running']}.
- Queued: {progress['queued']}.
- Failed: {progress['failed']}.
- Scheduler, simulation workers, and DynVMP bridge subprocesses: {activity};
  {log_activity}.
- Latest scheduler event: server-local {progress['last_event_server_local']}.
- Latest sampled job-log activity: server-local {progress['latest_sampled_log_server_local']}.
- CSV files currently present in the remote result root: {progress['all_csv_files']}.
- Error-pattern scan: {error_scan}.
- Remote result root: `{progress['remote_result_root']}`.

{evidence_note}
"""


def progress_summary(progress: dict) -> str:
    return (
        "updated Table 6 progress: "
        f"completed={progress['completed']} running={progress['running']} "
        f"queued={progress['queued']} failed={progress['failed']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--snapshot-json",
        help="Probe JSON path, or '-' to read one JSON object from stdin.",
    )
    parser.add_argument("--checked-server-local")
    parser.add_argument("--last-event-server-local")
    parser.add_argument("--latest-sampled-log-server-local")
    parser.add_argument("--completed", type=int)
    parser.add_argument("--running", type=int)
    parser.add_argument("--queued", type=int)
    parser.add_argument("--failed", type=int)
    parser.add_argument("--all-csv-files", type=int)
    parser.add_argument("--error-pattern-files", type=int)
    parser.add_argument("--remote-result-root")
    parser.add_argument(
        "--scheduler-active", action=argparse.BooleanOptionalAction
    )
    parser.add_argument(
        "--sampled-logs-advancing", action=argparse.BooleanOptionalAction
    )
    args = parser.parse_args()

    manifest = json.loads(CLAIMS_PATH.read_text(encoding="utf-8"))
    table6 = manifest["claims"]["table6"]
    manual_values = {field: getattr(args, field) for field in SNAPSHOT_FIELDS}
    if args.snapshot_json is not None:
        supplied = [field for field, value in manual_values.items() if value is not None]
        if supplied:
            parser.error(
                "--snapshot-json cannot be combined with manual progress fields: "
                + ", ".join(supplied)
            )
        try:
            progress = progress_from_snapshot(
                load_snapshot(args.snapshot_json), table6["expected_jobs"]
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            parser.error(f"invalid progress snapshot: {exc}")
    else:
        missing = [field for field, value in manual_values.items() if value is None]
        if missing:
            parser.error(
                "manual progress update is missing fields: " + ", ".join(missing)
            )
        progress = {"schema_version": 1, **manual_values}
        progress["final"] = (
            progress["completed"] == table6["expected_jobs"]
            and progress["running"] == 0
            and progress["queued"] == 0
            and progress["failed"] == 0
        )
    issues = progress_record_issues(progress, table6["expected_jobs"])
    if PROGRESS_PATH.exists():
        previous = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
        issues.extend(progress_transition_issues(previous, progress))
    if issues:
        parser.error("refusing unsafe progress update:\n- " + "\n- ".join(issues))

    PROGRESS_PATH.write_text(
        json.dumps(progress, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    STATUS_PATH.write_text(
        render_status(progress, table6), encoding="utf-8", newline="\n"
    )
    print(progress_summary(progress))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
