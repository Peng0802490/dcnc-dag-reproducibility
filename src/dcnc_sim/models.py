from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

NodeId = str
Edge = Tuple[NodeId, NodeId]


@dataclass(slots=True)
class DistributedComputingNetwork:
    network_id: str
    version: Optional[str] = None
    description: Optional[str] = None
    metadata: Dict = field(default_factory=dict)
    node_roles: Dict[NodeId, str] = field(default_factory=dict)
    node_capacities: Dict[NodeId, float] = field(default_factory=dict)
    edge_capacities: Dict[Edge, float] = field(default_factory=dict)
    out_adj: Dict[NodeId, Set[NodeId]] = field(default_factory=dict)
    in_adj: Dict[NodeId, Set[NodeId]] = field(default_factory=dict)

    @classmethod
    def from_json(cls, path: str | Path) -> "DistributedComputingNetwork":
        with Path(path).open("r", encoding="utf-8") as f:
            data = json.load(f)
        network_id = str(data["network_id"])
        net = cls(
            network_id=network_id,
            version=data.get("version"),
            description=data.get("description"),
            metadata=data.get("metadata") or {},
        )
        for n in data.get("nodes", []):
            nid = str(n["id"])
            role = str(n["role"])
            cap = n.get("capacity")
            net.node_roles[nid] = role
            net.node_capacities[nid] = float(cap) if cap is not None else 0.0
            net.out_adj.setdefault(nid, set())
            net.in_adj.setdefault(nid, set())
        for e in data.get("edges", []):
            u, v = str(e["from"]), str(e["to"])
            cap = float(e["capacity"])
            net.edge_capacities[(u, v)] = cap
            net.out_adj.setdefault(u, set()).add(v)
            net.in_adj.setdefault(v, set()).add(u)
            net.out_adj.setdefault(v, set())
            net.in_adj.setdefault(u, set())
        net.validate()
        return net

    def validate(self) -> None:
        for u, v in self.edge_capacities:
            if u not in self.node_roles or v not in self.node_roles:
                raise ValueError(f"edge {(u, v)} references unknown nodes")

    def nodes_all(self) -> List[NodeId]:
        return list(self.node_roles.keys())

    def edges_all(self) -> List[Edge]:
        return list(self.edge_capacities.keys())

    def delta_plus(self, node_id: NodeId) -> List[NodeId]:
        return list(self.out_adj.get(str(node_id), set()))

    def delta_minus(self, node_id: NodeId) -> List[NodeId]:
        return list(self.in_adj.get(str(node_id), set()))

    def role(self, node_id: NodeId) -> str:
        return self.node_roles[str(node_id)]

    def can_compute(self, node_id: NodeId) -> bool:
        return self.role(node_id) == "COMPUTE" and self.node_capacity(node_id) > 0.0

    def node_capacity(self, node_id: NodeId) -> float:
        return float(self.node_capacities.get(str(node_id), 0.0))

    def link_capacity(self, u: NodeId, v: NodeId) -> float:
        return float(self.edge_capacities.get((str(u), str(v)), 0.0))

    def summary(self) -> str:
        compute_nodes = sum(1 for n in self.nodes_all() if self.can_compute(n))
        return (
            f"Network[{self.network_id}] |V|={len(self.node_roles)}, |E|={len(self.edge_capacities)}, "
            f"compute_nodes={compute_nodes}"
        )


@dataclass(slots=True)
class ServiceDAG:
    service_chain_id: str
    version: Optional[str] = None
    description: Optional[str] = None
    metadata: Dict = field(default_factory=dict)
    node_types: Dict[NodeId, str] = field(default_factory=dict)
    node_r: Dict[NodeId, float] = field(default_factory=dict)
    node_in: Dict[NodeId, float] = field(default_factory=dict)
    node_out: Dict[NodeId, float] = field(default_factory=dict)
    edge_xi: Dict[Edge, float] = field(default_factory=dict)
    out_adj: Dict[NodeId, Set[NodeId]] = field(default_factory=dict)
    in_adj: Dict[NodeId, Set[NodeId]] = field(default_factory=dict)
    _topo_order: List[NodeId] = field(default_factory=list)

    @classmethod
    def from_json(cls, path: str | Path) -> "ServiceDAG":
        with Path(path).open("r", encoding="utf-8") as f:
            data = json.load(f)
        dag = cls(
            service_chain_id=str(data["service_chain_id"]),
            version=data.get("version"),
            description=data.get("description"),
            metadata=data.get("metadata") or {},
        )
        for n in data.get("nodes", []):
            nid = str(n["id"])
            dag.node_types[nid] = str(n["type"])
            dag.node_r[nid] = float(n.get("r", 0.0) or 0.0)
            if n.get("in") is not None:
                dag.node_in[nid] = float(n["in"])
            if n.get("out") is not None:
                dag.node_out[nid] = float(n["out"])
            dag.out_adj.setdefault(nid, set())
            dag.in_adj.setdefault(nid, set())
        for e in data.get("edges", []):
            u, v = str(e["from"]), str(e["to"])
            dag.edge_xi[(u, v)] = float(e["xi"])
            dag.out_adj.setdefault(u, set()).add(v)
            dag.in_adj.setdefault(v, set()).add(u)
            dag.out_adj.setdefault(v, set())
            dag.in_adj.setdefault(u, set())
        dag.validate()
        return dag

    def validate(self) -> None:
        indeg = {n: len(self.in_adj.get(n, set())) for n in self.node_types}
        queue = sorted([n for n, d in indeg.items() if d == 0])
        topo: List[NodeId] = []
        while queue:
            u = queue.pop(0)
            topo.append(u)
            for v in sorted(self.out_adj.get(u, set())):
                indeg[v] -= 1
                if indeg[v] == 0:
                    queue.append(v)
                    queue.sort()
        if len(topo) != len(self.node_types):
            raise ValueError(f"Service DAG {self.service_chain_id} contains a cycle")
        self._topo_order = topo

    def nodes_all(self) -> List[NodeId]:
        return list(self.node_types.keys())

    def edges_all(self) -> List[Edge]:
        return list(self.edge_xi.keys())

    def sources(self) -> List[NodeId]:
        return [n for n, t in self.node_types.items() if t == "source"]

    def sinks(self) -> List[NodeId]:
        return [n for n, t in self.node_types.items() if t == "sink"]

    def functions(self) -> List[NodeId]:
        return [n for n, t in self.node_types.items() if t == "function"]

    def delta_plus(self, node_id: NodeId) -> List[NodeId]:
        return list(self.out_adj.get(str(node_id), set()))

    def delta_minus(self, node_id: NodeId) -> List[NodeId]:
        return list(self.in_adj.get(str(node_id), set()))

    def topo_order(self) -> List[NodeId]:
        return list(self._topo_order)

    def xi(self, u: NodeId, v: NodeId) -> float:
        return float(self.edge_xi.get((str(u), str(v)), 0.0))

    def r(self, node_id: NodeId) -> float:
        return float(self.node_r.get(str(node_id), 0.0))

    def xi_source(self) -> Dict[NodeId, float]:
        return {n: self.node_in[n] for n in self.sources()}

    def xi_sink(self) -> Dict[NodeId, float]:
        return {n: self.node_out[n] for n in self.sinks()}

    def has_merging(self, node_id: NodeId) -> bool:
        return len(self.in_adj.get(str(node_id), set())) > 1

    def has_splitting(self, node_id: NodeId) -> bool:
        return len(self.out_adj.get(str(node_id), set())) > 1

    def summary(self) -> str:
        return (
            f"ServiceDAG[{self.service_chain_id}] |V|={len(self.node_types)}, "
            f"|E|={len(self.edge_xi)}, sources={len(self.sources())}, sinks={len(self.sinks())}"
        )


@dataclass(slots=True)
class Commodity:
    name: str
    service_dag: ServiceDAG
    src_nodes: Dict[NodeId, NodeId]
    dst_nodes: Dict[NodeId, NodeId]
    allowed: Dict[NodeId, List[NodeId]] = field(default_factory=dict)

    def allowed_nodes(self, network: DistributedComputingNetwork, func_id: NodeId) -> List[NodeId]:
        func_id = str(func_id)
        if func_id in self.allowed and self.allowed[func_id]:
            return [str(u) for u in self.allowed[func_id]]
        return [u for u in network.nodes_all() if network.can_compute(u)]

    def copy(self) -> "Commodity":
        return Commodity(
            name=self.name,
            service_dag=self.service_dag,
            src_nodes=dict(self.src_nodes),
            dst_nodes=dict(self.dst_nodes),
            allowed={k: list(v) for k, v in self.allowed.items()},
        )
