from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from dcnc_sim.interference import build_activation_policy
from dcnc_sim.mapping import NearestToSourceSolver, QueueAwareGreedySolver, RandomSolver
from dcnc_sim.models import Commodity, DistributedComputingNetwork, ServiceDAG
from dcnc_sim.simulator import CommodityConfig, DCNCSimulator
from dcnc_sim.wireless import AlwaysOnProcess, IIDOnOffProcess
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


def build_solver(policy: str, net: DistributedComputingNetwork, seed: int):
    if policy == "DCNC-DAG":
        return QueueAwareGreedySolver(net, seed=seed)
    if policy == "CTS":
        return NearestToSourceSolver(net, seed=seed)
    return RandomSolver(net, seed=seed)


def main() -> None:
    ap = argparse.ArgumentParser(description="Run one workflow-derived service-DAG case on an explicit network/config file.")
    ap.add_argument("--config", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--slots", type=int, default=2000)
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--seed-start", type=int, default=0)
    ap.add_argument("--rate", type=float, required=True, help="Total arrival rate, equally split across commodities in the config.")
    ap.add_argument("--policy", choices=["DCNC-DAG", "CTS", "Random"], required=True)
    ap.add_argument("--fixed-k", type=int, default=50)
    ap.add_argument("--interference-model", choices=["none", "primary"], default="primary")
    ap.add_argument("--progress-every", type=int, default=200)
    args = ap.parse_args()

    config_path = Path(args.config)
    net, comms = load_explicit_config(config_path)
    dynamic_edges = parse_dynamic_edges_from_metadata(net)
    activation_policy = build_activation_policy(args.interference_model)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "workflow_case_results.csv"

    rows = []
    for seed in range(args.seed_start, args.seed_start + args.seeds):
        per_rate = args.rate / max(len(comms), 1)
        wireless = IIDOnOffProcess(net, dynamic_edges, seed=1000 + seed) if dynamic_edges else AlwaysOnProcess(net)
        commodity_cfgs = []
        for idx, commodity in enumerate(comms):
            solver = build_solver(args.policy, net, 2000 + 100 * idx + seed)
            commodity_cfgs.append(CommodityConfig(commodity, per_rate, solver))
        policy_fixed_k = args.fixed_k if args.policy == "DCNC-DAG" else 1
        sim = DCNCSimulator(
            network=net,
            commodity_cfgs=commodity_cfgs,
            wireless_process=wireless,
            total_slots=args.slots,
            seed=3000 + seed,
            scheduler="nto",
            activation_policy=activation_policy,
            fixed_k=policy_fixed_k,
            run_label=f"workflow_{config_path.stem}_{args.policy}_rate{args.rate:.4f}_seed{seed}",
            progress_every=args.progress_every,
        )
        stats = sim.run()
        first_comm = comms[0] if comms else None
        rows.append({
            "case": config_path.stem,
            "workflow": first_comm.name if first_comm else config_path.stem,
            "policy": args.policy,
            "policy_display": "DCNC-DAG-H" if args.policy == "DCNC-DAG" else args.policy,
            "seed": seed,
            "total_arrival_rate": args.rate,
            "per_commodity_arrival_rate": per_rate,
            "interference_model": args.interference_model,
            "fixed_k": policy_fixed_k,
            "dcnc_solver": "greedy" if args.policy == "DCNC-DAG" else "",
            "avg_delay_completed": stats.avg_delay_completed,
            "avg_delay_with_penalty": stats.avg_delay_with_penalty,
            "delivered_packets": stats.delivered_packets,
            "pending_packets": stats.pending_packets,
            "total_jobs": stats.total_packets,
            "completed_jobs": stats.delivered_packets,
            "pending_jobs": stats.pending_packets,
            "job_throughput": stats.delivered_packets / float(args.slots),
            "job_completion_ratio": stats.delivered_packets / float(max(1, stats.total_packets)),
            "routing_oracle_calls": stats.routing_oracle_calls,
            "routing_cache_hits": stats.routing_cache_hits,
            "num_dynamic_edges": len(dynamic_edges),
            "num_nodes": len(net.nodes_all()),
            "num_edges": len(net.edges_all()),
        })

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"[done] wrote {csv_path}")


if __name__ == "__main__":
    main()
