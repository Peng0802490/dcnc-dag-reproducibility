from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple

import networkx as nx

from .models import DistributedComputingNetwork, Edge, NodeId


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
    ) -> Set[Edge]:
        on_edges = self._normalized_on_edges(current_link_capacities)
        best_edges: Set[Edge] = set()
        best_weight = -1.0
        best_size = -1
        for candidate in self._normalized_sets:
            if not candidate.issubset(on_edges):
                continue
            weight = sum(float(q_link.get(e, 0.0)) * float(current_link_capacities.get(e, 0.0)) for e in candidate)
            size = len(candidate)
            if weight > best_weight + 1e-12 or (abs(weight - best_weight) <= 1e-12 and size > best_size):
                best_edges = set(candidate)
                best_weight = weight
                best_size = size
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
    ) -> Set[Edge]:
        on_edges = self._normalized_on_edges(current_link_capacities)
        if not on_edges:
            return set()

        pair_best_directed: Dict[frozenset[NodeId], Tuple[Edge, float]] = {}
        for edge in on_edges:
            u, v = edge
            pair = frozenset((u, v))
            weight = float(q_link.get(edge, 0.0)) * float(current_link_capacities.get(edge, 0.0))
            best = pair_best_directed.get(pair)
            if best is None or weight > best[1] + 1e-12:
                pair_best_directed[pair] = (edge, weight)

        graph = nx.Graph()
        graph.add_nodes_from(network.nodes_all())
        for pair, (edge, weight) in pair_best_directed.items():
            u, v = tuple(pair)
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
