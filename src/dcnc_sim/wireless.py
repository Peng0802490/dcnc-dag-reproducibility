from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Tuple

import numpy as np

from .models import DistributedComputingNetwork, Edge


@dataclass
class BaseLinkStateProcess:
    network: DistributedComputingNetwork

    def sample_capacities(self, slot: int) -> Dict[Edge, float]:
        raise NotImplementedError

    def average_capacities(self) -> Dict[Edge, float]:
        raise NotImplementedError


@dataclass
class AlwaysOnProcess(BaseLinkStateProcess):
    def sample_capacities(self, slot: int) -> Dict[Edge, float]:
        return {e: self.network.link_capacity(*e) for e in self.network.edges_all()}

    def average_capacities(self) -> Dict[Edge, float]:
        return {e: self.network.link_capacity(*e) for e in self.network.edges_all()}


@dataclass
class IIDOnOffProcess(BaseLinkStateProcess):
    dynamic_edge_p_on: Mapping[Edge, float]
    seed: int = 1
    _rng: np.random.Generator = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.dynamic_edge_p_on = {(str(u), str(v)): float(p) for (u, v), p in self.dynamic_edge_p_on.items()}
        self._rng = np.random.default_rng(self.seed)

    def sample_capacities(self, slot: int) -> Dict[Edge, float]:
        capacities: Dict[Edge, float] = {}
        for e in self.network.edges_all():
            base = self.network.link_capacity(*e)
            p_on = self.dynamic_edge_p_on.get(e, 1.0)
            on = bool(self._rng.random() < p_on)
            capacities[e] = base if on else 0.0
        return capacities

    def average_capacities(self) -> Dict[Edge, float]:
        return {
            e: self.network.link_capacity(*e) * self.dynamic_edge_p_on.get(e, 1.0)
            for e in self.network.edges_all()
        }


def auto_source_adjacent_dynamic_edges(
    network: DistributedComputingNetwork,
    source_nodes: list[str],
    p_on: float,
) -> Dict[Edge, float]:
    dynamic: Dict[Edge, float] = {}
    source_set = {str(s) for s in source_nodes}
    for u, v in network.edges_all():
        if u in source_set:
            dynamic[(u, v)] = float(p_on)
    return dynamic
