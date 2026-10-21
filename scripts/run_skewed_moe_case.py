from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import pandas as pd

from dcnc_sim.interference import build_activation_policy
from dcnc_sim.mapping import (
    DynVMPBridgeSolver,
    LeastUsedReplicaSolver,
    QueueAwareGreedySolver,
    RoundRobinReplicaSolver,
)
from dcnc_sim.models import Commodity, DistributedComputingNetwork, ServiceDAG
from dcnc_sim.simulator import CommodityConfig, DCNCSimulator
from dcnc_sim.wireless import AlwaysOnProcess

from common import build_run_logger, close_logger, ensure_dir, save_dataframe


POLICY_ALIASES = {
    "DCNC-DAG-H": "DCNC-DAG-H",
    "DCNC-DAG": "DCNC-DAG-H",
    "Lazarus": "Lazarus-style",
    "Lazarus-style": "Lazarus-style",
    "FlexMoE": "FlexMoE-style",
    "FlexMoE-style": "FlexMoE-style",
}

WORKLOADS = {
    "mixtral_skewed_pr_multitenant": "mixtral",
    "llama_skewed_pr_multitenant": "llama",
}

GPU_NODES = [f"gpu{i}" for i in range(8)]
SERVER0 = {"gpu0", "gpu1", "gpu2", "gpu3"}
SERVER1 = {"gpu4", "gpu5", "gpu6", "gpu7"}

# Partial replication sets.  These are intentionally overlapping rather than
# disjoint: each expert group has multiple candidate GPUs, and some GPUs host
# more than one expert family.  This keeps the comparison fair while creating
# realistic local bottlenecks.
EXPERT_ALLOWED = {
    "A": ["gpu0", "gpu1", "gpu4"],
    "B": ["gpu1", "gpu2", "gpu5"],
    "C": ["gpu3", "gpu4", "gpu6", "gpu7"],
}


def add_directed_edge(net: DistributedComputingNetwork, u: str, v: str, cap: float) -> None:
    net.edge_capacities[(u, v)] = float(cap)
    net.out_adj.setdefault(u, set()).add(v)
    net.in_adj.setdefault(v, set()).add(u)
    net.out_adj.setdefault(v, set())
    net.in_adj.setdefault(u, set())


def make_heterogeneous_two_server_gpu_cluster() -> DistributedComputingNetwork:
    """Two-server GPU cluster with heterogeneous compute and non-uniform links.

    This models a realistic MoE serving substrate where not all GPUs have the
    same effective service rate and cross-server communication is slower than
    intra-server communication.  The topology is still fully connected, so no
    policy is prevented from routing between any pair of GPUs.
    """
    net = DistributedComputingNetwork(
        network_id="hetero_moe_cluster_2x4",
        description="Two-server 8-GPU heterogeneous MoE serving cluster with slower cross-server links.",
    )
    nodes = ["ingress", "egress"] + GPU_NODES
    capacities = {
        "gpu0": 82.0,
        "gpu1": 82.0,
        "gpu2": 62.0,
        "gpu3": 62.0,
        "gpu4": 82.0,
        "gpu5": 82.0,
        "gpu6": 45.0,
        "gpu7": 45.0,
    }
    for n in nodes:
        net.node_roles[n] = "FORWARD" if n in {"ingress", "egress"} else "COMPUTE"
        net.node_capacities[n] = 0.0 if n in {"ingress", "egress"} else capacities[n]
        net.out_adj.setdefault(n, set())
        net.in_adj.setdefault(n, set())

    # Ingress/egress fan-in/fan-out links.
    for g in GPU_NODES:
        for u, v in [("ingress", g), (g, "ingress"), (g, "egress"), ("egress", g)]:
            add_directed_edge(net, u, v, 120.0)

    # GPU interconnect.  Same-server links are faster; cross-server links are
    # slower but still feasible.  This captures NVLink/PCIe vs inter-server IB/Ethernet.
    for u in GPU_NODES:
        for v in GPU_NODES:
            if u == v:
                continue
            same_server = (u in SERVER0 and v in SERVER0) or (u in SERVER1 and v in SERVER1)
            cap = 420.0 if same_server else 55.0
            add_directed_edge(net, u, v, cap)

    net.validate()
    return net


def _new_dag(dag_id: str) -> ServiceDAG:
    return ServiceDAG(service_chain_id=dag_id)


def _add_node(dag: ServiceDAG, node: str, node_type: str, r: float, x_in: float | None = None, x_out: float | None = None) -> None:
    dag.node_types[node] = node_type
    dag.node_r[node] = float(r)
    if x_in is not None:
        dag.node_in[node] = float(x_in)
    if x_out is not None:
        dag.node_out[node] = float(x_out)
    dag.out_adj.setdefault(node, set())
    dag.in_adj.setdefault(node, set())


def _add_dag_edge(dag: ServiceDAG, u: str, v: str, xi: float) -> None:
    dag.edge_xi[(u, v)] = float(xi)
    dag.out_adj.setdefault(u, set()).add(v)
    dag.in_adj.setdefault(v, set()).add(u)
    dag.out_adj.setdefault(v, set())
    dag.in_adj.setdefault(u, set())


def _branch_weights(hot: str, warm: str) -> Dict[str, float]:
    """Moderate domain skew: one hot expert family, one warm, one cold."""
    base = {"A": 0.12, "B": 0.12, "C": 0.12}
    base[hot] = 0.70
    base[warm] = 0.18
    # values sum to one.  They are also used to scale expert compute load.
    return base


def make_skewed_moe_dag(dag_id: str, *, num_layers: int, hot: str, warm: str, model_scale: float) -> ServiceDAG:
    """Macro MoE DAG with domain-skewed expert traffic.

    Each layer has one router/attention node, three expert-family branches, and
    one merge node.  Branch xi and expert compute demand are scaled by the
    expert fraction.  This is a macro abstraction of a token batch where more
    tokens are routed to the hot expert group.
    """
    dag = _new_dag(dag_id)
    prev_merge: str | None = None
    weights = _branch_weights(hot, warm)
    for i in range(num_layers):
        router = f"router_{i}"
        merge = f"merge_{i}"
        expert_nodes = {k: f"expert{k}_{i}" for k in ["A", "B", "C"]}

        _add_node(
            dag,
            router,
            "source" if i == 0 else "function",
            r=1.25 * model_scale,
            x_in=1.0 if i == 0 else None,
        )
        for k, node in expert_nodes.items():
            # A macro expert node represents all tokens routed to that expert
            # family in this layer.  Compute demand scales with token fraction.
            _add_node(dag, node, "function", r=(0.55 + 3.25 * weights[k]) * model_scale)
        _add_node(
            dag,
            merge,
            "sink" if i == num_layers - 1 else "function",
            r=0.28 * model_scale,
            x_out=1.0 if i == num_layers - 1 else None,
        )

        if prev_merge is not None:
            _add_dag_edge(dag, prev_merge, router, 1.0)
        for k, node in expert_nodes.items():
            # Branch traffic equals the fraction of tokens routed to the expert group.
            _add_dag_edge(dag, router, node, weights[k])
            _add_dag_edge(dag, node, merge, weights[k])
        prev_merge = merge

    dag.validate()
    return dag


def allowed_for_dag(dag: ServiceDAG) -> Dict[str, List[str]]:
    allowed: Dict[str, List[str]] = {}
    for n in dag.nodes_all():
        if n.startswith("expertA"):
            allowed[n] = list(EXPERT_ALLOWED["A"])
        elif n.startswith("expertB"):
            allowed[n] = list(EXPERT_ALLOWED["B"])
        elif n.startswith("expertC"):
            allowed[n] = list(EXPERT_ALLOWED["C"])
        else:
            allowed[n] = list(GPU_NODES)
    return allowed


def make_multitenant_skewed_workload(workload: str, total_rate: float, split_a: float) -> Tuple[DistributedComputingNetwork, List[CommodityConfig], Dict[str, str]]:
    if workload not in WORKLOADS:
        raise ValueError(f"Unknown workload: {workload}. Choices: {sorted(WORKLOADS)}")
    model = WORKLOADS[workload]
    if model == "mixtral":
        num_layers = 4
        model_scale = 2.00
        # Two realistic domains with different hot expert families.  The allowed
        # sets overlap, which creates local contention without making any expert
        # single-homed.
        dag_a = make_skewed_moe_dag("mixtral_skewed_code", num_layers=num_layers, hot="A", warm="B", model_scale=model_scale)
        dag_b = make_skewed_moe_dag("mixtral_skewed_chat", num_layers=num_layers, hot="B", warm="A", model_scale=model_scale)
    else:
        num_layers = 5
        model_scale = 1.84
        dag_a = make_skewed_moe_dag("llama_skewed_code", num_layers=num_layers, hot="B", warm="C", model_scale=model_scale)
        dag_b = make_skewed_moe_dag("llama_skewed_chat", num_layers=num_layers, hot="C", warm="B", model_scale=model_scale)

    net = make_heterogeneous_two_server_gpu_cluster()
    commodity_a = Commodity(
        name=f"{workload}_tenant_code",
        service_dag=dag_a,
        src_nodes={dag_a.sources()[0]: "ingress"},
        dst_nodes={dag_a.sinks()[0]: "egress"},
        allowed=allowed_for_dag(dag_a),
    )
    commodity_b = Commodity(
        name=f"{workload}_tenant_chat",
        service_dag=dag_b,
        src_nodes={dag_b.sources()[0]: "ingress"},
        dst_nodes={dag_b.sinks()[0]: "egress"},
        allowed=allowed_for_dag(dag_b),
    )
    metadata = {
        "model": model,
        "tenant_a_rate_fraction": f"{split_a:.3f}",
        "tenant_b_rate_fraction": f"{1.0 - split_a:.3f}",
        "tenant_a_hot_expert": "A" if model == "mixtral" else "B",
        "tenant_b_hot_expert": "B" if model == "mixtral" else "C",
        "cluster": net.summary(),
        "gpu_capacities": json.dumps({g: net.node_capacity(g) for g in GPU_NODES}, sort_keys=True),
        "expert_allowed": json.dumps(EXPERT_ALLOWED, sort_keys=True),
    }
    return net, [commodity_a, commodity_b], metadata


def build_solver(policy: str, network, seed: int, logger, dcnc_solver: str, dynvmp_cmd: str | None):
    if policy == "DCNC-DAG-H":
        if dcnc_solver == "dynvmp_bridge":
            return DynVMPBridgeSolver(
                network,
                bridge_cmd=shlex.split(dynvmp_cmd) if dynvmp_cmd else None,
                seed=100000 + seed,
                logger=logger,
            )
        return QueueAwareGreedySolver(network, seed=100000 + seed, logger=logger)
    if policy == "Lazarus-style":
        return LeastUsedReplicaSolver(network, seed=200000 + seed, logger=logger)
    if policy == "FlexMoE-style":
        return RoundRobinReplicaSolver(network, seed=300000 + seed, logger=logger)
    raise ValueError(f"Unknown policy: {policy}")


def completion_fraction(delivered: int, pending: int) -> float:
    total = delivered + pending
    return float(delivered) / float(total) if total > 0 else 1.0


def main() -> None:
    ap = argparse.ArgumentParser(description="Run one skewed/partial-replication MoE serving experiment point.")
    ap.add_argument("--workload", required=True, choices=sorted(WORKLOADS.keys()))
    ap.add_argument("--policy", required=True, choices=sorted(POLICY_ALIASES.keys()))
    ap.add_argument("--rate", type=float, required=True, help="Total arrival rate across both tenants.")
    ap.add_argument("--tenant-a-fraction", type=float, default=0.60, help="Fraction of total rate assigned to tenant A.")
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--slots", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--fixed-k", type=int, default=1)
    ap.add_argument("--progress-every", type=int, default=1000)
    ap.add_argument("--interference-model", choices=["none", "primary"], default="none")
    ap.add_argument("--dcnc-solver", choices=["greedy", "dynvmp_bridge"], default="greedy")
    ap.add_argument("--dynvmp-cmd", default=None)
    args = ap.parse_args()

    policy = POLICY_ALIASES[args.policy]
    out_dir = ensure_dir(args.output_dir)
    logger, _ = build_run_logger("skewed_moe_case", out_dir, "skewed_moe_case")
    try:
        network, commodities, meta = make_multitenant_skewed_workload(args.workload, args.rate, args.tenant_a_fraction)
        activation_policy = build_activation_policy(args.interference_model)
        wireless_process = AlwaysOnProcess(network)
        solver = build_solver(policy, network, args.seed, logger, args.dcnc_solver, args.dynvmp_cmd)
        policy_fixed_k = args.fixed_k if policy == "DCNC-DAG-H" else 1

        # Share the same baseline solver object across tenants.  This is important:
        # Lazarus and FlexMoE should balance replicas globally across the serving
        # cluster, not independently per tenant.
        cfgs = [
            CommodityConfig(commodities[0], args.rate * args.tenant_a_fraction, solver),
            CommodityConfig(commodities[1], args.rate * (1.0 - args.tenant_a_fraction), solver),
        ]
        logger.info(
            "Skewed MoE start | workload=%s | policy=%s | total_rate=%.6f | tenant_rates=(%.6f, %.6f) | slots=%d | seed=%d | fixed_k=%d | network=%s",
            args.workload,
            policy,
            args.rate,
            cfgs[0].arrival_rate,
            cfgs[1].arrival_rate,
            args.slots,
            args.seed,
            policy_fixed_k,
            network.summary(),
        )
        for k, v in meta.items():
            logger.info("scenario_meta | %s=%s", k, v)

        sim = DCNCSimulator(
            network=network,
            commodity_cfgs=cfgs,
            wireless_process=wireless_process,
            total_slots=args.slots,
            seed=700000 + args.seed,
            scheduler="nto",
            activation_policy=activation_policy,
            fixed_k=policy_fixed_k,
            logger=logger,
            run_label=f"{args.workload}_{policy}_rate{args.rate:.6f}_seed{args.seed}",
            progress_every=args.progress_every,
        )
        stats = sim.run()
        row = {
            "family": "moe_skewed",
            "workload": args.workload,
            "policy": policy,
            "seed": args.seed,
            "arrival_rate": args.rate,
            "slots": args.slots,
            "tenant_a_fraction": args.tenant_a_fraction,
            "tenant_a_rate": cfgs[0].arrival_rate,
            "tenant_b_rate": cfgs[1].arrival_rate,
            "interference_model": args.interference_model,
            "fixed_k": policy_fixed_k,
            "dcnc_solver": args.dcnc_solver if policy == "DCNC-DAG-H" else "baseline",
            "avg_delay_completed": stats.avg_delay_completed,
            "avg_delay_with_penalty": stats.avg_delay_with_penalty,
            "achieved_throughput": stats.delivered_packets / float(args.slots),
            "delivered_packets": stats.delivered_packets,
            "pending_packets": stats.pending_packets,
            "completion_fraction": completion_fraction(stats.delivered_packets, stats.pending_packets),
            "routing_oracle_calls": stats.routing_oracle_calls,
            "routing_cache_hits": stats.routing_cache_hits,
            **meta,
        }
        df = pd.DataFrame([row])
        save_dataframe(df, out_dir / "ai_workload_case_result.csv")
        (out_dir / "scenario_metadata.json").write_text(
            json.dumps(
                {
                    "workload": args.workload,
                    "policy": policy,
                    "total_rate": args.rate,
                    "tenant_a_fraction": args.tenant_a_fraction,
                    "scenario": meta,
                    "commodities": [
                        {
                            "name": c.name,
                            "dag": c.service_dag.summary(),
                            "sources": c.src_nodes,
                            "sinks": c.dst_nodes,
                        }
                        for c in commodities
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        logger.info(
            "Skewed MoE done | workload=%s | policy=%s | rate=%.6f | throughput=%.6f | completed_delay=%.6f | penalty_delay=%.6f | delivered=%d | pending=%d | completion=%.6f",
            args.workload,
            policy,
            args.rate,
            row["achieved_throughput"],
            row["avg_delay_completed"],
            row["avg_delay_with_penalty"],
            stats.delivered_packets,
            stats.pending_packets,
            row["completion_fraction"],
        )
        print(df[["family", "workload", "policy", "arrival_rate", "avg_delay_completed", "avg_delay_with_penalty", "achieved_throughput", "pending_packets", "completion_fraction"]].to_string(index=False))
    finally:
        close_logger(logger)


if __name__ == "__main__":
    main()
