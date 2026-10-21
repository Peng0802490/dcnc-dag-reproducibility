#!/usr/bin/env python3
"""Second-pass deterministic audit with explicit physical backlog metrics.

Run this script in the real ``dcnc_sim`` environment. It leaves the simulator
control path unchanged and passively records several backlog definitions so
that object counts are not mislabeled as workload units.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Sequence, Tuple, Union

import numpy as np
import pandas as pd

import dcnc_sim.capacity
import dcnc_sim.capacity_gurobi
import dcnc_sim.interference
import dcnc_sim.mapping
import dcnc_sim.physical
import dcnc_sim.simulator
import dcnc_sim.virtual
import dcnc_sim.wireless
from dcnc_sim.interference import build_activation_policy
from dcnc_sim.simulator import CommodityConfig
from dcnc_sim.wireless import IIDOnOffProcess

from run_new_7_2_wireless_mixed_mapping import (
    ArrivalAuditSimulator,
    CountingExactSolver,
    MAIN_RATES,
    make_case,
    tail_slope,
    weighted_mapping_counts,
)


SLOPE_CUTOFF = 5e-2
DYNAMIC_EDGES = (
    ("uA", "uC1"),
    ("uC1", "uD"),
    ("uA", "uC2"),
    ("uC2", "uD"),
)


class AuditedIIDOnOffProcess(IIDOnOffProcess):
    """Record actual dynamic-edge states without changing RNG consumption."""

    def __init__(self, *args, **kwargs):
        self.state_bytes = bytearray()
        self.on_counts = [0] * len(DYNAMIC_EDGES)
        self.sample_calls = 0
        super().__init__(*args, **kwargs)

    def sample_capacities(self, slot: int):
        capacities = super().sample_capacities(slot)
        bits = []
        for index, edge in enumerate(DYNAMIC_EDGES):
            on = int(float(capacities[edge]) > 0.0)
            bits.append(on)
            if self.sample_calls > 0:
                self.on_counts[index] += on
        self.state_bytes.extend(bits)
        self.sample_calls += 1
        return capacities

    def run_path_sha256(self) -> str:
        # PhysicalNetwork samples once during construction, before slot 0. The
        # formal run then samples once per slot; exclude the construction draw.
        width = len(DYNAMIC_EDGES)
        return hashlib.sha256(bytes(self.state_bytes[width:])).hexdigest()


def waiting_payload_size(physical_network) -> float:
    total = 0.0
    for (_node, func), table in physical_network.wait_pools.items():
        for job_id, record in table.items():
            dag = physical_network.job_ctx[job_id]["dag"]
            for predecessor in record["arrived"]:
                if isinstance(predecessor, tuple) and predecessor[0] == "S":
                    total += float(dag.xi_source()[func])
                else:
                    total += float(dag.xi(predecessor, func))
    return total


def physical_metric_snapshot(physical_network) -> Dict[str, float]:
    waiting_components = float(
        sum(len(table) for table in physical_network.wait_pools.values())
    )
    waiting_packets = float(
        sum(
            len(record["arrived"])
            for table in physical_network.wait_pools.values()
            for record in table.values()
        )
    )
    link_objects = float(sum(len(queue) for queue in physical_network.link_queues.values()))
    node_objects = float(sum(len(queue) for queue in physical_network.node_queues.values()))
    link_workload = float(
        sum(
            max(0.0, float(item.size_remaining))
            for queue in physical_network.link_queues.values()
            for item in queue
        )
    )
    node_workload = float(
        sum(
            max(0.0, float(task.size_remaining))
            for queue in physical_network.node_queues.values()
            for task in queue
        )
    )
    queue_workload = link_workload + node_workload
    payload = waiting_payload_size(physical_network)
    return {
        "object_count": waiting_components + link_objects + node_objects,
        "queue_workload": queue_workload,
        "queue_workload_plus_waiting_components": queue_workload + waiting_components,
        "queue_workload_plus_waiting_packets": queue_workload + waiting_packets,
        "queue_workload_plus_waiting_payload": queue_workload + payload,
        "waiting_components": waiting_components,
        "waiting_packets": waiting_packets,
        "waiting_payload": payload,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_one(task: Tuple[int, float, int]) -> Dict[str, Union[int, float, str, bool]]:
    slots, arrival_rate, seed = task
    case = make_case("mixed")
    activation = build_activation_policy("primary")
    solver = CountingExactSolver(case.network, seed=20_000 + seed)
    wireless = AuditedIIDOnOffProcess(
        case.network, case.dynamic_edge_p_on, seed=10_000 + 101 * seed
    )
    sim = ArrivalAuditSimulator(
        network=case.network,
        commodity_cfgs=[CommodityConfig(case.commodity, arrival_rate, solver)],
        wireless_process=wireless,
        total_slots=slots,
        seed=30_000 + seed,
        scheduler="nto",
        activation_policy=activation,
        fixed_k=1,
        arrival_mode="bounded",
        run_label="new_7_2_second_pass_r{:.4f}_s{}".format(arrival_rate, seed),
        progress_every=max(slots // 5, 1),
    )

    metric_series: Dict[str, List[float]] = {}
    original_total_backlog = sim.physical_network.total_backlog

    def audited_total_backlog() -> int:
        metrics = physical_metric_snapshot(sim.physical_network)
        original = int(original_total_backlog())
        if not math.isclose(metrics["object_count"], float(original), abs_tol=1e-12):
            raise AssertionError("passive object count differs from simulator total_backlog")
        for name, value in metrics.items():
            metric_series.setdefault(name, []).append(float(value))
        return original

    sim.physical_network.total_backlog = audited_total_backlog
    stats = sim.run()
    if any(len(values) != slots for values in metric_series.values()):
        raise AssertionError("a passive physical metric does not contain one sample per slot")
    if wireless.sample_calls != slots + 1:
        raise AssertionError(
            "expected {} wireless samples including construction, got {}".format(
                slots + 1, wireless.sample_calls
            )
        )

    request_counts = weighted_mapping_counts(sim.arrival_draws, solver.choice_sequence)
    total_arrivals = int(sum(sim.arrival_draws))
    decisions = len(solver.choice_sequence)
    virtual_total = [
        link + node
        for link, node in zip(stats.vq_link_sum_series, stats.vq_node_sum_series)
    ]
    result: Dict[str, Union[int, float, str, bool]] = {
        "policy": "mixed",
        "arrival_rate": arrival_rate,
        "seed": seed,
        "slots": slots,
        "total_arrivals": total_arrivals,
        "completed_requests": int(stats.completed_service_units),
        "completed_throughput": int(stats.completed_service_units) / slots,
        "completion_ratio": int(stats.completed_service_units) / total_arrivals,
        "mapping_calls": decisions,
        "share_m1_requests": request_counts["uC1"] / total_arrivals,
        "share_m1_calls": solver.choice_sequence.count("uC1") / decisions,
        "arrival_path_sha256": hashlib.sha256(bytes(sim.arrival_draws)).hexdigest(),
        "wireless_path_sha256": wireless.run_path_sha256(),
        "virtual_workload_tail_slope": tail_slope(virtual_total),
    }
    for index, edge in enumerate(DYNAMIC_EDGES):
        result["on_fraction_{}->{}".format(edge[0], edge[1])] = wireless.on_counts[index] / slots
    for name, values in metric_series.items():
        result["{}_tail_slope".format(name)] = tail_slope(values)
    return result


def compare_to_formal(second_pass: pd.DataFrame, formal: pd.DataFrame) -> None:
    comparable = [
        "total_arrivals",
        "completed_requests",
        "completed_throughput",
        "completion_ratio",
        "mapping_calls",
        "share_m1_requests",
        "share_m1_calls",
        "arrival_path_sha256",
        "wireless_path_sha256",
    ]
    formal_main = formal[formal["policy"] == "mixed"]
    merged = second_pass.merge(
        formal_main,
        on=["policy", "arrival_rate", "seed"],
        suffixes=("_second", "_formal"),
        validate="one_to_one",
    )
    if len(merged) != len(second_pass):
        raise AssertionError("second-pass runs do not all match a formal run")
    for column in comparable:
        left = merged["{}_second".format(column)]
        right = merged["{}_formal".format(column)]
        if column.endswith("sha256"):
            if not left.equals(right):
                raise AssertionError("{} differs from the formal run".format(column))
        elif not np.allclose(left.astype(float), right.astype(float), rtol=0.0, atol=1e-12):
            raise AssertionError("{} differs from the formal run".format(column))

    if not np.allclose(
        merged["object_count_tail_slope"],
        merged["physical_object_backlog_tail_slope"],
        rtol=0.0,
        atol=1e-12,
    ):
        raise AssertionError("reproduced object-count slopes differ from formal physical slopes")
    if not np.allclose(
        merged["virtual_workload_tail_slope_second"],
        merged["virtual_workload_tail_slope_formal"],
        rtol=0.0,
        atol=1e-12,
    ):
        raise AssertionError("reproduced virtual slopes differ from formal virtual slopes")
    if not np.allclose(
        merged["queue_workload_plus_waiting_payload_tail_slope"],
        merged["physical_workload_tail_slope"],
        rtol=0.0,
        atol=1e-12,
    ):
        raise AssertionError("reproduced physical workload slopes differ from formal slopes")


def summarize(runs: pd.DataFrame) -> pd.DataFrame:
    slope_columns = [column for column in runs.columns if column.endswith("tail_slope")]
    rows = []
    for arrival_rate, group in runs.groupby("arrival_rate"):
        row: Dict[str, Union[float, int]] = {"arrival_rate": float(arrival_rate)}
        for column in slope_columns:
            row["{}_mean".format(column)] = float(group[column].mean())
            row["{}_se".format(column)] = float(
                group[column].std(ddof=1) / math.sqrt(len(group))
            )
            row["{}_flags".format(column)] = int((group[column] > SLOPE_CUTOFF).sum())
        rows.append(row)
    return pd.DataFrame(rows).sort_values("arrival_rate")


def module_hashes() -> Dict[str, str]:
    modules = [
        dcnc_sim.capacity,
        dcnc_sim.capacity_gurobi,
        dcnc_sim.interference,
        dcnc_sim.mapping,
        dcnc_sim.physical,
        dcnc_sim.simulator,
        dcnc_sim.virtual,
        dcnc_sim.wireless,
    ]
    result = {}
    for module in modules:
        source = Path(inspect.getsourcefile(module) or "")
        result[source.name] = sha256_file(source)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--formal-runs", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--slots", type=int, default=100_000)
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--workers", type=int, default=25)
    parser.add_argument("--rates", nargs="*", type=float, default=MAIN_RATES)
    parser.add_argument(
        "--reuse-existing",
        action="store_true",
        help="re-audit output-dir/second_pass_runs.csv without rerunning simulation",
    )
    args = parser.parse_args()
    if os.environ.get("PYTHONHASHSEED") != "0":
        parser.error("launch with PYTHONHASHSEED=0 for deterministic matching ties")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.reuse_existing:
        runs = pd.read_csv(args.output_dir / "second_pass_runs.csv").sort_values(
            ["arrival_rate", "seed"]
        )
    else:
        tasks = [
            (args.slots, float(rate), seed)
            for rate in args.rates
            for seed in range(args.seeds)
        ]
        rows = []
        with ProcessPoolExecutor(max_workers=min(args.workers, len(tasks))) as executor:
            futures = [executor.submit(run_one, task) for task in tasks]
            for count, future in enumerate(as_completed(futures), start=1):
                rows.append(future.result())
                pd.DataFrame(rows).sort_values(["arrival_rate", "seed"]).to_csv(
                    args.output_dir / "second_pass_runs_partial.csv", index=False
                )
                print("completed {}/{}".format(count, len(tasks)), flush=True)
        runs = pd.DataFrame(rows).sort_values(["arrival_rate", "seed"])

    expected_rows = args.seeds * len(args.rates)
    if len(runs) != expected_rows:
        raise AssertionError(
            "expected {} second-pass rows, found {}".format(expected_rows, len(runs))
        )
    formal = pd.read_csv(args.formal_runs)
    compare_to_formal(runs, formal)
    summary = summarize(runs)
    runs.to_csv(args.output_dir / "second_pass_runs.csv", index=False)
    summary.to_csv(args.output_dir / "physical_metric_summary.csv", index=False)

    wireless_hash_counts = runs.groupby("seed")["wireless_path_sha256"].nunique()
    if not (wireless_hash_counts == 1).all():
        raise AssertionError("wireless path hash changes across rates for a fixed seed")
    if runs.groupby("seed")["wireless_path_sha256"].first().nunique() != args.seeds:
        raise AssertionError("different logical seeds do not have distinct wireless paths")

    report = {
        "checks_passed": True,
        "formal_main_runs_reproduced_exactly": len(runs),
        "slots": args.slots,
        "seeds": args.seeds,
        "rates": sorted(float(value) for value in args.rates),
        "slope_cutoff": SLOPE_CUTOFF,
        "simulator_module_sha256": module_hashes(),
        "formal_runs_sha256": sha256_file(args.formal_runs),
        "second_pass_runs_sha256": sha256_file(args.output_dir / "second_pass_runs.csv"),
        "physical_metric_summary_sha256": sha256_file(
            args.output_dir / "physical_metric_summary.csv"
        ),
    }
    (args.output_dir / "second_pass_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
