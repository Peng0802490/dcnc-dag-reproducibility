#!/usr/bin/env python3
"""Run the Section 7.2 wireless mixed-mapping validation campaign.

This driver must be run from the DCNC-DAG simulator environment, where the
``dcnc_sim`` package is importable. It writes per-seed raw records before any
paper-facing aggregation so that every reported mean and standard error can be
audited.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from dcnc_sim.capacity_gurobi import solve_single_commodity_capacity_gurobi
from dcnc_sim.interference import build_activation_policy
from dcnc_sim.mapping import ExactEnumerationSolver, enumerate_all_valid_mappings_small
from dcnc_sim.models import Commodity
from dcnc_sim.simulator import CommodityConfig, DCNCSimulator
from dcnc_sim.synthetic_instances import (
    SyntheticThroughputCase,
    _add_dag_edge,
    _add_dag_node,
    _add_edge,
    _add_node,
    _new_dag,
    _new_network,
)
from dcnc_sim.wireless import IIDOnOffProcess


MAIN_RATES = (0.95, 0.98, 0.99, 1.01, 1.03, 1.05, 1.10)
ABLATION_BOUNDARY_RATES = (0.45, 0.49, 0.50, 0.51, 0.55)
BACKLOG_SLOPE_CUTOFF = 5e-2
WORKLOAD_QUANTUM = 0.1
DYNAMIC_EDGES = (
    ("uA", "uC1"),
    ("uC1", "uD"),
    ("uA", "uC2"),
    ("uC2", "uD"),
)


def make_case(policy: str = "mixed") -> SyntheticThroughputCase:
    if policy not in {"mixed", "single_m1"}:
        raise ValueError("unknown policy: {}".format(policy))

    net = _new_network("wireless_mixed_mapping_fork_join")
    for node, role, capacity in [
        ("s", "FORWARD", 0.0),
        ("uA", "COMPUTE", 5.0),
        ("uB", "COMPUTE", 5.0),
        ("uC1", "COMPUTE", 0.5),
        ("uC2", "COMPUTE", 0.5),
        ("uD", "COMPUTE", 5.0),
        ("d", "FORWARD", 0.0),
    ]:
        _add_node(net, node, role, capacity)
    edges = [
        ("s", "uA"),
        ("uA", "uB"),
        ("uB", "uD"),
        ("uA", "uC1"),
        ("uC1", "uD"),
        ("uA", "uC2"),
        ("uC2", "uD"),
        ("uD", "d"),
    ]
    for src, dst in edges:
        _add_edge(net, src, dst, 2.0)
    net.validate()

    dag = _new_dag("wireless_mixed_mapping_fork_join_dag")
    _add_dag_node(dag, "A", "source", r=0.1, xin=0.2)
    _add_dag_node(dag, "B", "function", r=0.1)
    _add_dag_node(dag, "C", "function", r=1.0)
    _add_dag_node(dag, "D", "sink", r=0.1, xout=0.2)
    _add_dag_edge(dag, "A", "B", xi=0.2)
    _add_dag_edge(dag, "A", "C", xi=1.0)
    _add_dag_edge(dag, "B", "D", xi=0.2)
    _add_dag_edge(dag, "C", "D", xi=1.0)
    dag.validate()

    c_candidates = ["uC1", "uC2"] if policy == "mixed" else ["uC1"]
    commodity = Commodity(
        name="wireless_mixed_mapping_fork_join",
        service_dag=dag,
        src_nodes={"A": "s"},
        dst_nodes={"D": "d"},
        allowed={
            "A": ["uA"],
            "B": ["uB"],
            "C": c_candidates,
            "D": ["uD"],
        },
    )
    dynamic_edge_p_on = {
        ("uA", "uC1"): 0.85,
        ("uC1", "uD"): 0.85,
        ("uA", "uC2"): 0.85,
        ("uC2", "uD"): 0.85,
    }
    return SyntheticThroughputCase(
        name="wireless_mixed_mapping_fork_join",
        description=(
            "Wireless fork-join DAG whose boundary requires mixing the two "
            "private C-node mappings."
        ),
        network=net,
        commodity=commodity,
        dynamic_edge_p_on=dynamic_edge_p_on,
        default_interference_model="primary",
    )


class CountingExactSolver(ExactEnumerationSolver):
    """Record the selected C node once for every mapping decision."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.choice_sequence: List[str] = []

    def compute(self, dag, commodity, q_link, q_node):
        mapping = super().compute(dag, commodity, q_link, q_node)
        self.choice_sequence.append(str(mapping.assign["C"]))
        return mapping


class ArrivalAuditSimulator(DCNCSimulator):
    """Capture bounded-arrival draws without changing simulator behavior."""

    def __init__(self, *args, **kwargs):
        self.arrival_draws: List[int] = []
        super().__init__(*args, **kwargs)

    def _sample_arrivals(self, *args, **kwargs):
        value = super()._sample_arrivals(*args, **kwargs)
        scalar = int(value)
        if scalar != value:
            raise AssertionError("arrival draw is not integer-valued: {}".format(value))
        self.arrival_draws.append(scalar)
        return value


class AuditedIIDOnOffProcess(IIDOnOffProcess):
    """Record the wireless path without changing the process RNG calls."""

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
    waiting_payload = waiting_payload_size(physical_network)
    return {
        "physical_object_backlog": waiting_components + link_objects + node_objects,
        "physical_queue_workload": queue_workload,
        "physical_workload_plus_waiting_components": queue_workload + waiting_components,
        "physical_workload_plus_waiting_packets": queue_workload + waiting_packets,
        "physical_workload_plus_waiting_payload": queue_workload + waiting_payload,
        "waiting_components": waiting_components,
        "waiting_packets": waiting_packets,
        "waiting_payload": waiting_payload,
    }


class IncrementalPhysicalMetricObserver:
    """Track exact physical metrics in 0.1-workload integer units.

    The instance uses only workloads and capacities that are integer multiples
    of 0.1. Updating those totals at enqueue, service, and synchronization
    events avoids repeatedly scanning a linearly growing overloaded queue.
    """

    def __init__(self, physical_network):
        self.physical_network = physical_network
        self.link_units = {edge: 0 for edge in physical_network.link_queues}
        self.node_units = {node: 0 for node in physical_network.node_queues}
        self.waiting_components = 0
        self.waiting_packets = 0
        self.waiting_payload_units = 0
        self.metric_series: Dict[str, List[float]] = {}
        self._install()

    @staticmethod
    def _units(value: float) -> int:
        units = int(round(float(value) / WORKLOAD_QUANTUM))
        if not math.isclose(
            units * WORKLOAD_QUANTUM, float(value), rel_tol=0.0, abs_tol=1e-9
        ):
            raise AssertionError("workload is not a multiple of 0.1: {}".format(value))
        return units

    def _record_state(self, node: str, func: str, job_id: str) -> Tuple[int, int, int]:
        table = self.physical_network.wait_pools.get((node, func), {})
        record = table.get(job_id)
        if record is None:
            return (0, 0, 0)
        dag = self.physical_network.job_ctx[job_id]["dag"]
        payload_units = 0
        for predecessor in record["arrived"]:
            if isinstance(predecessor, tuple) and predecessor[0] == "S":
                payload_units += self._units(dag.xi_source()[func])
            else:
                payload_units += self._units(dag.xi(predecessor, func))
        return (1, len(record["arrived"]), payload_units)

    def _wait_target(self, item) -> Optional[Tuple[str, str, str]]:
        left, right = item.edge_key
        if isinstance(right, tuple) and right[0] == "D":
            return None
        ctx = self.physical_network.job_ctx[item.job_id]
        if isinstance(left, tuple) and left[0] == "S":
            func = str(left[1])
        else:
            func = str(right)
        return (str(ctx["mapping"].assign[func]), func, str(item.job_id))

    def _install(self) -> None:
        physical = self.physical_network
        original_enqueue_link = physical._enqueue_link_item
        original_enqueue_compute = physical._enqueue_compute_task
        original_on_path_end = physical._on_path_end
        original_serve_links = physical._serve_links_one_slot
        original_serve_nodes = physical._serve_nodes_one_slot
        original_total_backlog = physical.total_backlog

        def tracked_enqueue_link(item):
            edge = item.current_edge()
            if edge is not None:
                self.link_units[edge] += self._units(item.size_remaining)
            return original_enqueue_link(item)

        def tracked_enqueue_compute(task):
            self.node_units[task.node] += self._units(task.size_remaining)
            return original_enqueue_compute(task)

        def tracked_on_path_end(item):
            target = self._wait_target(item)
            before = (0, 0, 0) if target is None else self._record_state(*target)
            result = original_on_path_end(item)
            after = (0, 0, 0) if target is None else self._record_state(*target)
            self.waiting_components += after[0] - before[0]
            self.waiting_packets += after[1] - before[1]
            self.waiting_payload_units += after[2] - before[2]
            return result

        def tracked_serve_links():
            start_units = dict(self.link_units)
            service_map = physical.effective_link_service_map()
            used_units = {
                edge: min(start_units[edge], self._units(service_map.get(edge, 0.0)))
                for edge in start_units
            }
            result = original_serve_links()
            for edge, units in used_units.items():
                self.link_units[edge] -= units
                if self.link_units[edge] < 0:
                    raise AssertionError("incremental link workload became negative")
            return result

        def tracked_serve_nodes():
            start_units = dict(self.node_units)
            used_units = {
                node: min(
                    start_units[node], self._units(physical.network.node_capacity(node))
                )
                for node in start_units
            }
            result = original_serve_nodes()
            for node, units in used_units.items():
                self.node_units[node] -= units
                if self.node_units[node] < 0:
                    raise AssertionError("incremental node workload became negative")
            return result

        def tracked_total_backlog() -> int:
            original = int(original_total_backlog())
            metrics = self.snapshot()
            if not math.isclose(
                metrics["physical_object_backlog"], float(original), abs_tol=1e-12
            ):
                raise AssertionError("incremental object count differs from total_backlog")
            for name, value in metrics.items():
                self.metric_series.setdefault(name, []).append(float(value))
            return original

        physical._enqueue_link_item = tracked_enqueue_link
        physical._enqueue_compute_task = tracked_enqueue_compute
        physical._on_path_end = tracked_on_path_end
        physical._serve_links_one_slot = tracked_serve_links
        physical._serve_nodes_one_slot = tracked_serve_nodes
        physical.total_backlog = tracked_total_backlog

    def snapshot(self) -> Dict[str, float]:
        physical = self.physical_network
        link_objects = sum(len(queue) for queue in physical.link_queues.values())
        node_objects = sum(len(queue) for queue in physical.node_queues.values())
        queue_workload = WORKLOAD_QUANTUM * (
            sum(self.link_units.values()) + sum(self.node_units.values())
        )
        waiting_payload = WORKLOAD_QUANTUM * self.waiting_payload_units
        return {
            "physical_object_backlog": float(
                self.waiting_components + link_objects + node_objects
            ),
            "physical_queue_workload": queue_workload,
            "physical_workload_plus_waiting_components": (
                queue_workload + self.waiting_components
            ),
            "physical_workload_plus_waiting_packets": (
                queue_workload + self.waiting_packets
            ),
            "physical_workload_plus_waiting_payload": (
                queue_workload + waiting_payload
            ),
            "waiting_components": float(self.waiting_components),
            "waiting_packets": float(self.waiting_packets),
            "waiting_payload": waiting_payload,
        }

    def assert_matches_full_scan(self) -> None:
        incremental = self.snapshot()
        scanned = physical_metric_snapshot(self.physical_network)
        for name, expected in scanned.items():
            if not math.isclose(
                incremental[name], expected, rel_tol=0.0, abs_tol=1e-7
            ):
                raise AssertionError(
                    "incremental {} differs from full scan: {} versus {}".format(
                        name, incremental[name], expected
                    )
                )


def tail_slope(values: Sequence[float]) -> float:
    start = len(values) // 2
    y = np.asarray(values[start:], dtype=float)
    if len(y) < 2:
        return 0.0
    return float(np.polyfit(np.arange(len(y), dtype=float), y, 1)[0])


def standard_error(values: pd.Series) -> float:
    if len(values) < 2:
        return math.nan
    return float(values.std(ddof=1) / math.sqrt(len(values)))


def weighted_mapping_counts(
    arrival_draws: Sequence[int], choice_sequence: Sequence[str]
) -> Counter:
    positive_draws = [draw for draw in arrival_draws if draw > 0]
    if len(positive_draws) != len(choice_sequence):
        raise AssertionError(
            "mapping/arrival alignment failed: {} choices for {} positive-arrival slots".format(
                len(choice_sequence), len(positive_draws)
            )
        )
    counts = Counter()
    for draw, choice in zip(positive_draws, choice_sequence):
        counts[choice] += draw
    return counts


def run_one(
    task: Tuple[int, str, float, int, str]
) -> Dict[str, Union[str, int, float, bool]]:
    slots, policy, arrival_rate, seed, metric_mode = task
    case = make_case(policy)
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
        run_label="new_7_2_{}_r{:.4f}_s{}".format(policy, arrival_rate, seed),
        progress_every=max(slots // 5, 1),
    )

    observer: Optional[IncrementalPhysicalMetricObserver] = None
    metric_series: Dict[str, List[float]] = {}
    if metric_mode == "incremental":
        observer = IncrementalPhysicalMetricObserver(sim.physical_network)
        metric_series = observer.metric_series
    elif metric_mode == "scan":
        original_total_backlog = sim.physical_network.total_backlog

        def audited_total_backlog() -> int:
            metrics = physical_metric_snapshot(sim.physical_network)
            original = int(original_total_backlog())
            if not math.isclose(
                metrics["physical_object_backlog"], float(original), abs_tol=1e-12
            ):
                raise AssertionError("passive object count differs from simulator total_backlog")
            for name, value in metrics.items():
                metric_series.setdefault(name, []).append(float(value))
            return original

        sim.physical_network.total_backlog = audited_total_backlog
    else:
        raise ValueError("unknown metric mode: {}".format(metric_mode))
    stats = sim.run()

    if observer is not None:
        observer.assert_matches_full_scan()

    if len(sim.arrival_draws) != slots:
        raise AssertionError(
            "expected one arrival draw per slot, got {} for {} slots".format(
                len(sim.arrival_draws), slots
            )
        )
    if wireless.sample_calls != slots + 1:
        raise AssertionError(
            "expected {} wireless samples including construction, got {}".format(
                slots + 1, wireless.sample_calls
            )
        )
    if any(len(values) != slots for values in metric_series.values()):
        raise AssertionError("a passive physical metric lacks one sample per slot")
    total_arrivals = int(sum(sim.arrival_draws))
    if int(stats.total_service_units) != total_arrivals:
        raise AssertionError(
            "stats total {} differs from audited arrivals {}".format(
                stats.total_service_units, total_arrivals
            )
        )

    request_counts = weighted_mapping_counts(sim.arrival_draws, solver.choice_sequence)
    decision_counts = Counter(solver.choice_sequence)
    completed = int(stats.completed_service_units)
    virtual = [
        link + node
        for link, node in zip(stats.vq_link_sum_series, stats.vq_node_sum_series)
    ]
    metric_slopes = {
        "{}_tail_slope".format(name): tail_slope(values)
        for name, values in metric_series.items()
    }
    object_slope = metric_slopes["physical_object_backlog_tail_slope"]
    physical_workload_slope = metric_slopes[
        "physical_workload_plus_waiting_payload_tail_slope"
    ]
    virtual_slope = tail_slope(virtual)
    request_count_sum = sum(request_counts.values())
    decision_count_sum = sum(decision_counts.values())

    result: Dict[str, Union[str, int, float, bool]] = {
        "policy": policy,
        "arrival_rate": arrival_rate,
        "seed": seed,
        "slots": slots,
        "total_arrivals": total_arrivals,
        "completed_requests": completed,
        "completed_throughput": completed / slots,
        "completion_ratio": completed / total_arrivals if total_arrivals else 1.0,
        "physical_object_backlog_tail_slope": object_slope,
        "physical_workload_tail_slope": physical_workload_slope,
        "virtual_workload_tail_slope": virtual_slope,
        "physical_object_flag": object_slope > BACKLOG_SLOPE_CUTOFF,
        "physical_workload_flag": physical_workload_slope > BACKLOG_SLOPE_CUTOFF,
        "virtual_workload_flag": virtual_slope > BACKLOG_SLOPE_CUTOFF,
        "backlog_flag": max(physical_workload_slope, virtual_slope)
        > BACKLOG_SLOPE_CUTOFF,
        "legacy_object_or_virtual_flag": max(object_slope, virtual_slope)
        > BACKLOG_SLOPE_CUTOFF,
        "mapping_calls": decision_count_sum,
        "share_m1_requests": (
            request_counts["uC1"] / request_count_sum if request_count_sum else math.nan
        ),
        "share_m1_calls": (
            decision_counts["uC1"] / decision_count_sum if decision_count_sum else math.nan
        ),
        "arrival_path_sha256": hashlib.sha256(bytes(sim.arrival_draws)).hexdigest(),
        "wireless_path_sha256": wireless.run_path_sha256(),
    }
    result.update(metric_slopes)
    for index, edge in enumerate(DYNAMIC_EDGES):
        result["on_fraction_{}->{}".format(edge[0], edge[1])] = (
            wireless.on_counts[index] / slots
        )
    return result


def summarize_runs(runs: pd.DataFrame) -> pd.DataFrame:
    return (
        runs.groupby(["policy", "arrival_rate"], as_index=False)
        .agg(
            completed_throughput=("completed_throughput", "mean"),
            completed_throughput_se=("completed_throughput", standard_error),
            completion_ratio=("completion_ratio", "mean"),
            completion_ratio_se=("completion_ratio", standard_error),
            share_m1_requests=("share_m1_requests", "mean"),
            share_m1_requests_se=("share_m1_requests", standard_error),
            share_m1_calls=("share_m1_calls", "mean"),
            physical_object_backlog_tail_slope=(
                "physical_object_backlog_tail_slope",
                "mean",
            ),
            physical_object_backlog_tail_slope_se=(
                "physical_object_backlog_tail_slope",
                standard_error,
            ),
            physical_workload_tail_slope=("physical_workload_tail_slope", "mean"),
            physical_workload_tail_slope_se=(
                "physical_workload_tail_slope",
                standard_error,
            ),
            virtual_workload_tail_slope=("virtual_workload_tail_slope", "mean"),
            virtual_workload_tail_slope_se=(
                "virtual_workload_tail_slope",
                standard_error,
            ),
            physical_object_flags=("physical_object_flag", "sum"),
            physical_workload_flags=("physical_workload_flag", "sum"),
            virtual_workload_flags=("virtual_workload_flag", "sum"),
            backlog_flags=("backlog_flag", "sum"),
            legacy_object_or_virtual_flags=("legacy_object_or_virtual_flag", "sum"),
        )
        .sort_values(["policy", "arrival_rate"])
    )


def verify_paired_arrivals(runs: pd.DataFrame) -> None:
    main = runs[runs["policy"] == "mixed"]
    ablation = runs[runs["policy"] == "single_m1"]
    common = main.merge(
        ablation,
        on=["arrival_rate", "seed"],
        suffixes=("_main", "_ablation"),
    )
    if common.empty:
        raise AssertionError("no paired main/ablation runs were found")
    mismatches = common[
        common["arrival_path_sha256_main"] != common["arrival_path_sha256_ablation"]
    ]
    if not mismatches.empty:
        raise AssertionError("paired runs do not share identical arrival sample paths")
    wireless_mismatches = common[
        common["wireless_path_sha256_main"]
        != common["wireless_path_sha256_ablation"]
    ]
    if not wireless_mismatches.empty:
        raise AssertionError("paired runs do not share identical wireless sample paths")


def solve_lp_audit() -> Tuple[object, pd.DataFrame]:
    case = make_case("mixed")
    activation = build_activation_policy("primary")
    mappings = enumerate_all_valid_mappings_small(
        case.network, case.commodity.service_dag, case.commodity
    )
    if len(mappings) != 2:
        raise RuntimeError("expected exactly two mappings, found {}".format(len(mappings)))
    full_lp = solve_single_commodity_capacity_gurobi(
        case.network,
        case.commodity.service_dag,
        case.commodity,
        mappings,
        case.dynamic_edge_p_on,
        activation,
    )

    rows = []
    for index, mapping in enumerate(mappings):
        single_lp = solve_single_commodity_capacity_gurobi(
            case.network,
            case.commodity.service_dag,
            case.commodity,
            [mapping],
            case.dynamic_edge_p_on,
            activation,
        )
        rows.append(
            {
                "mapping_index": index,
                "C_node": mapping.assign["C"],
                "single_mapping_capacity": single_lp.objective,
                "mixed_lp_rate": full_lp.mapping_rates.get(index, 0.0),
            }
        )
    if not math.isclose(full_lp.objective, 1.0, rel_tol=0.0, abs_tol=1e-8):
        raise AssertionError("expected lambda*=1, got {}".format(full_lp.objective))
    return full_lp, pd.DataFrame(rows)


def first_reliably_flagged_rate(summary: pd.DataFrame, seeds: int) -> Optional[float]:
    main = summary[summary["policy"] == "mixed"].sort_values("arrival_rate")
    flagged = main[
        (main["arrival_rate"] > 1.0) & (main["backlog_flags"] == seeds)
    ]
    if flagged.empty:
        return None
    return float(flagged.iloc[0]["arrival_rate"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--slots", type=int, default=100_000)
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--workers", type=int, default=25)
    parser.add_argument(
        "--metric-mode", choices=("incremental", "scan"), default="incremental"
    )
    parser.add_argument("--main-rates", nargs="*", type=float, default=MAIN_RATES)
    parser.add_argument(
        "--ablation-boundary-rates",
        nargs="*",
        type=float,
        default=ABLATION_BOUNDARY_RATES,
    )
    args = parser.parse_args()
    if args.slots <= 0 or args.seeds <= 0:
        parser.error("--slots and --seeds must be positive")
    python_hash_seed = os.environ.get("PYTHONHASHSEED")
    if python_hash_seed != "0":
        parser.error(
            "launch with PYTHONHASHSEED=0 so equal-weight NetworkX matchings "
            "are reproducible across interpreter processes"
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    full_lp, lp_rows = solve_lp_audit()
    lp_rows.to_csv(args.output_dir / "lp_decomposition.csv", index=False)

    main_rates = sorted(set(float(rate) for rate in args.main_rates))
    ablation_rates = sorted(
        set(main_rates) | set(float(rate) for rate in args.ablation_boundary_rates)
    )
    tasks = [
        (args.slots, "mixed", rate * full_lp.objective, seed, args.metric_mode)
        for rate in main_rates
        for seed in range(args.seeds)
    ]
    tasks.extend(
        (args.slots, "single_m1", rate * full_lp.objective, seed, args.metric_mode)
        for rate in ablation_rates
        for seed in range(args.seeds)
    )

    run_rows = []
    with ProcessPoolExecutor(max_workers=min(args.workers, len(tasks))) as executor:
        futures = [executor.submit(run_one, task) for task in tasks]
        for completed_count, future in enumerate(as_completed(futures), start=1):
            run_rows.append(future.result())
            pd.DataFrame(run_rows).sort_values(
                ["policy", "arrival_rate", "seed"]
            ).to_csv(args.output_dir / "runs_partial.csv", index=False)
            print("completed {}/{}".format(completed_count, len(tasks)), flush=True)

    runs = pd.DataFrame(run_rows).sort_values(["policy", "arrival_rate", "seed"])
    verify_paired_arrivals(runs)
    summary = summarize_runs(runs)
    first_flagged = first_reliably_flagged_rate(summary, args.seeds)

    runs.to_csv(args.output_dir / "runs.csv", index=False)
    summary.to_csv(args.output_dir / "summary.csv", index=False)
    metadata = {
        "instance": "new_section_7_2_wireless_mixed_mapping",
        "lp_lambda_star": full_lp.objective,
        "lp_mapping_rates": full_lp.mapping_rates,
        "num_valid_mappings": len(lp_rows),
        "slots": args.slots,
        "logical_seeds": list(range(args.seeds)),
        "simulator_seed_offset": 30_000,
        "solver_seed_offset": 20_000,
        "wireless_seed_formula": "10000 + 101 * logical_seed",
        "main_rates": main_rates,
        "ablation_rates": ablation_rates,
        "arrival_mode": "bounded",
        "interference_model": "primary",
        "dynamic_edge_p_on": 0.85,
        "backlog_slope_cutoff": BACKLOG_SLOPE_CUTOFF,
        "physical_metric_collection": args.metric_mode,
        "workload_quantum": WORKLOAD_QUANTUM,
        "backlog_metric": (
            "max(physical queue workload plus synchronization-pool waiting "
            "payload, virtual workload)"
        ),
        "first_reliably_flagged_rate": first_flagged,
        "overload_resolution_percent": (
            None if first_flagged is None else 100.0 * (first_flagged / full_lp.objective - 1.0)
        ),
        "paired_arrival_paths_verified": True,
        "paired_wireless_paths_verified": True,
        "mapping_share_definition": "arrival-weighted request fraction",
        "python": platform.python_version(),
        "python_hash_seed": python_hash_seed,
    }
    (args.output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, indent=2, sort_keys=True))
    print(lp_rows.to_string(index=False))
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
