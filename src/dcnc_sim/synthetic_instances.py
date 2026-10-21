from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from .models import Commodity, DistributedComputingNetwork, Edge, NodeId, ServiceDAG


@dataclass(frozen=True)
class SyntheticThroughputCase:
    """Small synthetic instance used for LP-vs-DCNC throughput validation."""

    name: str
    description: str
    network: DistributedComputingNetwork
    commodity: Commodity
    dynamic_edge_p_on: Dict[Edge, float]
    default_interference_model: str = "none"


def _new_network(network_id: str) -> DistributedComputingNetwork:
    return DistributedComputingNetwork(network_id=network_id)


def _add_node(net: DistributedComputingNetwork, node_id: NodeId, role: str, capacity: float) -> None:
    node_id = str(node_id)
    net.node_roles[node_id] = str(role)
    net.node_capacities[node_id] = float(capacity)
    net.out_adj.setdefault(node_id, set())
    net.in_adj.setdefault(node_id, set())


def _add_edge(net: DistributedComputingNetwork, u: NodeId, v: NodeId, capacity: float) -> None:
    u, v = str(u), str(v)
    net.edge_capacities[(u, v)] = float(capacity)
    net.out_adj.setdefault(u, set()).add(v)
    net.in_adj.setdefault(v, set()).add(u)
    net.out_adj.setdefault(v, set())
    net.in_adj.setdefault(u, set())


def _new_dag(dag_id: str) -> ServiceDAG:
    return ServiceDAG(service_chain_id=dag_id)


def _add_dag_node(
    dag: ServiceDAG,
    node_id: NodeId,
    node_type: str,
    r: float,
    xin: float | None = None,
    xout: float | None = None,
) -> None:
    node_id = str(node_id)
    dag.node_types[node_id] = str(node_type)
    dag.node_r[node_id] = float(r)
    if xin is not None:
        dag.node_in[node_id] = float(xin)
    if xout is not None:
        dag.node_out[node_id] = float(xout)
    dag.out_adj.setdefault(node_id, set())
    dag.in_adj.setdefault(node_id, set())


def _add_dag_edge(dag: ServiceDAG, u: NodeId, v: NodeId, xi: float) -> None:
    u, v = str(u), str(v)
    dag.edge_xi[(u, v)] = float(xi)
    dag.out_adj.setdefault(u, set()).add(v)
    dag.in_adj.setdefault(v, set()).add(u)
    dag.out_adj.setdefault(v, set())
    dag.in_adj.setdefault(u, set())


def make_line_chain_case() -> SyntheticThroughputCase:
    """Two-stage chain with two interchangeable compute nodes.

    The LP optimum is mainly computation-limited. It is a useful smoke case
    because the capacity boundary is easy to interpret and the exact mapping
    enumeration stays very small.
    """

    net = _new_network("synthetic_line_chain")
    for node, role, cap in [
        ("s", "FORWARD", 0.0),
        ("u1", "COMPUTE", 2.0),
        ("u2", "COMPUTE", 2.0),
        ("d", "FORWARD", 0.0),
    ]:
        _add_node(net, node, role, cap)
    for edge in [
        ("s", "u1"),
        ("s", "u2"),
        ("u1", "u2"),
        ("u2", "u1"),
        ("u1", "d"),
        ("u2", "d"),
    ]:
        _add_edge(net, *edge, capacity=4.0)
    net.validate()

    dag = _new_dag("line_chain_dag")
    _add_dag_node(dag, "A", "source", r=1.0, xin=1.0)
    _add_dag_node(dag, "B", "sink", r=1.0, xout=1.0)
    _add_dag_edge(dag, "A", "B", xi=1.0)
    dag.validate()

    commodity = Commodity(
        name="line_chain",
        service_dag=dag,
        src_nodes={"A": "s"},
        dst_nodes={"B": "d"},
        allowed={"A": ["u1", "u2"], "B": ["u1", "u2"]},
    )
    return SyntheticThroughputCase(
        name="line_chain",
        description="Two-function service chain on two interchangeable compute nodes; always-on links, no interference.",
        network=net,
        commodity=commodity,
        dynamic_edge_p_on={},
        default_interference_model="none",
    )


def make_diamond_fork_join_case() -> SyntheticThroughputCase:
    """Fork-join DAG with a fixed merge node and two branch compute nodes."""

    net = _new_network("synthetic_diamond_fork_join")
    for node, role, cap in [
        ("s", "FORWARD", 0.0),
        ("u0", "COMPUTE", 1.4),
        ("u1", "COMPUTE", 1.1),
        ("u2", "COMPUTE", 1.1),
        ("d", "FORWARD", 0.0),
    ]:
        _add_node(net, node, role, cap)

    # Directed edges support source injection, branch distribution, merge return, and delivery.
    for edge, cap in [
        (("s", "u0"), 2.0),
        (("u0", "u1"), 1.5),
        (("u0", "u2"), 1.5),
        (("u1", "u0"), 1.5),
        (("u2", "u0"), 1.5),
        (("u0", "d"), 2.0),
        (("u1", "u2"), 1.0),
        (("u2", "u1"), 1.0),
    ]:
        _add_edge(net, edge[0], edge[1], cap)
    net.validate()

    dag = _new_dag("diamond_fork_join_dag")
    _add_dag_node(dag, "A", "source", r=0.4, xin=1.0)
    _add_dag_node(dag, "B", "function", r=1.0)
    _add_dag_node(dag, "C", "function", r=1.0)
    _add_dag_node(dag, "D", "sink", r=0.4, xout=1.0)
    for u, v in [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")]:
        _add_dag_edge(dag, u, v, xi=0.7)
    dag.validate()

    commodity = Commodity(
        name="diamond_fork_join",
        service_dag=dag,
        src_nodes={"A": "s"},
        dst_nodes={"D": "d"},
        allowed={
            "A": ["u0"],
            "B": ["u1", "u2"],
            "C": ["u1", "u2"],
            "D": ["u0"],
        },
    )
    return SyntheticThroughputCase(
        name="diamond_fork_join",
        description="Small fork-join DAG with split, merge, and scaling; always-on links, no interference.",
        network=net,
        commodity=commodity,
        dynamic_edge_p_on={},
        default_interference_model="none",
    )


def make_wireless_primary_case() -> SyntheticThroughputCase:
    """Two-hop wireless service with IID ON/OFF links and primary interference."""

    net = _new_network("synthetic_wireless_primary")
    for node, role, cap in [
        ("s", "FORWARD", 0.0),
        ("u1", "COMPUTE", 3.0),
        ("u2", "COMPUTE", 3.0),
        ("d", "FORWARD", 0.0),
    ]:
        _add_node(net, node, role, cap)
    for edge in [("s", "u1"), ("s", "u2"), ("u1", "d"), ("u2", "d")]:
        _add_edge(net, *edge, capacity=1.0)
    net.validate()

    dag = _new_dag("wireless_primary_chain_dag")
    _add_dag_node(dag, "A", "source", r=0.3, xin=1.0)
    _add_dag_node(dag, "B", "sink", r=0.3, xout=1.0)
    _add_dag_edge(dag, "A", "B", xi=1.0)
    dag.validate()

    commodity = Commodity(
        name="wireless_primary_chain",
        service_dag=dag,
        src_nodes={"A": "s"},
        dst_nodes={"B": "d"},
        allowed={"A": ["u1", "u2"], "B": ["u1", "u2"]},
    )
    dynamic = {edge: 0.85 for edge in net.edges_all()}
    return SyntheticThroughputCase(
        name="wireless_primary",
        description="Two-hop wireless chain with IID ON/OFF links and primary-interference scheduling.",
        network=net,
        commodity=commodity,
        dynamic_edge_p_on=dynamic,
        default_interference_model="primary",
    )



def make_wireless_diamond_primary_case() -> SyntheticThroughputCase:
    """Fork-join service DAG with IID ON/OFF links and primary interference.

    This is the compact end-to-end validation instance for the full setting
    considered in the paper: a general service DAG with split/merge behavior,
    time-varying wireless links, and interference-constrained activations.
    """

    net = _new_network("synthetic_wireless_diamond_primary")
    for node, role, cap in [
        ("s", "FORWARD", 0.0),
        ("uA", "COMPUTE", 2.0),
        ("uB", "COMPUTE", 1.0),
        ("uC", "COMPUTE", 1.0),
        ("uD", "COMPUTE", 2.0),
        ("d", "FORWARD", 0.0),
    ]:
        _add_node(net, node, role, cap)

    # Directed layered wireless topology:
    # s -> uA; uA splits to uB/uC; uB/uC merge at uD; uD -> d.
    # Under primary interference, links sharing a node cannot be activated in
    # the same slot, so the split and merge stages create real scheduling
    # coupling in addition to ON/OFF randomness.
    for edge in [
        ("s", "uA"),
        ("uA", "uB"),
        ("uA", "uC"),
        ("uB", "uD"),
        ("uC", "uD"),
        ("uD", "d"),
    ]:
        _add_edge(net, *edge, capacity=1.0)
    net.validate()

    dag = _new_dag("wireless_diamond_primary_dag")
    _add_dag_node(dag, "A", "source", r=0.3, xin=1.0)
    _add_dag_node(dag, "B", "function", r=0.6)
    _add_dag_node(dag, "C", "function", r=0.6)
    _add_dag_node(dag, "D", "sink", r=0.3, xout=1.0)
    for u, v in [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")]:
        _add_dag_edge(dag, u, v, xi=0.7)
    dag.validate()

    commodity = Commodity(
        name="wireless_diamond_primary",
        service_dag=dag,
        src_nodes={"A": "s"},
        dst_nodes={"D": "d"},
        allowed={
            "A": ["uA"],
            "B": ["uB", "uC"],
            "C": ["uB", "uC"],
            "D": ["uD"],
        },
    )
    dynamic = {edge: 0.85 for edge in net.edges_all()}
    return SyntheticThroughputCase(
        name="wireless_diamond_primary",
        description="Wireless fork-join service DAG with split/merge/scaling, IID ON/OFF links, and primary-interference scheduling.",
        network=net,
        commodity=commodity,
        dynamic_edge_p_on=dynamic,
        default_interference_model="primary",
    )


def get_synthetic_throughput_cases() -> Dict[str, SyntheticThroughputCase]:
    cases = [
        make_line_chain_case(),
        make_diamond_fork_join_case(),
        make_wireless_primary_case(),
        make_wireless_diamond_primary_case(),
    ]
    return {case.name: case for case in cases}


def list_synthetic_throughput_cases() -> List[str]:
    return sorted(get_synthetic_throughput_cases().keys())
