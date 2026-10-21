#!/usr/bin/env python3
"""Verify the actual dcnc_sim instance against the Section 7.2 specification."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from dcnc_sim.capacity import (
    enumerate_iid_onoff_state_activations_small,
    usage_of_mapping,
)
from dcnc_sim.capacity_gurobi import (
    solve_single_commodity_capacity_gurobi,
    solve_single_commodity_capacity_scipy,
)
from dcnc_sim.interference import build_activation_policy
from dcnc_sim.mapping import enumerate_all_valid_mappings_small

from run_new_7_2_wireless_mixed_mapping import make_case


EXPECTED_NODES = ("s", "uA", "uB", "uC1", "uC2", "uD", "d")
EXPECTED_EDGES = (
    ("s", "uA"),
    ("uA", "uB"),
    ("uB", "uD"),
    ("uA", "uC1"),
    ("uC1", "uD"),
    ("uA", "uC2"),
    ("uC2", "uD"),
    ("uD", "d"),
)
EXPECTED_NODE_CAPACITIES = (0.0, 5.0, 5.0, 0.5, 0.5, 5.0, 0.0)
EXPECTED_DYNAMIC = {
    ("uA", "uC1"): 0.85,
    ("uC1", "uD"): 0.85,
    ("uA", "uC2"): 0.85,
    ("uC2", "uD"): 0.85,
}
EXPECTED_LINK_LOADS = {
    "uC1": (0.2, 0.2, 0.2, 1.0, 1.0, 0.0, 0.0, 0.2),
    "uC2": (0.2, 0.2, 0.2, 0.0, 0.0, 1.0, 1.0, 0.2),
}
EXPECTED_NODE_LOADS = {
    "uC1": (0.1, 0.1, 1.0, 0.0, 0.1),
    "uC2": (0.1, 0.1, 0.0, 1.0, 0.1),
}
COMPUTE_NODE_ORDER = ("uA", "uB", "uC1", "uC2", "uD")


def close_sequence(actual, expected, label: str) -> None:
    if not np.allclose(actual, expected, rtol=0.0, atol=1e-12):
        raise AssertionError("{} differs: expected {}, got {}".format(label, expected, actual))


def mapping_record(case, mapping):
    usage = usage_of_mapping(
        case.network, case.commodity.service_dag, case.commodity, mapping
    )
    c_node = str(mapping.assign["C"])
    link_loads = tuple(float(usage.link_usage[edge]) for edge in EXPECTED_EDGES)
    node_loads = tuple(float(usage.node_usage[node]) for node in COMPUTE_NODE_ORDER)
    close_sequence(link_loads, EXPECTED_LINK_LOADS[c_node], "{} link loads".format(c_node))
    close_sequence(node_loads, EXPECTED_NODE_LOADS[c_node], "{} node loads".format(c_node))
    return {
        "C_node": c_node,
        "assignment": dict(mapping.assign),
        "link_loads": list(link_loads),
        "node_loads": list(node_loads),
        "paths": {
            str(key): [list(edge) for edge in path]
            for key, path in sorted(mapping.edge_paths.items(), key=lambda item: str(item[0]))
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    case = make_case("mixed")
    network = case.network
    dag = case.commodity.service_dag
    commodity = case.commodity
    activation = build_activation_policy("primary")

    if tuple(network.nodes_all()) != EXPECTED_NODES:
        raise AssertionError("substrate node order/content differs from the specification")
    if tuple(network.edges_all()) != EXPECTED_EDGES:
        raise AssertionError("substrate link order/content differs from the specification")
    close_sequence(
        [network.node_capacity(node) for node in EXPECTED_NODES],
        EXPECTED_NODE_CAPACITIES,
        "node capacities",
    )
    close_sequence(
        [network.link_capacity(*edge) for edge in EXPECTED_EDGES],
        [2.0] * len(EXPECTED_EDGES),
        "link capacities",
    )
    if case.dynamic_edge_p_on != EXPECTED_DYNAMIC:
        raise AssertionError("dynamic-edge probabilities differ from the specification")
    if case.default_interference_model != "primary":
        raise AssertionError("interference model is not primary")

    if tuple(dag.topo_order()) != ("A", "B", "C", "D"):
        raise AssertionError("service DAG topological order/content differs")
    if set(dag.edges_all()) != {("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")}:
        raise AssertionError("service DAG edges differ")
    close_sequence([dag.r(node) for node in ("A", "B", "C", "D")], (0.1, 0.1, 1.0, 0.1), "function workloads")
    close_sequence(
        [dag.xi(*edge) for edge in (("A", "B"), ("A", "C"), ("B", "D"), ("C", "D"))],
        (0.2, 1.0, 0.2, 1.0),
        "dependency workloads",
    )
    if dag.xi_source() != {"A": 0.2} or dag.xi_sink() != {"D": 0.2}:
        raise AssertionError("source/sink workloads differ")
    if commodity.src_nodes != {"A": "s"} or commodity.dst_nodes != {"D": "d"}:
        raise AssertionError("service endpoints differ")
    if commodity.allowed != {
        "A": ["uA"],
        "B": ["uB"],
        "C": ["uC1", "uC2"],
        "D": ["uD"],
    }:
        raise AssertionError("function candidate sets differ")

    mappings = enumerate_all_valid_mappings_small(network, dag, commodity)
    if len(mappings) != 2:
        raise AssertionError("expected exactly two valid mappings, got {}".format(len(mappings)))
    mapping_records = sorted(
        (mapping_record(case, mapping) for mapping in mappings),
        key=lambda row: row["C_node"],
    )

    states = enumerate_iid_onoff_state_activations_small(
        network, case.dynamic_edge_p_on, activation
    )
    if len(states) != 16:
        raise AssertionError("expected 16 wireless states, got {}".format(len(states)))
    if not math.isclose(sum(state.probability for state in states), 1.0, abs_tol=1e-12):
        raise AssertionError("wireless-state probabilities do not sum to one")
    activation_counts = [len(state.activation_sets) for state in states]
    if sum(activation_counts) != 232:
        raise AssertionError("expected 232 state-activation variables")

    gurobi = solve_single_commodity_capacity_gurobi(
        network, dag, commodity, mappings, case.dynamic_edge_p_on, activation
    )
    scipy = solve_single_commodity_capacity_scipy(
        network, dag, commodity, mappings, case.dynamic_edge_p_on, activation
    )
    if not math.isclose(gurobi.objective, 1.0, abs_tol=1e-10):
        raise AssertionError("Gurobi full capacity is not 1")
    if not math.isclose(scipy.objective, 1.0, abs_tol=1e-10):
        raise AssertionError("SciPy full capacity is not 1")

    single_capacities = {}
    for mapping in mappings:
        c_node = str(mapping.assign["C"])
        single = solve_single_commodity_capacity_gurobi(
            network, dag, commodity, [mapping], case.dynamic_edge_p_on, activation
        )
        single_capacities[c_node] = float(single.objective)
        if not math.isclose(single.objective, 0.5, abs_tol=1e-10):
            raise AssertionError("single mapping {} capacity is not 0.5".format(c_node))

    mapping_rates_by_node = {
        str(mappings[index].assign["C"]): float(rate)
        for index, rate in gurobi.mapping_rates.items()
    }
    if set(mapping_rates_by_node) != {"uC1", "uC2"}:
        raise AssertionError("Gurobi did not use both mappings")
    close_sequence(
        [mapping_rates_by_node["uC1"], mapping_rates_by_node["uC2"]],
        (0.5, 0.5),
        "Gurobi mapping rates",
    )

    report = {
        "checks_passed": True,
        "instance": {
            "nodes": [
                {
                    "id": node,
                    "role": network.role(node),
                    "capacity": network.node_capacity(node),
                }
                for node in EXPECTED_NODES
            ],
            "links": [
                {
                    "index": index,
                    "from": edge[0],
                    "to": edge[1],
                    "capacity": network.link_capacity(*edge),
                    "p_on": case.dynamic_edge_p_on.get(edge, 1.0),
                }
                for index, edge in enumerate(EXPECTED_EDGES, start=1)
            ],
            "dag_topological_order": dag.topo_order(),
            "dag_edges": [list(edge) for edge in dag.edges_all()],
            "function_workloads": {node: dag.r(node) for node in dag.nodes_all()},
            "dependency_workloads": {
                "{}->{}".format(*edge): dag.xi(*edge) for edge in dag.edges_all()
            },
            "source_workloads": dag.xi_source(),
            "sink_workloads": dag.xi_sink(),
            "allowed": commodity.allowed,
            "src_nodes": commodity.src_nodes,
            "dst_nodes": commodity.dst_nodes,
        },
        "mappings": mapping_records,
        "wireless_state_count": len(states),
        "state_activation_counts": activation_counts,
        "total_state_activation_variables": sum(activation_counts),
        "capacity": {
            "gurobi": float(gurobi.objective),
            "scipy": float(scipy.objective),
            "gurobi_mapping_rates_by_C_node": mapping_rates_by_node,
            "single_mapping_capacities": single_capacities,
        },
    }
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
