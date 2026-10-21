from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

import numpy as np
from scipy.optimize import linprog

from .interference import BaseActivationPolicy, NoInterferenceActivationPolicy
from .mapping import ValidMapping
from .models import Commodity, DistributedComputingNetwork, Edge, NodeId, ServiceDAG


@dataclass
class MappingResourceUsage:
    link_usage: Dict[Edge, float]
    node_usage: Dict[NodeId, float]


@dataclass
class WirelessStateActivation:
    probability: float
    activation_sets: List[Dict[Edge, float]]


def usage_of_mapping(
    network: DistributedComputingNetwork,
    dag: ServiceDAG,
    commodity: Commodity,
    mapping: ValidMapping,
) -> MappingResourceUsage:
    link_usage = {e: 0.0 for e in network.edges_all()}
    node_usage = {u: 0.0 for u in network.nodes_all()}
    xi_s = dag.xi_source()
    xi_d = dag.xi_sink()
    for a, u in mapping.assign.items():
        node_usage[u] += dag.r(a)
    for a in dag.sources():
        for e in mapping.path_for((("S", a), a)):
            link_usage[e] += xi_s[a]
    for a, b in dag.edges_all():
        for e in mapping.path_for((a, b)):
            link_usage[e] += dag.xi(a, b)
    for a in dag.sinks():
        for e in mapping.path_for((a, ("D", a))):
            link_usage[e] += xi_d[a]
    return MappingResourceUsage(link_usage=link_usage, node_usage=node_usage)


def maximum_single_commodity_rate(
    network: DistributedComputingNetwork,
    dag: ServiceDAG,
    commodity: Commodity,
    mappings: Sequence[ValidMapping],
    avg_link_caps: Mapping[Edge, float],
) -> float:
    if not mappings:
        raise ValueError("no valid mappings provided")
    usages = [usage_of_mapping(network, dag, commodity, m) for m in mappings]
    num_vars = len(usages)
    c = -np.ones(num_vars, dtype=float)

    A_ub = []
    b_ub = []
    for e in network.edges_all():
        A_ub.append([u.link_usage[e] for u in usages])
        b_ub.append(float(avg_link_caps[e]))
    for u in network.nodes_all():
        A_ub.append([usage.node_usage[u] for usage in usages])
        b_ub.append(network.node_capacity(u))

    bounds = [(0.0, None)] * num_vars
    res = linprog(c, A_ub=np.asarray(A_ub), b_ub=np.asarray(b_ub), bounds=bounds, method="highs")
    if not res.success:
        raise RuntimeError(f"capacity LP failed: {res.message}")
    return float(-res.fun)


def enumerate_iid_onoff_state_activations_small(
    network: DistributedComputingNetwork,
    dynamic_edge_p_on: Mapping[Edge, float],
    activation_policy: BaseActivationPolicy,
) -> List[WirelessStateActivation]:
    """Enumerate wireless states and feasible activation sets for small networks.

    Intended for the boundary-validation experiment when interference constraints
    are enabled. The routine assumes edge-wise independent ON/OFF states.
    """

    dynamic_edges = sorted({(str(u), str(v)) for (u, v) in dynamic_edge_p_on})
    static_edges = {e for e in network.edges_all() if e not in dynamic_edges}
    results: List[WirelessStateActivation] = []

    if not dynamic_edges:
        on_edges = static_edges
        feasible_sets = activation_policy.enumerate_feasible_sets(network, on_edges)
        activation_maps = [
            {e: float(network.link_capacity(*e)) if e in active else 0.0 for e in network.edges_all()}
            for active in feasible_sets
        ]
        return [WirelessStateActivation(probability=1.0, activation_sets=activation_maps)]

    for bits in product([0, 1], repeat=len(dynamic_edges)):
        prob = 1.0
        on_edges = set(static_edges)
        for edge, bit in zip(dynamic_edges, bits):
            p_on = float(dynamic_edge_p_on[edge])
            if bit:
                prob *= p_on
                on_edges.add(edge)
            else:
                prob *= (1.0 - p_on)
        if prob <= 1e-15:
            continue
        feasible_sets = activation_policy.enumerate_feasible_sets(network, on_edges)
        activation_maps = [
            {e: float(network.link_capacity(*e)) if e in active else 0.0 for e in network.edges_all()}
            for active in feasible_sets
        ]
        results.append(WirelessStateActivation(probability=prob, activation_sets=activation_maps))
    return results


def maximum_single_commodity_rate_iid_onoff_with_activation(
    network: DistributedComputingNetwork,
    dag: ServiceDAG,
    commodity: Commodity,
    mappings: Sequence[ValidMapping],
    dynamic_edge_p_on: Mapping[Edge, float],
    activation_policy: BaseActivationPolicy,
) -> float:
    """Exact small-network capacity LP under IID ON/OFF links and interference.

    The LP jointly optimizes time-sharing across valid mappings and across
    feasible activation sets in each wireless state, thereby implementing the
    state-averaged service region \bar{C} for small graphs.
    """

    if not mappings:
        raise ValueError("no valid mappings provided")
    if isinstance(activation_policy, NoInterferenceActivationPolicy):
        avg_link_caps = {
            e: float(network.link_capacity(*e)) * float(dynamic_edge_p_on.get(e, 1.0))
            for e in network.edges_all()
        }
        return maximum_single_commodity_rate(network, dag, commodity, mappings, avg_link_caps)

    usages = [usage_of_mapping(network, dag, commodity, m) for m in mappings]
    states = enumerate_iid_onoff_state_activations_small(network, dynamic_edge_p_on, activation_policy)

    num_mapping_vars = len(usages)
    action_offsets: List[int] = []
    num_action_vars = 0
    for state in states:
        action_offsets.append(num_action_vars)
        num_action_vars += len(state.activation_sets)

    total_vars = num_mapping_vars + num_action_vars
    c = np.zeros(total_vars, dtype=float)
    c[:num_mapping_vars] = -1.0

    A_ub: List[List[float]] = []
    b_ub: List[float] = []

    # Link constraints: mapping load <= state-averaged activated service.
    for edge in network.edges_all():
        row = [0.0] * total_vars
        for k, usage in enumerate(usages):
            row[k] = usage.link_usage[edge]
        cursor = num_mapping_vars
        for state in states:
            for activation in state.activation_sets:
                row[cursor] = -float(activation.get(edge, 0.0))
                cursor += 1
        A_ub.append(row)
        b_ub.append(0.0)

    # Node constraints.
    for node in network.nodes_all():
        row = [0.0] * total_vars
        for k, usage in enumerate(usages):
            row[k] = usage.node_usage[node]
        A_ub.append(row)
        b_ub.append(float(network.node_capacity(node)))

    A_eq: List[List[float]] = []
    b_eq: List[float] = []
    cursor = num_mapping_vars
    for state in states:
        row = [0.0] * total_vars
        for _ in state.activation_sets:
            row[cursor] = 1.0
            cursor += 1
        A_eq.append(row)
        b_eq.append(float(state.probability))

    bounds = [(0.0, None)] * total_vars
    res = linprog(
        c,
        A_ub=np.asarray(A_ub),
        b_ub=np.asarray(b_ub),
        A_eq=np.asarray(A_eq),
        b_eq=np.asarray(b_eq),
        bounds=bounds,
        method="highs",
    )
    if not res.success:
        raise RuntimeError(f"capacity LP with activation failed: {res.message}")
    return float(-res.fun)
