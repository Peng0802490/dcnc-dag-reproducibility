#!/usr/bin/env python3
"""Run one skewed MoE serving experiment point on the Milan wireless MEC substrate.

Substrate replacement only: the MoE service DAGs, workloads, expert-demand skew,
tenant split, policies and metric definitions are imported unchanged from
run_skewed_moe_case.  Only the network, the candidate sets, the endpoints,
the wireless ON/OFF process and the interference model differ.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from collections import defaultdict

from dcnc_sim.interference import build_activation_policy
from dcnc_sim.mapping import BaseMappingSolver
from dcnc_sim.models import Commodity, DistributedComputingNetwork
from dcnc_sim.simulator import CommodityConfig, DCNCSimulator
from dcnc_sim.wireless import IIDOnOffProcess
from common import build_run_logger, close_logger, ensure_dir, save_dataframe

import run_skewed_moe_case as moe

MILAN_JSON = ROOT / "legacy_inputs" / "Network" / "Milan.json"

GPU_CAPABLE = ["4", "5", "7", "9", "14", "16", "17", "20", "21", "22", "30"]

DYNAMIC_EDGES = [
    ("1", "3"), ("3", "1"),
    ("6", "7"), ("7", "6"),
    ("10", "12"), ("12", "10"),
    ("28", "23"), ("23", "28"),
]
P_ON = 0.8

TENANT_ENDPOINTS = {"a": ("1", "29"), "b": ("6", "27")}


def make_milan_network() -> DistributedComputingNetwork:
    spec = json.loads(MILAN_JSON.read_text(encoding="utf-8"))
    net = DistributedComputingNetwork(
        network_id=spec.get("network_id", "Milan-30"),
        description="Milan wireless MEC substrate (published realization).",
    )
    qualified = set(GPU_CAPABLE)
    for n in spec["nodes"]:
        nid = str(n["id"])
        net.node_roles[nid] = "COMPUTE" if nid in qualified else "FORWARD"
        net.node_capacities[nid] = float(n["capacity"]) if nid in qualified else 0.0
        net.out_adj.setdefault(nid, set())
        net.in_adj.setdefault(nid, set())
    for e in spec["edges"]:
        moe.add_directed_edge(net, str(e["from"]), str(e["to"]), float(e["capacity"]))
    net.validate()
    return net


def _node_sort_key(u):
    su = str(u)
    return (0, int(su)) if su.isdigit() else (1, su)


class PhysicalBacklogLeastLoadedSolver(BaseMappingSolver):
    """Lazarus-inspired least-loaded placement, as described in the paper.

    Each function of a request is placed on the qualified node with the
    smallest current physical computation backlog, measured as the remaining
    work queued at that node.  Work already assigned to a node earlier in the
    same request is added tentatively, so a single request is not collapsed
    onto one node.  Ties break on the smallest node id.

    Dependency routing after placement uses the same queue-aware minimum-cost
    machinery as DCNC-DAG-H (spec section 7.2), so the only difference from
    DCNC-DAG-H is the placement rule.
    """

    def __init__(self, network, seed: int = 1, logger=None, tentative: bool = True):
        super().__init__(network, seed=seed, logger=logger)
        self.physical = None
        # When False the rule reads only the real physical backlog, as a
        # literal reading of 'send each request to the least-loaded replica'.
        self.tentative = tentative

    def _backlog(self, u) -> float:
        if self.physical is None:
            return 0.0
        q = self.physical.node_queues.get(str(u))
        if not q:
            return 0.0
        return float(sum(float(t.size_remaining) for t in q))

    def compute(self, dag, commodity, q_link, q_node):
        assign = {}
        tentative = defaultdict(float)
        edge_cost = self._edge_cost_fn(q_link)
        for a in dag.topo_order():
            candidates = commodity.allowed_nodes(self.network, a)
            best_u = min(
                candidates,
                key=lambda u: (self._backlog(u) + tentative[str(u)], _node_sort_key(u)),
            )
            assign[a] = best_u
            if self.tentative:
                tentative[str(best_u)] += float(dag.r(str(a)))
        return self._build_mapping_from_assignment(
            dag, commodity, assign, edge_cost, q_link, q_node)


class QueueRoutedRoundRobinSolver(BaseMappingSolver):
    """FlexMoE-inspired placement with queue-aware dependency routing.

    Placement is the published fixed rotating order over the sorted qualified
    nodes.  Routing after placement uses the same queue-aware minimum-cost
    machinery as DCNC-DAG-H (spec section 7.3).
    """

    def __init__(self, network, seed: int = 1, logger=None):
        super().__init__(network, seed=seed, logger=logger)
        self.ptr = defaultdict(int)

    def compute(self, dag, commodity, q_link, q_node):
        assign = {}
        edge_cost = self._edge_cost_fn(q_link)
        for a in dag.topo_order():
            candidates = sorted(commodity.allowed_nodes(self.network, a),
                                key=_node_sort_key)
            if not candidates:
                raise RuntimeError("No candidates for %s" % a)
            assign[a] = candidates[self.ptr[a] % len(candidates)]
            self.ptr[a] += 1
        return self._build_mapping_from_assignment(
            dag, commodity, assign, edge_cost, q_link, q_node)


def allowed_on_milan(dag) -> Dict[str, List[str]]:
    return {n: list(GPU_CAPABLE) for n in dag.nodes_all()}


def make_milan_workload(workload: str, split_a: float):
    model = moe.WORKLOADS[workload]
    if model == "mixtral":
        num_layers, model_scale = 4, 2.00
        dag_a = moe.make_skewed_moe_dag(
            "mixtral_skewed_code", num_layers=num_layers, hot="A", warm="B", model_scale=model_scale)
        dag_b = moe.make_skewed_moe_dag(
            "mixtral_skewed_chat", num_layers=num_layers, hot="B", warm="A", model_scale=model_scale)
        hot_a, hot_b = "A", "B"
    else:
        num_layers, model_scale = 5, 1.84
        dag_a = moe.make_skewed_moe_dag(
            "llama_skewed_code", num_layers=num_layers, hot="B", warm="C", model_scale=model_scale)
        dag_b = moe.make_skewed_moe_dag(
            "llama_skewed_chat", num_layers=num_layers, hot="C", warm="B", model_scale=model_scale)
        hot_a, hot_b = "B", "C"

    net = make_milan_network()
    src_a, dst_a = TENANT_ENDPOINTS["a"]
    src_b, dst_b = TENANT_ENDPOINTS["b"]
    commodity_a = Commodity(
        name=workload + "_tenant_code",
        service_dag=dag_a,
        src_nodes={s: src_a for s in dag_a.sources()},
        dst_nodes={d: dst_a for d in dag_a.sinks()},
        allowed=allowed_on_milan(dag_a),
    )
    commodity_b = Commodity(
        name=workload + "_tenant_chat",
        service_dag=dag_b,
        src_nodes={s: src_b for s in dag_b.sources()},
        dst_nodes={d: dst_b for d in dag_b.sinks()},
        allowed=allowed_on_milan(dag_b),
    )
    meta = {
        "model": model,
        "substrate": "milan_wireless_mec",
        "tenant_a_rate_fraction": "%.3f" % split_a,
        "tenant_b_rate_fraction": "%.3f" % (1.0 - split_a),
        "tenant_a_hot_expert": hot_a,
        "tenant_b_hot_expert": hot_b,
        "tenant_a_endpoints": src_a + "->" + dst_a,
        "tenant_b_endpoints": src_b + "->" + dst_b,
        "gpu_capable_nodes": json.dumps(GPU_CAPABLE),
        "gpu_capable_capacities": json.dumps(
            {g: net.node_capacity(g) for g in GPU_CAPABLE}, sort_keys=True),
        "dynamic_edges": json.dumps([u + "->" + v for u, v in DYNAMIC_EDGES]),
        "dynamic_p_on": str(P_ON),
        "model_scale": str(model_scale),
        "num_layers": str(num_layers),
        "workload_scaling_factor": "1.0",
    }
    return net, [commodity_a, commodity_b], meta


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Skewed MoE serving on the Milan wireless MEC substrate.")
    ap.add_argument("--workload", required=True, choices=sorted(moe.WORKLOADS.keys()))
    ap.add_argument("--policy", required=True, choices=sorted(moe.POLICY_ALIASES.keys()))
    ap.add_argument("--rate", type=float, required=True)
    ap.add_argument("--tenant-a-fraction", type=float, default=0.60)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--slots", type=int, default=50000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--fixed-k", type=int, default=1)
    ap.add_argument("--progress-every", type=int, default=10000)
    ap.add_argument("--interference-model", choices=["none", "primary"], default="primary")
    args = ap.parse_args()

    policy = moe.POLICY_ALIASES[args.policy]
    out_dir = ensure_dir(args.output_dir)
    logger, _ = build_run_logger("skewed_moe_milan", out_dir, "skewed_moe_milan")
    try:
        network, commodities, meta = make_milan_workload(args.workload, args.tenant_a_fraction)
        activation_policy = build_activation_policy(args.interference_model)
        wireless_process = IIDOnOffProcess(
            network, {e: P_ON for e in DYNAMIC_EDGES}, seed=1000 + args.seed)
        if policy == "Lazarus-style":
            solver = PhysicalBacklogLeastLoadedSolver(
                network, seed=200000 + args.seed, logger=logger,
                tentative=(os.environ.get("LZ_TENTATIVE", "1") != "0"))
        elif policy == "FlexMoE-style":
            solver = QueueRoutedRoundRobinSolver(
                network, seed=300000 + args.seed, logger=logger)
        else:
            solver = moe.build_solver(policy, network, args.seed, logger, "greedy", None)
        policy_fixed_k = args.fixed_k if policy == "DCNC-DAG-H" else 1
        cfgs = [
            CommodityConfig(commodities[0], args.rate * args.tenant_a_fraction, solver),
            CommodityConfig(commodities[1], args.rate * (1.0 - args.tenant_a_fraction), solver),
        ]
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
            run_label="milan_%s_%s_rate%.6f_seed%d" % (
                args.workload, policy, args.rate, args.seed),
            progress_every=args.progress_every,
        )
        if isinstance(solver, PhysicalBacklogLeastLoadedSolver):
            solver.physical = sim.physical_network
        stats = sim.run()

        total_arr = int(stats.total_service_units)
        done = int(stats.completed_service_units)
        samples = sorted(list(getattr(stats, "routing_oracle_runtime_samples_sec", []) or []))

        def q(p):
            if not samples:
                return ""
            i = min(len(samples) - 1, max(0, int(round(p * (len(samples) - 1)))))
            return samples[i]

        calls = stats.routing_oracle_calls
        row = {
            "model": meta["model"],
            "workload": args.workload,
            "policy": policy,
            "arrival_rate": args.rate,
            "seed": args.seed,
            "horizon": args.slots,
            "total_arrivals": total_arr,
            "total_completions": done,
            "completion_ratio": (done / total_arr) if total_arr else 0.0,
            "completed_throughput": done / float(args.slots),
            "mean_completion_delay": stats.avg_service_delay_completed,
            "unfinished_requests": int(stats.pending_service_units),
            "delivered_packets": stats.delivered_packets,
            "pending_packets": stats.pending_packets,
            "avg_delay_completed": stats.avg_delay_completed,
            "tenant_a_fraction": args.tenant_a_fraction,
            "interference_model": args.interference_model,
            "fixed_k": policy_fixed_k,
            "routing_oracle_calls": calls,
            "routing_oracle_wall_time_sec": stats.routing_oracle_wall_time_sec,
            "mapping_time_per_call_mean_sec": (
                stats.routing_oracle_wall_time_sec / calls if calls else 0.0),
            "mapping_time_p50_sec": q(0.50),
            "mapping_time_p95_sec": q(0.95),
            "mapping_time_max_sec": (samples[-1] if samples else ""),
            "runtime_seconds": stats.simulation_wall_time_sec,
        }
        row.update(meta)
        save_dataframe(pd.DataFrame([row]), out_dir / "moe_milan_result.csv")
        logger.info(
            "MoE/Milan done | %s | %s | rate=%.6f | seed=%d | arrivals=%d | "
            "completions=%d | ratio=%.4f | delay=%.3f",
            args.workload, policy, args.rate, args.seed, total_arr, done,
            row["completion_ratio"], row["mean_completion_delay"])
        print("OK %s %s rate=%s seed=%s ratio=%.4f delay=%.3f" % (
            args.workload, policy, args.rate, args.seed,
            row["completion_ratio"], row["mean_completion_delay"]))
    finally:
        close_logger(logger)


if __name__ == "__main__":
    main()
