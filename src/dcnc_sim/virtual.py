from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional

from .mapping import ValidMapping
from .models import Commodity, DistributedComputingNetwork, Edge, NodeId, ServiceDAG


@dataclass
class VirtualQueues:
    network: DistributedComputingNetwork
    avg_link_capacities: Mapping[Edge, float]
    q_link: Dict[Edge, float] = field(default_factory=dict)
    q_node: Dict[NodeId, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.q_link = {e: 0.0 for e in self.network.edges_all()}
        self.q_node = {u: 0.0 for u in self.network.nodes_all()}

    def snapshot_link(self) -> Dict[Edge, float]:
        return dict(self.q_link)

    def snapshot_node(self) -> Dict[NodeId, float]:
        return dict(self.q_node)

    def add_arrivals_of_mapping(
        self,
        dag: ServiceDAG,
        commodity: Commodity,
        mapping: ValidMapping,
        count_units: int,
    ) -> None:
        count = float(int(count_units))
        xi_s = dag.xi_source()
        xi_d = dag.xi_sink()
        for a, u in mapping.assign.items():
            self.q_node[u] += count * dag.r(a)
        for a in dag.sources():
            inc = count * xi_s[a]
            for e in mapping.path_for((("S", a), a)):
                self.q_link[e] += inc
        for a, b in dag.edges_all():
            inc = count * dag.xi(a, b)
            for e in mapping.path_for((a, b)):
                self.q_link[e] += inc
        for a in dag.sinks():
            inc = count * xi_d[a]
            for e in mapping.path_for((a, ("D", a))):
                self.q_link[e] += inc

    def serve_one_slot(
        self,
        link_service: Optional[Mapping[Edge, float]] = None,
        node_service: Optional[Mapping[NodeId, float]] = None,
    ) -> None:
        r"""Apply one slot of virtual service.

        The exact DCNC-DAG update uses the *actual activated* link service
        :math:`\mu_{uv}(t)s_{uv}(t)` in the virtual queues. For backward
        compatibility, ``link_service=None`` falls back to the state-averaged
        capacities that were used by the earlier simplified implementation.
        """

        link_service = link_service or self.avg_link_capacities
        if node_service is None:
            node_service = {u: self.network.node_capacity(u) for u in self.network.nodes_all()}

        for e in self.network.edges_all():
            self.q_link[e] = max(0.0, self.q_link[e] - float(link_service.get(e, 0.0)))
        for u in self.network.nodes_all():
            self.q_node[u] = max(0.0, self.q_node[u] - float(node_service.get(u, 0.0)))

    def total_link_backlog(self) -> float:
        return sum(self.q_link.values())

    def total_node_backlog(self) -> float:
        return sum(self.q_node.values())
