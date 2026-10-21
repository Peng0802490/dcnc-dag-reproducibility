#!/usr/bin/env python3
"""Produce a fail-closed Table 6 scheduler progress snapshot.

Run this script on the machine that owns the campaign result directory.  It
only reads the scheduler workspace and writes one JSON document to stdout; it
does not modify jobs or results.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import time


TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
JOB_NAME = re.compile(r"^job_(\d{5})_.+")
ERROR_PATTERNS = (
    re.compile(r"Traceback \(most recent call last\):", re.IGNORECASE),
    re.compile(r"Fatal Python error", re.IGNORECASE),
    re.compile(r"Segmentation fault", re.IGNORECASE),
    re.compile(r"^.*\|\s*ERROR\s*\|", re.IGNORECASE | re.MULTILINE),
)


class ProbeError(RuntimeError):
    """Raised when scheduler evidence is missing or internally inconsistent."""


def timestamp(epoch: float) -> str:
    return datetime.fromtimestamp(epoch).strftime(TIMESTAMP_FORMAT)


def keyed_files(directory: Path, suffix: str) -> dict[int, Path]:
    """Return scheduler files keyed by job id, rejecting ambiguous names."""
    if not directory.is_dir():
        raise ProbeError(f"missing scheduler directory: {directory}")
    keyed: dict[int, Path] = {}
    for path in sorted(directory.glob(f"*{suffix}")):
        match = JOB_NAME.match(path.name)
        if match is None:
            raise ProbeError(f"unrecognized scheduler filename: {path.name}")
        job_id = int(match.group(1))
        if job_id in keyed:
            raise ProbeError(
                f"duplicate scheduler files for job {job_id}: "
                f"{keyed[job_id].name}, {path.name}"
            )
        keyed[job_id] = path
    return keyed


def exit_code(path: Path) -> int:
    raw = path.read_text(encoding="utf-8", errors="strict").strip()
    if not re.fullmatch(r"-?\d+", raw):
        raise ProbeError(f"invalid exit status in {path}: {raw!r}")
    return int(raw)


def pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        raise ProbeError("scheduler PID must be positive")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def log_state(paths: list[Path]) -> dict[Path, tuple[int, int]]:
    return {
        path: (stat.st_size, stat.st_mtime_ns)
        for path in paths
        if (stat := path.stat()).st_size >= 0
    }


def error_pattern_file_count(paths: list[Path]) -> int:
    matches = 0
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(pattern.search(text) for pattern in ERROR_PATTERNS):
            matches += 1
    return matches


def latest_event_epoch(
    scripts: dict[int, Path], done: dict[int, Path], state_dir: Path
) -> float:
    candidates = [
        path.stat().st_mtime for path in (*scripts.values(), *done.values())
    ]
    running_state = state_dir / "running_jobs.json"
    if running_state.is_file():
        candidates.append(running_state.stat().st_mtime)
    if not candidates:
        raise ProbeError("scheduler contains no dispatch or completion evidence")
    return max(candidates)


def collect_progress(
    result_root: Path,
    expected_jobs: int,
    scheduler_active: bool,
    sample_seconds: float,
) -> dict:
    """Collect one validated snapshot from a scheduler result root."""
    result_root = result_root.resolve()
    if expected_jobs <= 0:
        raise ProbeError("expected job count must be positive")
    if sample_seconds < 0:
        raise ProbeError("sample interval cannot be negative")
    scheduler = result_root / "scheduler_main"
    scripts = keyed_files(scheduler / "scripts", ".sh")
    done = keyed_files(scheduler / "done", ".exit")
    logs = keyed_files(scheduler / "job_logs", ".log")

    dispatched_ids = set(scripts)
    done_ids = set(done)
    if not done_ids <= dispatched_ids:
        extras = ", ".join(map(str, sorted(done_ids - dispatched_ids)))
        raise ProbeError(f"completed jobs were never dispatched: {extras}")
    if len(dispatched_ids) > expected_jobs:
        raise ProbeError(
            f"dispatched jobs exceed expected total: {len(dispatched_ids)} > {expected_jobs}"
        )
    if set(logs) != dispatched_ids:
        missing = sorted(dispatched_ids - set(logs))
        extra = sorted(set(logs) - dispatched_ids)
        raise ProbeError(
            "job-log set disagrees with dispatched jobs: "
            f"missing={missing} extra={extra}"
        )

    codes = {job_id: exit_code(path) for job_id, path in done.items()}
    completed = sum(code == 0 for code in codes.values())
    failed = sum(code != 0 for code in codes.values())
    running = len(dispatched_ids - done_ids)
    queued = expected_jobs - len(dispatched_ids)

    log_paths = list(logs.values())
    before = log_state(log_paths)
    if sample_seconds:
        time.sleep(sample_seconds)
    after = log_state(log_paths)
    sampled_logs_advancing = any(
        after.get(path) != value for path, value in before.items()
    )
    latest_log_epoch = max(
        (path.stat().st_mtime for path in log_paths),
        default=latest_event_epoch(scripts, done, scheduler / "state"),
    )
    checked_epoch = time.time()
    event_epoch = latest_event_epoch(scripts, done, scheduler / "state")
    # Filesystem timestamps can be fractionally newer than the wall-clock read
    # on skewed/network filesystems.  Clamp them to preserve the update
    # contract while still exposing the latest observable second.
    event_epoch = min(event_epoch, checked_epoch)
    latest_log_epoch = min(latest_log_epoch, checked_epoch)

    return {
        "schema_version": 1,
        "probe": "table6_progress_probe",
        "checked_server_local": timestamp(checked_epoch),
        "last_event_server_local": timestamp(event_epoch),
        "latest_sampled_log_server_local": timestamp(latest_log_epoch),
        "completed": completed,
        "running": running,
        "queued": queued,
        "failed": failed,
        "all_csv_files": sum(1 for path in result_root.rglob("*.csv") if path.is_file()),
        "scheduler_active": scheduler_active,
        "sampled_logs_advancing": sampled_logs_advancing,
        "error_pattern_files": error_pattern_file_count(log_paths),
        "remote_result_root": result_root.name,
        "final": completed == expected_jobs and failed == running == queued == 0,
        "dispatched": len(dispatched_ids),
        "exit_files": len(done_ids),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-root", type=Path, required=True)
    parser.add_argument("--expected-jobs", type=int, required=True)
    activity = parser.add_mutually_exclusive_group(required=True)
    activity.add_argument("--scheduler-pid", type=int)
    activity.add_argument(
        "--scheduler-active", action=argparse.BooleanOptionalAction
    )
    parser.add_argument(
        "--sample-seconds",
        type=float,
        default=5.0,
        help="Seconds used to verify that at least one job log advances.",
    )
    args = parser.parse_args()
    try:
        scheduler_active = (
            pid_is_alive(args.scheduler_pid)
            if args.scheduler_pid is not None
            else args.scheduler_active
        )
        snapshot = collect_progress(
            args.result_root,
            args.expected_jobs,
            bool(scheduler_active),
            args.sample_seconds,
        )
    except (OSError, ProbeError) as exc:
        parser.error(str(exc))
    print(json.dumps(snapshot, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
