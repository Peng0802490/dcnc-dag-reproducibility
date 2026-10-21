#!/usr/bin/env python3
"""Exact state-averaged LP audit for the wireless mixed-mapping instance.

The script is independent of the DCNC-DAG simulator. It enumerates every
wireless state and every primary-interference matching, then solves the LP in
Section 2.2 of the paper. This makes it a useful pre-run check for the instance
definition and for the simulator's own capacity-LP result.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

try:
    from scipy.optimize import linprog
except ImportError as exc:  # pragma: no cover - exercised only on missing dependency
    raise SystemExit(
        "SciPy is required. Install it in the active environment or prepend "
        "the repository-local .codex/vendor directory to PYTHONPATH."
    ) from exc


NODES = ("s", "uA", "uB", "uC1", "uC2", "uD", "d")
LINKS = (
    ("s", "uA"),
    ("uA", "uB"),
    ("uB", "uD"),
    ("uA", "uC1"),
    ("uC1", "uD"),
    ("uA", "uC2"),
    ("uC2", "uD"),
    ("uD", "d"),
)
DYNAMIC_LINKS = (3, 4, 5, 6)
MAPPING_LINK_LOADS = np.asarray(
    [
        (0.2, 0.2, 0.2, 1.0, 1.0, 0.0, 0.0, 0.2),
        (0.2, 0.2, 0.2, 0.0, 0.0, 1.0, 1.0, 0.2),
    ],
    dtype=float,
)
COMPUTE_NODES = ("uA", "uB", "uC1", "uC2", "uD")
MAPPING_NODE_LOADS = np.asarray(
    [
        (0.1, 0.1, 1.0, 0.0, 0.1),
        (0.1, 0.1, 0.0, 1.0, 0.1),
    ],
    dtype=float,
)
NODE_CAPACITIES = np.asarray((5.0, 5.0, 0.5, 0.5, 5.0), dtype=float)


@dataclass(frozen=True)
class LPResult:
    name: str
    objective: float
    mapping_rates: Tuple[float, float]
    link_loads: Tuple[float, ...]
    link_services: Tuple[float, ...]
    node_loads: Tuple[float, ...]
    state_probability_sum: float
    num_activation_variables: int

    def as_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "objective": self.objective,
            "mapping_rates": list(self.mapping_rates),
            "link_loads": list(self.link_loads),
            "link_services": list(self.link_services),
            "node_loads": list(self.node_loads),
            "state_probability_sum": self.state_probability_sum,
            "num_activation_variables": self.num_activation_variables,
        }


def all_primary_matchings() -> List[Tuple[int, ...]]:
    """Enumerate all link subsets satisfying one incident link per node."""

    matchings: List[Tuple[int, ...]] = [tuple()]
    for size in range(1, len(LINKS) + 1):
        for subset in combinations(range(len(LINKS)), size):
            endpoints: List[str] = []
            for edge_index in subset:
                endpoints.extend(LINKS[edge_index])
            if len(endpoints) == len(set(endpoints)):
                matchings.append(subset)
    return matchings


def wireless_states(p_on: float) -> List[Tuple[int, float, Tuple[int, ...]]]:
    states = []
    for state_mask in range(1 << len(DYNAMIC_LINKS)):
        on_dynamic = tuple(
            edge_index
            for bit, edge_index in enumerate(DYNAMIC_LINKS)
            if state_mask & (1 << bit)
        )
        on_count = len(on_dynamic)
        probability = p_on ** on_count * (1.0 - p_on) ** (len(DYNAMIC_LINKS) - on_count)
        states.append((state_mask, probability, on_dynamic))
    return states


def solve_capacity_lp(
    name: str,
    p_on: float,
    link_capacity: float,
    allowed_mappings: Sequence[int] = (0, 1),
    include_compute: bool = True,
    force_equal_rates: bool = False,
) -> LPResult:
    matchings = all_primary_matchings()
    states = wireless_states(p_on)

    activation_columns: List[Tuple[int, float, Tuple[int, ...]]] = []
    state_columns: Dict[int, List[int]] = {}
    always_on = set(range(len(LINKS))) - set(DYNAMIC_LINKS)
    for state_mask, probability, on_dynamic in states:
        available = always_on | set(on_dynamic)
        state_columns[state_mask] = []
        for matching in matchings:
            if set(matching).issubset(available):
                state_columns[state_mask].append(len(activation_columns))
                activation_columns.append((state_mask, probability, matching))

    # Variables are f_0, f_1, followed by unconditional state-activation
    # frequencies nu_(state,matching). Disallowed mappings are fixed to zero.
    variable_count = 2 + len(activation_columns)
    objective = np.zeros(variable_count, dtype=float)
    objective[0:2] = -1.0
    bounds: List[Tuple[float, Optional[float]]] = []
    allowed = set(allowed_mappings)
    for mapping_index in range(2):
        bounds.append((0.0, None) if mapping_index in allowed else (0.0, 0.0))
    bounds.extend((0.0, None) for _ in activation_columns)

    a_ub: List[np.ndarray] = []
    b_ub: List[float] = []

    for link_index in range(len(LINKS)):
        row = np.zeros(variable_count, dtype=float)
        row[0:2] = MAPPING_LINK_LOADS[:, link_index]
        for column_index, (_, _, matching) in enumerate(activation_columns):
            if link_index in matching:
                row[2 + column_index] = -link_capacity
        a_ub.append(row)
        b_ub.append(0.0)

    if include_compute:
        for node_index in range(len(COMPUTE_NODES)):
            row = np.zeros(variable_count, dtype=float)
            row[0:2] = MAPPING_NODE_LOADS[:, node_index]
            a_ub.append(row)
            b_ub.append(float(NODE_CAPACITIES[node_index]))

    probability_sum = 0.0
    for state_mask, probability, _ in states:
        row = np.zeros(variable_count, dtype=float)
        for column_index in state_columns[state_mask]:
            row[2 + column_index] = 1.0
        a_ub.append(row)
        b_ub.append(probability)
        probability_sum += probability

    a_eq = None
    b_eq = None
    if force_equal_rates:
        a_eq = np.zeros((1, variable_count), dtype=float)
        a_eq[0, 0] = 1.0
        a_eq[0, 1] = -1.0
        b_eq = np.zeros(1, dtype=float)

    solution = linprog(
        c=objective,
        A_ub=np.asarray(a_ub),
        b_ub=np.asarray(b_ub),
        A_eq=a_eq,
        b_eq=b_eq,
        bounds=bounds,
        method="highs",
    )
    if not solution.success:
        raise RuntimeError("{} failed: {}".format(name, solution.message))

    rates = solution.x[0:2]
    link_loads = rates @ MAPPING_LINK_LOADS
    node_loads = rates @ MAPPING_NODE_LOADS
    link_services = np.zeros(len(LINKS), dtype=float)
    for column_index, (_, _, matching) in enumerate(activation_columns):
        frequency = solution.x[2 + column_index]
        for link_index in matching:
            link_services[link_index] += frequency * link_capacity

    return LPResult(
        name=name,
        objective=float(-solution.fun),
        mapping_rates=(float(rates[0]), float(rates[1])),
        link_loads=tuple(float(value) for value in link_loads),
        link_services=tuple(float(value) for value in link_services),
        node_loads=tuple(float(value) for value in node_loads),
        state_probability_sum=probability_sum,
        num_activation_variables=len(activation_columns),
    )


def assert_close(actual: float, expected: float, label: str, tolerance: float = 1e-8) -> None:
    if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=tolerance):
        raise AssertionError("{}: expected {}, got {}".format(label, expected, actual))


def write_link_audit(path: Path, result: LPResult) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("link_index", "link", "load", "service", "slack"),
        )
        writer.writeheader()
        for index, ((src, dst), load, service) in enumerate(
            zip(LINKS, result.link_loads, result.link_services), start=1
        ):
            writer.writerow(
                {
                    "link_index": index,
                    "link": "{}->{}".format(src, dst),
                    "load": "{:.12g}".format(load),
                    "service": "{:.12g}".format(service),
                    "slack": "{:.12g}".format(service - load),
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--p-on", type=float, default=0.85)
    parser.add_argument("--link-capacity", type=float, default=2.0)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if not 0.0 < args.p_on <= 1.0:
        parser.error("--p-on must lie in (0, 1]")
    if args.link_capacity <= 0.0:
        parser.error("--link-capacity must be positive")

    full = solve_capacity_lp(
        "full_mixed_mapping", args.p_on, args.link_capacity
    )
    single_m1 = solve_capacity_lp(
        "single_m1", args.p_on, args.link_capacity, allowed_mappings=(0,)
    )
    single_m2 = solve_capacity_lp(
        "single_m2", args.p_on, args.link_capacity, allowed_mappings=(1,)
    )
    wireless_only_equal = solve_capacity_lp(
        "wireless_only_equal_mixture",
        args.p_on,
        args.link_capacity,
        include_compute=False,
        force_equal_rates=True,
    )

    assert_close(full.objective, 1.0, "mixed-mapping capacity")
    assert_close(full.mapping_rates[0], 0.5, "m1 optimal rate")
    assert_close(full.mapping_rates[1], 0.5, "m2 optimal rate")
    assert_close(single_m1.objective, 0.5, "single-m1 capacity")
    assert_close(single_m2.objective, 0.5, "single-m2 capacity")
    if wireless_only_equal.objective <= full.objective + 1e-8:
        raise AssertionError("wireless constraints have no strict headroom at lambda=1")

    report = {
        "instance": "new_section_7_2_wireless_mixed_mapping",
        "p_on": args.p_on,
        "link_capacity": args.link_capacity,
        "num_wireless_states": 1 << len(DYNAMIC_LINKS),
        "num_primary_matchings_before_state_filter": len(all_primary_matchings()),
        "results": [
            full.as_dict(),
            single_m1.as_dict(),
            single_m2.as_dict(),
            wireless_only_equal.as_dict(),
        ],
        "wireless_equal_mixture_headroom_ratio": wireless_only_equal.objective / full.objective,
        "checks": {
            "full_capacity_is_1": True,
            "unique_boundary_rates_are_0p5_0p5": True,
            "each_single_mapping_capacity_is_0p5": True,
            "wireless_constraints_are_nonbinding_at_lambda_1": True,
        },
    }

    if args.output_dir is not None:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "capacity_lp_audit.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        write_link_audit(args.output_dir / "capacity_lp_link_audit.csv", full)

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
