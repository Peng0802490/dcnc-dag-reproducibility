from __future__ import annotations

import argparse
import csv
import json
import shlex
from pathlib import Path

from dcnc_sim.interference import build_activation_policy
from dcnc_sim.mapping import (
    DynVMPBridgeSolver,
    NearestToSourceSolver,
    QueueAwareGreedySolver,
    RandomSolver,
    StaticMinCostSolver,
)
from dcnc_sim.models import Commodity, DistributedComputingNetwork, ServiceDAG
from dcnc_sim.simulator import CommodityConfig, DCNCSimulator
from dcnc_sim.wireless import IIDOnOffProcess, AlwaysOnProcess
from dcnc_sim.workloads import restrict_to_allowed_compute_nodes


def load_explicit_config(config_path: Path) -> tuple[DistributedComputingNetwork, list[Commodity]]:
    config_path = config_path.resolve()
    base = config_path.parent
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    net = DistributedComputingNetwork.from_json(base / cfg["network"]["file"])
    commodities: list[Commodity] = []
    for idx, scfg in enumerate(cfg["service_dags"]):
        dag = ServiceDAG.from_json(base / scfg["file"])
        commodities.append(
            Commodity(
                name=scfg.get("name", f"commodity_{idx}"),
                service_dag=dag,
                src_nodes={str(k): str(v) for k, v in scfg.get("sources", {}).items()},
                dst_nodes={str(k): str(v) for k, v in scfg.get("sinks", {}).items()},
                allowed={str(k): [str(u) for u in v] for k, v in (scfg.get("allowed") or {}).items()},
            )
        )
    restrict_to_allowed_compute_nodes(net, commodities)
    return net, commodities


def parse_dynamic_edges_from_metadata(network: DistributedComputingNetwork) -> dict[tuple[str, str], float]:
    dyn: dict[tuple[str, str], float] = {}
    for item in network.metadata.get("dynamic_edges", []) or []:
        dyn[(str(item["from"]), str(item["to"]))] = float(item.get("p_on", 1.0))
    return dyn


def build_solver(policy: str, net: DistributedComputingNetwork, seed: int, args):
    if policy in {"DCNC-DAG", "DCNC-DAG-Cost"}:
        if args.dcnc_solver == "dynvmp_bridge":
            return DynVMPBridgeSolver(
                net,
                bridge_cmd=shlex.split(args.dynvmp_cmd) if args.dynvmp_cmd else None,
                seed=seed,
            )
        return QueueAwareGreedySolver(net, seed=seed)
    if policy == "CTS":
        return NearestToSourceSolver(net, seed=seed)
    if policy == "Static-MinCost":
        return StaticMinCostSolver(net, seed=seed)
    return RandomSolver(net, seed=seed)


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the 24-node AI-RAN smart-factory case.")
    ap.add_argument("--config", default="legacy_inputs/config_ai_ran_three_tasks.json")
    ap.add_argument("--output-dir", default="results/project_case")
    ap.add_argument("--slots", type=int, default=400)
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--seed-start", type=int, default=0)
    ap.add_argument("--rate", type=float, default=0.18, help="Total arrival rate, equally split across all commodities.")
    ap.add_argument(
        "--policy",
        choices=["DCNC-DAG", "DCNC-DAG-Cost", "CTS", "Static-MinCost", "Random"],
        default="DCNC-DAG",
    )
    ap.add_argument("--fixed-k", type=int, default=1)
    ap.add_argument("--interference-model", choices=["none", "primary"], default="primary")
    ap.add_argument("--dcnc-solver", choices=["greedy", "dynvmp_bridge"], default="greedy")
    ap.add_argument("--dynvmp-cmd", default=None)
    ap.add_argument("--resource-alpha", type=float, default=1.0)
    ap.add_argument("--resource-beta", type=float, default=1.0)
    ap.add_argument("--resource-cost-weight", type=float, default=1.0, help="Only used by DCNC-DAG-Cost.")
    args = ap.parse_args()

    config_path = Path(args.config)
    net, comms = load_explicit_config(config_path)
    dynamic_edges = parse_dynamic_edges_from_metadata(net)
    activation_policy = build_activation_policy(args.interference_model)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "project_case_results.csv"

    rows = []
    for seed in range(args.seed_start, args.seed_start + args.seeds):
        per_rate = args.rate / max(len(comms), 1)
        if dynamic_edges:
            wireless = IIDOnOffProcess(net, dynamic_edges, seed=1000 + seed)
        else:
            wireless = AlwaysOnProcess(net)
        commodity_cfgs = []
        for idx, commodity in enumerate(comms):
            solver = build_solver(args.policy, net, 2000 + 100 * idx + seed, args)
            commodity_cfgs.append(CommodityConfig(commodity, per_rate, solver))

        policy_fixed_k = args.fixed_k if args.policy in {"DCNC-DAG", "DCNC-DAG-Cost"} else 1
        sim = DCNCSimulator(
            network=net,
            commodity_cfgs=commodity_cfgs,
            wireless_process=wireless,
            total_slots=args.slots,
            seed=3000 + seed,
            scheduler="nto",
            activation_policy=activation_policy,
            fixed_k=policy_fixed_k,
            run_label=f"project_case_{args.policy}_rate{args.rate:.4f}_seed{seed}",
            progress_every=max(25, args.slots // 10),
            resource_alpha=args.resource_alpha,
            resource_beta=args.resource_beta,
            resource_cost_weight=args.resource_cost_weight if args.policy == "DCNC-DAG-Cost" else 0.0,
        )
        stats = sim.run()
        rows.append(
            {
                "policy": args.policy,
                "seed": seed,
                "total_arrival_rate": args.rate,
                "per_commodity_arrival_rate": per_rate,
                "interference_model": args.interference_model,
                "fixed_k": policy_fixed_k,
                "dcnc_solver": args.dcnc_solver if args.policy in {"DCNC-DAG", "DCNC-DAG-Cost"} else "",
                "avg_delay_completed": stats.avg_delay_completed,
                "avg_delay_with_penalty": stats.avg_delay_with_penalty,
                "delivered_packets": stats.delivered_packets,
                "pending_packets": stats.pending_packets,
                "total_jobs": stats.total_jobs,
                "completed_jobs": stats.completed_jobs,
                "pending_jobs": stats.pending_jobs,
                "job_throughput": stats.completed_jobs / float(args.slots),
                "job_completion_ratio": stats.completed_jobs / float(max(1, stats.total_jobs)),
                "admitted_comm_cost_raw": stats.admitted_comm_cost_raw,
                "admitted_comp_cost_raw": stats.admitted_comp_cost_raw,
                "admitted_comm_cost_norm": stats.admitted_comm_cost_norm,
                "admitted_comp_cost_norm": stats.admitted_comp_cost_norm,
                "admitted_total_cost_norm": stats.admitted_total_cost_norm,
                "completed_comm_cost_raw": stats.completed_comm_cost_raw,
                "completed_comp_cost_raw": stats.completed_comp_cost_raw,
                "completed_comm_cost_norm": stats.completed_comm_cost_norm,
                "completed_comp_cost_norm": stats.completed_comp_cost_norm,
                "completed_total_cost_norm": stats.completed_total_cost_norm,
                "admitted_total_cost_norm_per_slot": stats.admitted_total_cost_norm_per_slot,
                "completed_total_cost_norm_per_slot": stats.completed_total_cost_norm_per_slot,
                "completed_comm_cost_norm_per_job": stats.completed_comm_cost_norm_per_job,
                "completed_comp_cost_norm_per_job": stats.completed_comp_cost_norm_per_job,
                "completed_total_cost_norm_per_job": stats.completed_total_cost_norm_per_job,
                "resource_alpha": args.resource_alpha,
                "resource_beta": args.resource_beta,
                "resource_cost_weight": args.resource_cost_weight if args.policy == "DCNC-DAG-Cost" else 0.0,
                "routing_oracle_calls": stats.routing_oracle_calls,
                "routing_cache_hits": stats.routing_cache_hits,
                "num_dynamic_edges": len(dynamic_edges),
                "num_nodes": len(net.nodes_all()),
                "num_edges": len(net.edges_all()),
            }
        )

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"[done] wrote {csv_path}")


if __name__ == "__main__":
    main()
