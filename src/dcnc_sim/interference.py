from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
import math
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple

import networkx as nx

from .models import DistributedComputingNetwork, Edge, NodeId


def _integer_objective(edges, queues, capacities):
    """Exact products of the supplied binary floats, on one integer scale.

    Float denominators are powers of two. Scaling by their largest product
    denominator preserves every objective comparison, including tiny gaps;
    no fixed epsilon or floating-point matching tolerance is used.
    """
    ratios = {}
    for edge in edges:
        q = float(queues.get(edge, 0.0))
        cap = float(capacities[edge])
        if not math.isfinite(q) or q < 0 or not math.isfinite(cap) or cap < 0:
            raise ValueError("activation queues and capacities must be finite and nonnegative")
        qn, qd = q.as_integer_ratio()
        cn, cd = cap.as_integer_ratio()
        ratios[edge] = (qn * cn, qd * cd)
    denominator = max((d for _, d in ratios.values()), default=1)
    return {edge: n * (denominator // d) for edge, (n, d) in ratios.items()}


@dataclass
class BaseActivationPolicy:
    """Selects which currently-ON directed links are activated in a slot.

    The policy consumes the slot-start virtual link backlogs and the currently
    available ON/OFF link capacities. It returns the set of directed edges that
    are activated in the current slot.
    """

    def select_active_edges(
        self,
        network: DistributedComputingNetwork,
        q_link: Mapping[Edge, float],
        current_link_capacities: Mapping[Edge, float],
        physical_backlog: Optional[Mapping[Edge, float]] = None,
    ) -> Set[Edge]:
        raise NotImplementedError

    def enumerate_feasible_sets(
        self,
        network: DistributedComputingNetwork,
        on_edges: Iterable[Edge],
    ) -> List[Set[Edge]]:
        raise NotImplementedError

    @staticmethod
    def _normalized_on_edges(current_link_capacities: Mapping[Edge, float], eps: float = 1e-12) -> Set[Edge]:
        return {e for e, cap in current_link_capacities.items() if float(cap) > eps}


@dataclass
class NoInterferenceActivationPolicy(BaseActivationPolicy):
    """Activate every link that is currently ON.

    This corresponds to the special case in which the feasible activation set is
    the full power set of links.
    """

    def select_active_edges(
        self,
        network: DistributedComputingNetwork,
        q_link: Mapping[Edge, float],
        current_link_capacities: Mapping[Edge, float],
        physical_backlog: Optional[Mapping[Edge, float]] = None,
    ) -> Set[Edge]:
        return self._normalized_on_edges(current_link_capacities)

    def enumerate_feasible_sets(
        self,
        network: DistributedComputingNetwork,
        on_edges: Iterable[Edge],
    ) -> List[Set[Edge]]:
        return [set(on_edges)]


@dataclass
class EnumeratedActivationPolicy(BaseActivationPolicy):
    """General feasible activation model specified by a static family of edge sets."""

    feasible_sets: Sequence[Iterable[Edge]]
    _normalized_sets: List[Set[Edge]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._normalized_sets = [{(str(u), str(v)) for (u, v) in edges} for edges in self.feasible_sets]
        if set() not in self._normalized_sets:
            self._normalized_sets.insert(0, set())

    def select_active_edges(
        self,
        network: DistributedComputingNetwork,
        q_link: Mapping[Edge, float],
        current_link_capacities: Mapping[Edge, float],
        physical_backlog: Optional[Mapping[Edge, float]] = None,
    ) -> Set[Edge]:
        on_edges = self._normalized_on_edges(current_link_capacities)
        best_edges: Set[Edge] = set()
        virtual = _integer_objective(on_edges, q_link, current_link_capacities)
        physical = _integer_objective(on_edges, physical_backlog or {}, current_link_capacities)
        best_score = (-1, -1, -1)
        for candidate in self._normalized_sets:
            if not candidate.issubset(on_edges):
                continue
            score = (sum(virtual[e] for e in candidate),
                     sum(physical[e] for e in candidate), len(candidate))
            if score > best_score:
                best_edges = set(candidate)
                best_score = score
        return best_edges

    def enumerate_feasible_sets(
        self,
        network: DistributedComputingNetwork,
        on_edges: Iterable[Edge],
    ) -> List[Set[Edge]]:
        on = set(on_edges)
        feasible = [set(candidate) for candidate in self._normalized_sets if set(candidate).issubset(on)]
        if not feasible:
            return [set()]
        return feasible


@dataclass
class PrimaryInterferenceActivationPolicy(BaseActivationPolicy):
    """Primary-interference scheduler based on max-weight matching over ON links.

    The feasible activation rule is
        sum_out(u) + sum_in(u) <= 1,
    i.e., each node may participate in at most one transmission per slot.
    """

    def select_active_edges(
        self,
        network: DistributedComputingNetwork,
        q_link: Mapping[Edge, float],
        current_link_capacities: Mapping[Edge, float],
        physical_backlog: Optional[Mapping[Edge, float]] = None,
    ) -> Set[Edge]:
        on_edges = self._normalized_on_edges(current_link_capacities)
        if not on_edges:
            return set()

        virtual = _integer_objective(on_edges, q_link, current_link_capacities)
        physical = _integer_objective(on_edges, physical_backlog or {}, current_link_capacities)
        # A one-unit primary gain dominates the TOTAL possible secondary
        # weight. Cardinality is a third objective, only on exact double ties.
        # Integer blossom therefore solves the lexicographic problem exactly.
        secondary_base = sum(physical.values()) + 1
        cardinality_base = len(on_edges) + 1
        pair_best_directed: Dict[frozenset[NodeId], Tuple[Edge, int]] = {}
        for edge in sorted(on_edges):
            u, v = edge
            pair = frozenset((u, v))
            weight = (virtual[edge] * secondary_base + physical[edge]) * cardinality_base + 1
            best = pair_best_directed.get(pair)
            if best is None or weight > best[1]:
                pair_best_directed[pair] = (edge, weight)

        graph = nx.Graph()
        graph.add_nodes_from(network.nodes_all())
        for pair, (edge, weight) in pair_best_directed.items():
            u, v = edge
            graph.add_edge(u, v, weight=weight)

        # We need the true max-weight matching induced by the queue weights.
        # ``maxcardinality=True`` would incorrectly prioritize the number of
        # activated edges over their total weight and can starve positive-weight
        # edges by replacing them with multiple zero-weight edges.
        matching = nx.algorithms.matching.max_weight_matching(graph, maxcardinality=False, weight="weight")
        active: Set[Edge] = set()
        for u, v in matching:
            pair = frozenset((str(u), str(v)))
            best = pair_best_directed.get(pair)
            if best is None:
                continue
            edge, weight = best
            active.add(edge)
        return active

    def enumerate_feasible_sets(
        self,
        network: DistributedComputingNetwork,
        on_edges: Iterable[Edge],
    ) -> List[Set[Edge]]:
        edges = list({(str(u), str(v)) for (u, v) in on_edges})
        feasible: List[Set[Edge]] = [set()]
        if not edges:
            return feasible

        # Small-graph exact enumeration intended for boundary-validation use.
        for r in range(1, len(edges) + 1):
            for subset in combinations(edges, r):
                used_nodes: Set[NodeId] = set()
                ok = True
                for u, v in subset:
                    if u in used_nodes or v in used_nodes:
                        ok = False
                        break
                    used_nodes.add(u)
                    used_nodes.add(v)
                if ok:
                    feasible.append(set(subset))
        return feasible


ACTIVATION_POLICY_REGISTRY = {
    "none": NoInterferenceActivationPolicy,
    "all_on": NoInterferenceActivationPolicy,
    "primary": PrimaryInterferenceActivationPolicy,
}


def build_activation_policy(
    name: str,
    feasible_sets: Optional[Sequence[Iterable[Edge]]] = None,
) -> BaseActivationPolicy:
    key = str(name).strip().lower()
    if key in {"enumerated", "custom"}:
        if feasible_sets is None:
            raise ValueError("feasible_sets must be provided for the enumerated activation policy")
        return EnumeratedActivationPolicy(feasible_sets=feasible_sets)
    if key not in ACTIVATION_POLICY_REGISTRY:
        raise ValueError(f"unknown activation policy: {name}")
    return ACTIVATION_POLICY_REGISTRY[key]()
