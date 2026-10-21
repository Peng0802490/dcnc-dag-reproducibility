from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from .inputs import CONFIG_ROOT, resolve_config_path
from .models import Commodity, DistributedComputingNetwork, ServiceDAG

ROOT = Path(__file__).resolve().parents[2]
LEGACY_ROOT = CONFIG_ROOT


def load_config(config_name: str | Path) -> tuple[DistributedComputingNetwork, list[Commodity]]:
    config_path = resolve_config_path(config_name)
    with config_path.open("r", encoding="utf-8") as f:
        cfg = json.load(f)
    network = DistributedComputingNetwork.from_json(config_path.parent / cfg["network"]["file"])
    commodities: list[Commodity] = []
    for idx, scfg in enumerate(cfg["service_dags"]):
        dag = ServiceDAG.from_json(config_path.parent / scfg["file"])
        commodities.append(
            Commodity(
                name=scfg.get("name", f"commodity_{idx}"),
                service_dag=dag,
                src_nodes={str(k): str(v) for k, v in scfg.get("sources", {}).items()},
                dst_nodes={str(k): str(v) for k, v in scfg.get("sinks", {}).items()},
                allowed={str(k): [str(u) for u in v] for k, v in (scfg.get("allowed") or {}).items()},
            )
        )
    restrict_to_allowed_compute_nodes(network, commodities)
    return network, commodities


def load_legacy_config(config_name: str | Path) -> tuple[DistributedComputingNetwork, list[Commodity]]:
    """Compatibility entry point for configurations shipped before v0.1.1."""
    return load_config(config_name)


def restrict_to_allowed_compute_nodes(
    network: DistributedComputingNetwork,
    commodities: Sequence[Commodity],
) -> DistributedComputingNetwork:
    """Project a legacy topology onto the compute-node subset used by the workloads.

    If every service function in every commodity has an explicit allowed-node list, nodes
    outside the union of these lists are treated as pure forwarding nodes by setting their
    role to ``FORWARD`` and their computation capacity to zero. This keeps the routing
    topology unchanged while making the edge-experiment assumption about central compute
    nodes explicit in the simulator state.
    """
    if not commodities:
        return network
    all_explicit = all(set(c.service_dag.nodes_all()).issubset(set(c.allowed.keys())) for c in commodities)
    if not all_explicit:
        return network
    compute_nodes = {u for c in commodities for func in c.service_dag.nodes_all() for u in c.allowed_nodes(network, func)}
    for node in network.nodes_all():
        if node in compute_nodes:
            network.node_roles[node] = "COMPUTE"
        else:
            network.node_roles[node] = "FORWARD"
            network.node_capacities[node] = 0.0
    return network


def make_grid_boundary_case() -> tuple[DistributedComputingNetwork, Commodity, dict[tuple[str, str], float]]:
    net = DistributedComputingNetwork(network_id="grid_2x3")
    for nid in ["v1", "v2", "v3", "v4", "v5", "v6"]:
        net.node_roles[nid] = "COMPUTE"
        net.node_capacities[nid] = 0.0
        net.out_adj.setdefault(nid, set())
        net.in_adj.setdefault(nid, set())
    # compute capacities on eligible nodes
    net.node_capacities.update({"v2": 2.0, "v5": 2.0, "v3": 1.5, "v6": 1.5})
    edges = [
        ("v1", "v2"), ("v2", "v3"),
        ("v4", "v5"), ("v5", "v6"),
        ("v1", "v4"), ("v2", "v5"), ("v3", "v6"),
        ("v4", "v1"), ("v5", "v2"), ("v6", "v3"),
        ("v2", "v1"), ("v3", "v2"),
        ("v5", "v4"), ("v6", "v5"),
    ]
    for e in edges:
        net.edge_capacities[e] = 1.0
        net.out_adj[e[0]].add(e[1])
        net.in_adj[e[1]].add(e[0])
    net.validate()

    dag = ServiceDAG(service_chain_id="grid_boundary_dag")
    nodes = {
        "A": ("source", 0.2, 1.0, None),
        "B": ("source", 0.2, 1.0, None),
        "C": ("function", 0.6, None, None),
        "D": ("sink", 0.2, None, 0.7),
        "E": ("sink", 0.2, None, 0.7),
    }
    for nid, (ntype, r, xin, xout) in nodes.items():
        dag.node_types[nid] = ntype
        dag.node_r[nid] = r
        if xin is not None:
            dag.node_in[nid] = xin
        if xout is not None:
            dag.node_out[nid] = xout
        dag.out_adj.setdefault(nid, set())
        dag.in_adj.setdefault(nid, set())
    for u, v, xi in [("A", "C", 0.8), ("B", "C", 0.8), ("C", "D", 0.7), ("C", "E", 0.7)]:
        dag.edge_xi[(u, v)] = xi
        dag.out_adj[u].add(v)
        dag.in_adj[v].add(u)
    dag.validate()

    commodity = Commodity(
        name="grid_boundary",
        service_dag=dag,
        src_nodes={"A": "v1", "B": "v4"},
        dst_nodes={"D": "v3", "E": "v6"},
        allowed={
            "A": ["v2", "v5"],
            "B": ["v2", "v5"],
            "C": ["v2", "v5"],
            "D": ["v3", "v6"],
            "E": ["v3", "v6"],
        },
    )
    dynamic_edges = {("v1", "v2"): 0.8, ("v4", "v5"): 0.8}
    return net, commodity, dynamic_edges


def make_three_workstation_gpu_cluster() -> DistributedComputingNetwork:
    net = DistributedComputingNetwork(network_id="gpu_cluster_3x2")
    nodes = ["ingress", "egress"] + [f"gpu{i}" for i in range(6)]
    for n in nodes:
        net.node_roles[n] = "FORWARD" if n in {"ingress", "egress"} else "COMPUTE"
        net.node_capacities[n] = 0.0 if n in {"ingress", "egress"} else 82.0
        net.out_adj.setdefault(n, set())
        net.in_adj.setdefault(n, set())
    # ingress / egress connectivity
    for gpu in [f"gpu{i}" for i in range(6)]:
        for e in [("ingress", gpu), (gpu, "egress"), (gpu, "ingress"), ("egress", gpu)]:
            net.edge_capacities[e] = 120.0
            net.out_adj[e[0]].add(e[1])
            net.in_adj[e[1]].add(e[0])
    # GPU interconnects
    groups = [["gpu0", "gpu1"], ["gpu2", "gpu3"], ["gpu4", "gpu5"]]
    for g in groups:
        u, v = g
        for e in [(u, v), (v, u)]:
            net.edge_capacities[e] = 600.0
            net.out_adj[e[0]].add(e[1])
            net.in_adj[e[1]].add(e[0])
    gpus = [f"gpu{i}" for i in range(6)]
    for i, u in enumerate(gpus):
        for j, v in enumerate(gpus):
            if i == j or (u, v) in net.edge_capacities:
                continue
            net.edge_capacities[(u, v)] = 60.0
            net.out_adj[u].add(v)
            net.in_adj[v].add(u)
    net.validate()
    return net


def make_cpu_gpu_cluster() -> DistributedComputingNetwork:
    net = DistributedComputingNetwork(network_id="hetero_cluster_4cpu_2gpu")
    nodes = ["ingress", "egress"] + [f"cpu{i}" for i in range(4)] + [f"gpu{i}" for i in range(2)]
    for n in nodes:
        net.node_roles[n] = "FORWARD" if n in {"ingress", "egress"} else "COMPUTE"
        if n.startswith("cpu"):
            cap = 2.0
        elif n.startswith("gpu"):
            cap = 20.0
        else:
            cap = 0.0
        net.node_capacities[n] = cap
        net.out_adj.setdefault(n, set())
        net.in_adj.setdefault(n, set())
    devices = [n for n in nodes if n not in {"ingress", "egress"}]
    for dev in devices:
        for e in [("ingress", dev), (dev, "egress"), (dev, "ingress"), ("egress", dev)]:
            net.edge_capacities[e] = 60.0
            net.out_adj[e[0]].add(e[1])
            net.in_adj[e[1]].add(e[0])
    for u in devices:
        for v in devices:
            if u == v:
                continue
            net.edge_capacities[(u, v)] = 60.0
            net.out_adj[u].add(v)
            net.in_adj[v].add(u)
    net.validate()
    return net


def _new_dag(dag_id: str) -> ServiceDAG:
    return ServiceDAG(service_chain_id=dag_id)


def make_mixtral_workload(num_layers: int = 8) -> Commodity:
    dag = _new_dag("mixtral_macro")
    prev = None
    for i in range(num_layers):
        attn = f"attn_{i}"
        exp1 = f"expertA_{i}"
        exp2 = f"expertB_{i}"
        merge = f"merge_{i}"
        if i == 0:
            dag.node_types[attn] = "source"
            dag.node_in[attn] = 1.0
        else:
            dag.node_types[attn] = "function"
        dag.node_r[attn] = 2.2
        dag.node_types[exp1] = "function"
        dag.node_types[exp2] = "function"
        dag.node_r[exp1] = 1.45
        dag.node_r[exp2] = 1.45
        dag.node_types[merge] = "sink" if i == num_layers - 1 else "function"
        dag.node_r[merge] = 0.2
        if i == num_layers - 1:
            dag.node_out[merge] = 1.0
        for n in [attn, exp1, exp2, merge]:
            dag.out_adj.setdefault(n, set())
            dag.in_adj.setdefault(n, set())
        if prev is not None:
            dag.edge_xi[(prev, attn)] = 1.0
            dag.out_adj[prev].add(attn)
            dag.in_adj[attn].add(prev)
        for u, v, xi in [(attn, exp1, 0.5), (attn, exp2, 0.5), (exp1, merge, 0.5), (exp2, merge, 0.5)]:
            dag.edge_xi[(u, v)] = xi
            dag.out_adj[u].add(v)
            dag.in_adj[v].add(u)
        prev = merge
    dag.validate()
    gpus = [f"gpu{i}" for i in range(6)]
    allowed = {n: gpus for n in dag.nodes_all()}
    return Commodity(
        name="mixtral_macro",
        service_dag=dag,
        src_nodes={dag.sources()[0]: "ingress"},
        dst_nodes={dag.sinks()[0]: "egress"},
        allowed=allowed,
    )


def make_llama_maverick_workload(num_layers: int = 10) -> Commodity:
    dag = _new_dag("llama4_maverick_macro")
    prev = None
    sink_node = None
    for i in range(num_layers):
        attn = f"attn_{i}"
        ffn = f"ffn_{i}"
        if i % 2 == 1:
            shared = f"shared_{i}"
            expert = f"expert_{i}"
        else:
            shared = None
            expert = None
        if i == 0:
            dag.node_types[attn] = "source"
            dag.node_in[attn] = 1.0
        else:
            dag.node_types[attn] = "function"
        dag.node_r[attn] = 2.4
        dag.node_types[ffn] = "function"
        dag.node_r[ffn] = 1.4
        for n in [attn, ffn]:
            dag.out_adj.setdefault(n, set())
            dag.in_adj.setdefault(n, set())
        if prev is not None:
            dag.edge_xi[(prev, attn)] = 1.0
            dag.out_adj[prev].add(attn)
            dag.in_adj[attn].add(prev)
        if shared is None:
            dag.edge_xi[(attn, ffn)] = 1.0
            dag.out_adj[attn].add(ffn)
            dag.in_adj[ffn].add(attn)
            prev = ffn
            sink_node = ffn
        else:
            dag.node_types[shared] = "function"
            dag.node_r[shared] = 0.7
            dag.node_types[expert] = "function"
            dag.node_r[expert] = 0.7
            dag.out_adj.setdefault(shared, set())
            dag.in_adj.setdefault(shared, set())
            dag.out_adj.setdefault(expert, set())
            dag.in_adj.setdefault(expert, set())
            for u, v, xi in [(attn, shared, 0.5), (attn, expert, 0.5), (shared, ffn, 0.5), (expert, ffn, 0.5)]:
                dag.edge_xi[(u, v)] = xi
                dag.out_adj[u].add(v)
                dag.in_adj[v].add(u)
            prev = ffn
            sink_node = ffn
    dag.node_types[sink_node] = "sink"
    dag.node_out[sink_node] = 1.0
    dag.validate()
    gpus = [f"gpu{i}" for i in range(6)]
    allowed = {n: gpus for n in dag.nodes_all()}
    return Commodity(
        name="llama4_maverick_macro",
        service_dag=dag,
        src_nodes={dag.sources()[0]: "ingress"},
        dst_nodes={dag.sinks()[0]: "egress"},
        allowed=allowed,
    )


def make_resnet50_macro_workload() -> Commodity:
    dag = _new_dag("resnet50_macro")
    prev = None
    block_id = 0
    for stage, blocks in enumerate([3, 4, 6, 3]):
        for _ in range(blocks):
            inp = f"b{block_id}_in"
            c1 = f"b{block_id}_c1"
            c2 = f"b{block_id}_c2"
            add = f"b{block_id}_add"
            dag.node_types[inp] = "source" if prev is None else "function"
            if prev is None:
                dag.node_in[inp] = 1.0
            dag.node_r[inp] = 0.2
            dag.node_types[c1] = "function"
            dag.node_types[c2] = "function"
            dag.node_types[add] = "function"
            dag.node_r[c1] = 0.8
            dag.node_r[c2] = 0.8
            dag.node_r[add] = 0.2
            for n in [inp, c1, c2, add]:
                dag.out_adj.setdefault(n, set())
                dag.in_adj.setdefault(n, set())
            if prev is not None:
                dag.edge_xi[(prev, inp)] = 1.0
                dag.out_adj[prev].add(inp)
                dag.in_adj[inp].add(prev)
            for u, v, xi in [(inp, c1, 1.0), (c1, c2, 1.0), (c2, add, 1.0), (inp, add, 1.0)]:
                dag.edge_xi[(u, v)] = xi
                dag.out_adj[u].add(v)
                dag.in_adj[v].add(u)
            prev = add
            block_id += 1
    dag.node_types[prev] = "sink"
    dag.node_out[prev] = 1.0
    dag.validate()
    devices = [f"cpu{i}" for i in range(4)] + [f"gpu{i}" for i in range(2)]
    allowed = {n: devices for n in dag.nodes_all()}
    return Commodity(
        name="resnet50_macro",
        service_dag=dag,
        src_nodes={dag.sources()[0]: "ingress"},
        dst_nodes={dag.sinks()[0]: "egress"},
        allowed=allowed,
    )


def make_inception_v3_macro_workload(num_modules: int = 8) -> Commodity:
    dag = _new_dag("inception_v3_macro")
    prev = None
    for i in range(num_modules):
        stem = f"m{i}_stem"
        b1 = f"m{i}_b1"
        b2 = f"m{i}_b2"
        b3 = f"m{i}_b3"
        concat = f"m{i}_concat"
        dag.node_types[stem] = "source" if prev is None else "function"
        if prev is None:
            dag.node_in[stem] = 1.0
        dag.node_r[stem] = 0.3
        for n in [b1, b2, b3]:
            dag.node_types[n] = "function"
            dag.node_r[n] = 0.6
        dag.node_types[concat] = "function"
        dag.node_r[concat] = 0.3
        for n in [stem, b1, b2, b3, concat]:
            dag.out_adj.setdefault(n, set())
            dag.in_adj.setdefault(n, set())
        if prev is not None:
            dag.edge_xi[(prev, stem)] = 1.0
            dag.out_adj[prev].add(stem)
            dag.in_adj[stem].add(prev)
        for u, v, xi in [(stem, b1, 0.34), (stem, b2, 0.33), (stem, b3, 0.33), (b1, concat, 0.34), (b2, concat, 0.33), (b3, concat, 0.33)]:
            dag.edge_xi[(u, v)] = xi
            dag.out_adj[u].add(v)
            dag.in_adj[v].add(u)
        prev = concat
    dag.node_types[prev] = "sink"
    dag.node_out[prev] = 1.0
    dag.validate()
    devices = [f"cpu{i}" for i in range(4)] + [f"gpu{i}" for i in range(2)]
    allowed = {n: devices for n in dag.nodes_all()}
    return Commodity(
        name="inception_v3_macro",
        service_dag=dag,
        src_nodes={dag.sources()[0]: "ingress"},
        dst_nodes={dag.sinks()[0]: "egress"},
        allowed=allowed,
    )


def make_fifo_counterexample() -> tuple[DistributedComputingNetwork, Commodity, dict[str, str]]:
    net = DistributedComputingNetwork(network_id="fifo_counterexample")
    for nid in ["u1", "v1"]:
        net.node_roles[nid] = "COMPUTE"
        net.node_capacities[nid] = 1.0
        net.out_adj.setdefault(nid, set())
        net.in_adj.setdefault(nid, set())
    for e in [("u1", "v1"), ("v1", "u1")]:
        net.edge_capacities[e] = 1.0
        net.out_adj[e[0]].add(e[1])
        net.in_adj[e[1]].add(e[0])
    net.validate()

    dag = ServiceDAG(service_chain_id="fifo_chain")
    specs = {
        "A": ("source", 0.01, 1.0, None),
        "B": ("function", 0.99, None, None),
        "C": ("function", 0.01, None, None),
        "E": ("function", 0.01, None, None),
        "F": ("function", 0.01, None, None),
        "G": ("sink", 0.99, None, 1.0),
    }
    for n, (tp, r, xin, xout) in specs.items():
        dag.node_types[n] = tp
        dag.node_r[n] = r
        if xin is not None:
            dag.node_in[n] = xin
        if xout is not None:
            dag.node_out[n] = xout
        dag.out_adj.setdefault(n, set())
        dag.in_adj.setdefault(n, set())
    edge_specs = [("A", "B", 0.0), ("B", "C", 1.0), ("C", "E", 1.0), ("E", "F", 1.0), ("F", "G", 0.0)]
    for u, v, xi in edge_specs:
        dag.edge_xi[(u, v)] = xi
        dag.out_adj[u].add(v)
        dag.in_adj[v].add(u)
    dag.validate()

    commodity = Commodity(
        name="fifo_chain",
        service_dag=dag,
        src_nodes={"A": "u1"},
        dst_nodes={"G": "u1"},
        allowed={n: ["u1", "v1"] for n in dag.nodes_all()},
    )
    fixed_assign = {"A": "u1", "B": "v1", "C": "v1", "E": "v1", "F": "v1", "G": "u1"}
    return net, commodity, fixed_assign
