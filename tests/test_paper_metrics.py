"""Regression tests for complete-request metrics and both aggregation callers."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
for folder in ("src", "scripts", "tools"):
    sys.path.insert(0, str(ROOT / folder))

from dcnc_sim.paper_metrics import normalize_record, request_metrics_from_stats
from paper_aggregation import summarize_rows
from reproduce_paper_results import aggregate
from run_campaign import consolidate


def stats(total=2, completed=1, delay=10):
    return dict(total_service_units=total, completed_service_units=completed,
                pending_service_units=total-completed, avg_service_delay_completed=delay,
                avg_service_delay_with_penalty=20, total_packets=4,
                delivered_packets=3, pending_packets=1, avg_delay_completed=6,
                avg_delay_with_penalty=15)


class RequestMetricTests(unittest.TestCase):
    def test_partially_delivered_multisink_request_is_not_complete(self):
        # Request A delivered both outputs; B delivered only one of its two.
        row = request_metrics_from_stats(stats())
        self.assertEqual(row["completed_requests"], 1)
        self.assertEqual(row["completion_ratio"], .5)
        self.assertEqual(row["avg_delay_completed"], 10)
        self.assertEqual(row["sink_output_completion_ratio"], .75)
        self.assertEqual(row["sink_output_avg_delay_completed"], 6)

    def test_archived_example(self):
        record = json.loads((ROOT / "data/runs/31e777cc6306a8ebe03e/result.json").read_text())
        original = copy.deepcopy(record)
        row = normalize_record("frames", record)
        self.assertEqual(row["avg_delay_completed"], 12163.47467881505)
        self.assertEqual(row["completion_ratio"], 41487/111014)
        self.assertEqual(row["sink_output_avg_delay_completed"], 10923.254938639242)
        self.assertEqual(row["sink_output_completion_ratio"], 119213/222028)
        self.assertEqual(record, original)

    def test_legacy_results_without_request_stats_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Missing request-level"):
            normalize_record("main", {"result": {"avg_delay_completed": 1, "completion_ratio": 1}})
        with self.assertRaisesRegex(ValueError, "Missing request-level"):
            request_metrics_from_stats({"total_packets": 2, "delivered_packets": 1})

    def test_native_versioned_result_needs_no_observer(self):
        row = request_metrics_from_stats(stats())
        self.assertEqual(normalize_record("main", {"result": row}), row)
        # Normalization must correct conflicting legacy aliases.
        row["completion_ratio"] = .75
        self.assertEqual(normalize_record("main", {"result": row})["completion_ratio"], .5)

    def test_zero_arrivals_and_no_completions_are_undefined(self):
        empty = request_metrics_from_stats(stats(total=0, completed=0, delay=0))
        self.assertIsNone(empty["completion_ratio"])
        self.assertIsNone(empty["avg_delay_completed"])
        pending = request_metrics_from_stats(stats(total=2, completed=0, delay=0))
        self.assertEqual(pending["completion_ratio"], 0)
        self.assertIsNone(pending["avg_delay_completed"])

    def test_invalid_counts_and_delay_fail(self):
        for key, value in (("pending_service_units", 0), ("completed_service_units", -1),
                           ("total_service_units", 2.5), ("avg_service_delay_completed", float("nan"))):
            with self.subTest(key=key), self.assertRaises(ValueError):
                request_metrics_from_stats(dict(stats(), **{key: value}))

    def test_workflow_jobs_and_throughput_use_requests(self):
        row = normalize_record("workflow", {"result": {"total_jobs": 4, "completed_jobs": 3},
                                            "stats": stats()}, slots=100)
        self.assertEqual(row["total_jobs"], 2)
        self.assertEqual(row["completed_jobs"], 1)
        self.assertEqual(row["job_completion_ratio"], .5)
        self.assertEqual(row["job_throughput"], .01)

    def test_seed_means_are_not_pooled(self):
        base = dict(case="test", policy="DCNC-DAG", solver="exact_dp", fixed_k=1, rate=1)
        rows = [dict(base, seed=i, **request_metrics_from_stats(s)) for i, s in
                enumerate((stats(100, 90, 10), stats(10, 5, 30)))]
        row = summarize_rows("main", rows).iloc[0]
        self.assertAlmostEqual(row.completion_ratio, .7)
        self.assertEqual(row.avg_delay_completed, 20)
        self.assertEqual(row.delay_se, 10)
        self.assertNotEqual(row.completion_ratio, 95/110)

    def test_missing_seed_delay_does_not_silently_drop_seed(self):
        import math
        base = dict(case="test", policy="DCNC-DAG", solver="exact_dp", fixed_k=1, rate=1)
        rows = [dict(base, seed=i, **request_metrics_from_stats(s)) for i, s in
                enumerate((stats(2, 1, 10), stats(2, 0, 0)))]
        row = summarize_rows("main", rows).iloc[0]
        self.assertTrue(math.isnan(row.avg_delay_completed))
        self.assertEqual(row.completion_ratio, .25)

    def test_campaign_and_archive_exports_are_byte_identical(self):
        jobs = json.loads((ROOT / "inputs/experiments.json").read_text())
        jobs = [job for job in jobs if job["id"] == "31e777cc6306a8ebe03e"]
        # Keep temporary files inside the checkout.
        with tempfile.TemporaryDirectory(prefix=".test-metrics-", dir=ROOT) as tmp:
            base = Path(tmp)
            manifest = base / "jobs.json"
            manifest.write_text(json.dumps(jobs))
            for job in jobs:
                record = json.loads((ROOT / "data/runs" / job["id"] / "result.json").read_text())
                record.update(protocol_id="test", job=job)
                dest = base / "campaign/runs" / job["id"] / "result.json"
                dest.parent.mkdir(parents=True)
                dest.write_text(json.dumps(record))
            consolidate(jobs, {"protocol_id": "test"}, results=base / "campaign")
            aggregate(base / "archive", base / "campaign/runs", manifest)
            for name in ("runs.csv", "summary.csv", "runs.jsonl"):
                self.assertEqual((base / "campaign/exports/frames" / name).read_bytes(),
                                 (base / "archive/exports/frames" / name).read_bytes())
            with self.assertRaisesRegex(ValueError, "protocol/job mismatch"):
                consolidate(jobs, {"protocol_id": "wrong"}, results=base / "campaign")


if __name__ == "__main__":
    unittest.main()
