"""Request-level paper metrics, independent of simulation execution.

One request completes only after all its sink outputs have been delivered.
The simulator's historical ``*_packets`` and ``avg_delay_completed`` stats
describe sink outputs; never use them as a fallback for request statistics.
"""
from __future__ import annotations

import math

REQUEST_METRICS_SCHEMA = "complete-request-v1"
REQUEST_KINDS = frozenset(("main", "frames", "workflow"))


def _count(value, name):
    number = float(value)
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        raise ValueError(f"{name} must be a nonnegative integer: {value!r}")
    return int(number)


def _delay(value, count, name):
    if count == 0:
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be finite and nonnegative: {value!r}")
    return number


def request_metrics_from_stats(stats):
    """Extract canonical metrics from a stats mapping (or ``vars(SimStats)``).

    Zero arrivals give an undefined completion ratio; zero completions give
    an undefined completed delay. JSON uses null and CSV uses an empty cell.
    """
    required = ("total_service_units", "completed_service_units",
                "pending_service_units", "avg_service_delay_completed")
    missing = [key for key in required if key not in stats]
    if missing:
        raise ValueError(f"Missing request-level statistics: {missing}; sink-output fallback is forbidden")
    total, completed, pending = (_count(stats[key], key) for key in required[:3])
    if total != completed + pending:
        raise ValueError("Request conservation failed: total != completed + pending")
    delay = _delay(stats[required[3]], completed, required[3])
    ratio = completed / total if total else None
    result = dict(request_metrics_schema=REQUEST_METRICS_SCHEMA,
                  total_requests=total, completed_requests=completed,
                  pending_requests=pending, request_avg_delay_completed=delay,
                  request_completion_ratio=ratio,
                  avg_delay_completed=delay, completion_ratio=ratio)
    # These unqualified result fields are compatibility aliases for requests.
    if "avg_service_delay_with_penalty" in stats:
        penalty = _delay(stats["avg_service_delay_with_penalty"], total,
                         "avg_service_delay_with_penalty")
        result.update(request_avg_delay_with_penalty=penalty, avg_delay_with_penalty=penalty)
    if all(key in stats for key in ("delivered_packets", "pending_packets", "total_packets")):
        delivered, outstanding, outputs = (_count(stats[key], key) for key in
                                           ("delivered_packets", "pending_packets", "total_packets"))
        if outputs != delivered + outstanding:
            raise ValueError("Sink-output conservation failed")
        result.update(sink_output_delivered=delivered, sink_output_pending=outstanding,
                      sink_output_total=outputs,
                      sink_output_completion_ratio=delivered / outputs if outputs else None)
        for key, count in (("avg_delay_completed", delivered), ("avg_delay_with_penalty", outputs)):
            if key in stats:
                result["sink_output_" + key] = _delay(stats[key], count, key)
    return result


def normalize_record(kind, record, *, slots=None):
    """Normalize archived stats and new direct/native runner exports identically."""
    row = dict(record["result"])
    if row.get("status") == "error":
        raise ValueError(f"Cannot aggregate a failed run: {row.get('error')}")
    if kind not in REQUEST_KINDS:
        return row
    if "stats" in record:
        metrics = request_metrics_from_stats(record["stats"])
    elif row.get("request_metrics_schema") == REQUEST_METRICS_SCHEMA:
        # Native runs need no observer: direct runners export counts and delays.
        try:
            stats = dict(total_service_units=row["total_requests"],
                         completed_service_units=row["completed_requests"],
                         pending_service_units=row["pending_requests"],
                         avg_service_delay_completed=row["request_avg_delay_completed"])
        except KeyError as exc:
            raise ValueError(f"Incomplete canonical request metrics: {exc}") from exc
        if "request_avg_delay_with_penalty" in row:
            stats["avg_service_delay_with_penalty"] = row["request_avg_delay_with_penalty"]
        metrics = request_metrics_from_stats(stats)
    else:
        raise ValueError("Missing request-level stats or versioned request metrics; cannot use legacy result fields")
    row.update(metrics)
    # Never leave a historical output-level penalty under the request alias.
    if "request_avg_delay_with_penalty" not in metrics:
        row.pop("avg_delay_with_penalty", None)
    if kind == "workflow":
        row.update(total_jobs=row["total_requests"], completed_jobs=row["completed_requests"],
                   pending_jobs=row["pending_requests"], job_completion_ratio=row["completion_ratio"])
        slots = slots if slots is not None else row.get("slots")
        if slots is not None and float(slots) > 0:
            row["job_throughput"] = row["completed_requests"] / float(slots)
        else:
            row.pop("job_throughput", None)
    return row
