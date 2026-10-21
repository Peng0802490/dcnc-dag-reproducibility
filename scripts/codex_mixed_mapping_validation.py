#!/usr/bin/env python3
"""LP and five-seed validation for a fork-join case requiring mapping mixing.

The instance has exactly two valid mappings. Each mapping alone is limited to
0.5 requests/slot by its private branch, whereas a 50/50 mixture uses both
branches and reaches the LP boundary of 1.0 request/slot. The experiment is
intended to complement, not replace, the paper's wireless fork-join case.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

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
from dcnc_sim.wireless import AlwaysOnProcess


def make_case() -> SyntheticThroughputCase:
    net = _new_network("mixed_mapping_fork_join")
    for node, role, capacity in [
        ("s", "FORWARD", 0.0),
        ("uA", "COMPUTE", 4.0),
        ("uB", "COMPUTE", 4.0),
        ("uC1", "COMPUTE", 0.5),
        ("uC2", "COMPUTE", 0.5),
        ("uD", "COMPUTE", 4.0),
        ("d", "FORWARD", 0.0),
    ]:
        _add_node(net, node, role, capacity)
    for edge, capacity in [
        (("s", "uA"), 4.0),
        (("uA", "uB"), 4.0),
        (("uB", "uD"), 4.0),
        (("uA", "uC1"), 0.5),
        (("uC1", "uD"), 0.5),
        (("uA", "uC2"), 0.5),
        (("uC2", "uD"), 0.5),
        (("uD", "d"), 4.0),
    ]:
        _add_edge(net, edge[0], edge[1], capacity)
    net.validate()

    dag = _new_dag("mixed_mapping_fork_join_dag")
    _add_dag_node(dag, "A", "source", r=0.1, xin=0.2)
    _add_dag_node(dag, "B", "function", r=0.1)
    _add_dag_node(dag, "C", "function", r=1.0)
    _add_dag_node(dag, "D", "sink", r=0.1, xout=0.2)
    _add_dag_edge(dag, "A", "B", xi=0.2)
    _add_dag_edge(dag, "A", "C", xi=1.0)
    _add_dag_edge(dag, "B", "D", xi=0.2)
    _add_dag_edge(dag, "C", "D", xi=1.0)
    dag.validate()

    commodity = Commodity(
        name="mixed_mapping_fork_join",
        service_dag=dag,
        src_nodes={"A": "s"},
        dst_nodes={"D": "d"},
        allowed={
            "A": ["uA"],
            "B": ["uB"],
            "C": ["uC1", "uC2"],
            "D": ["uD"],
        },
    )
    return SyntheticThroughputCase(
        name="mixed_mapping_fork_join",
        description="Fork-join DAG with two private C-branch mappings that must be mixed.",
        network=net,
        commodity=commodity,
        dynamic_edge_p_on={},
        default_interference_model="none",
    )


class CountingExactSolver(ExactEnumerationSolver):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.choices: Counter[str] = Counter()

    def compute(self, dag, commodity, q_link, q_node):
        mapping = super().compute(dag, commodity, q_link, q_node)
        self.choices[str(mapping.assign["C"])] += 1
        return mapping


def tail_slope(values: list[float]) -> float:
    start = len(values) // 2
    y = np.asarray(values[start:], dtype=float)
    if len(y) < 2:
        return 0.0
    return float(np.polyfit(np.arange(len(y), dtype=float), y, 1)[0])


def run_one(task: tuple[int, float, float, int]) -> dict[str, float | int]:
    slots, factor, arrival_rate, seed = task
    case = make_case()
    activation = build_activation_policy("none")
    solver = CountingExactSolver(case.network, seed=20_000 + seed)
    sim = DCNCSimulator(
        network=case.network,
        commodity_cfgs=[CommodityConfig(case.commodity, arrival_rate, solver)],
        wireless_process=AlwaysOnProcess(case.network),
        total_slots=slots,
        seed=30_000 + seed,
        scheduler="nto",
        activation_policy=activation,
        fixed_k=1,
        arrival_mode="bounded",
        run_label=f"mixed_mapping_f{factor:.3f}_s{seed}",
        progress_every=max(slots // 5, 1),
    )
    stats = sim.run()
    completed = int(stats.completed_service_units)
    total = int(stats.total_service_units)
    virtual = [
        link + node
        for link, node in zip(stats.vq_link_sum_series, stats.vq_node_sum_series)
    ]
    decisions = sum(solver.choices.values())
    return {
        "factor": factor,
        "arrival_rate": arrival_rate,
        "seed": seed,
        "completed_throughput": completed / slots,
        "completion_ratio": completed / total if total else 1.0,
        "physical_tail_slope": tail_slope(stats.physical_backlog_series),
        "virtual_tail_slope": tail_slope(virtual),
        "mapping_calls": decisions,
        "share_C_uC1": solver.choices["uC1"] / decisions if decisions else math.nan,
        "share_C_uC2": solver.choices["uC2"] / decisions if decisions else math.nan,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--slots", type=int, default=100_000)
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--workers", type=int, default=25)
    parser.add_argument(
        "--factors",
        nargs="*",
        type=float,
        default=[0.95, 0.99, 1.01, 1.05, 1.10],
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    case = make_case()
    activation = build_activation_policy("none")
    mappings = enumerate_all_valid_mappings_small(
        case.network, case.commodity.service_dag, case.commodity
    )
    if len(mappings) != 2:
        raise RuntimeError(f"expected two valid mappings, found {len(mappings)}")

    full_lp = solve_single_commodity_capacity_gurobi(
        case.network,
        case.commodity.service_dag,
        case.commodity,
        mappings,
        {},
        activation,
    )
    mapping_rows = []
    for index, mapping in enumerate(mappings):
        single_lp = solve_single_commodity_capacity_gurobi(
            case.network,
            case.commodity.service_dag,
            case.commodity,
            [mapping],
            {},
            activation,
        )
        mapping_rows.append(
            {
                "mapping_index": index,
                "C_node": mapping.assign["C"],
                "single_mapping_capacity": single_lp.objective,
                "mixed_lp_rate": full_lp.mapping_rates.get(index, 0.0),
            }
        )
    pd.DataFrame(mapping_rows).to_csv(
        args.output_dir / "mixed_mapping_lp_decomposition.csv", index=False
    )

    tasks = [
        (args.slots, factor, factor * full_lp.objective, seed)
        for factor in args.factors
        for seed in range(args.seeds)
    ]
    run_rows = []
    with ProcessPoolExecutor(max_workers=min(args.workers, len(tasks))) as executor:
        futures = [executor.submit(run_one, task) for task in tasks]
        for completed_count, future in enumerate(as_completed(futures), start=1):
            run_rows.append(future.result())
            pd.DataFrame(run_rows).sort_values(["factor", "seed"]).to_csv(
                args.output_dir / "mixed_mapping_runs_partial.csv", index=False
            )
            print(f"completed {completed_count}/{len(tasks)}", flush=True)

    runs = pd.DataFrame(run_rows)
    summary = (
        runs.groupby(["factor", "arrival_rate"], as_index=False)
        .agg(
            completed_throughput=("completed_throughput", "mean"),
            throughput_se=("completed_throughput", lambda x: x.std(ddof=1) / math.sqrt(len(x))),
            completion_ratio=("completion_ratio", "mean"),
            completion_ratio_se=("completion_ratio", lambda x: x.std(ddof=1) / math.sqrt(len(x))),
            physical_tail_slope=("physical_tail_slope", "mean"),
            virtual_tail_slope=("virtual_tail_slope", "mean"),
            share_C_uC1=("share_C_uC1", "mean"),
            share_C_uC2=("share_C_uC2", "mean"),
        )
    )
    runs.to_csv(args.output_dir / "mixed_mapping_runs.csv", index=False)
    summary.to_csv(args.output_dir / "mixed_mapping_summary.csv", index=False)
    metadata = {
        "lp_lambda_star": full_lp.objective,
        "lp_mapping_rates": full_lp.mapping_rates,
        "num_valid_mappings": len(mappings),
        "slots": args.slots,
        "seeds": args.seeds,
        "factors": args.factors,
        "arrival_mode": "bounded",
        "interference_model": "none",
    }
    (args.output_dir / "mixed_mapping_metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    print(json.dumps(metadata, indent=2))
    print(pd.DataFrame(mapping_rows).to_string(index=False))
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
