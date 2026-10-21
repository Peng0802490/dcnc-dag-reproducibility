from __future__ import annotations

import argparse
import shlex
from dataclasses import dataclass

import pandas as pd

from dcnc_sim.interference import build_activation_policy
from dcnc_sim.mapping import DynVMPBridgeSolver, LeastUsedReplicaSolver, QueueAwareGreedySolver, RoundRobinReplicaSolver, StaticPlacementSolver
from dcnc_sim.plotting import plot_delay_curve
from dcnc_sim.simulator import CommodityConfig, DCNCSimulator
from dcnc_sim.wireless import AlwaysOnProcess
from dcnc_sim.workloads import make_cpu_gpu_cluster, make_inception_v3_macro_workload, make_llama_maverick_workload, make_mixtral_workload, make_resnet50_macro_workload, make_three_workstation_gpu_cluster

from common import build_run_logger, close_logger, ensure_dir, save_dataframe


@dataclass
class WorkloadCase:
    name: str
    family: str
    rates: list[float]


def main() -> None:
    ap = argparse.ArgumentParser(description="Run AI-workload experiments on always-on cluster networks.")
    ap.add_argument("--output-dir", default="results/ai_experiments")
    ap.add_argument("--slots", type=int, default=500)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--progress-every", type=int, default=50)
    ap.add_argument("--fixed-k", type=int, default=1, help="Frame length K for the Fixed-K routing extension. Use 1 for the exact policy.")
    ap.add_argument(
        "--interference-model",
        choices=["none", "primary"],
        default="none",
        help="Feasible-link-activation model. The AI experiments default to no interference because the cluster links are always on.",
    )
    ap.add_argument("--dcnc-solver", choices=["greedy", "dynvmp_bridge"], default="greedy")
    ap.add_argument("--dynvmp-cmd", default=None, help="Command used to invoke the DynVMP bridge when --dcnc-solver dynvmp_bridge is selected.")
    args = ap.parse_args()

    out_dir = ensure_dir(args.output_dir)
    logger, _ = build_run_logger("ai_experiments", out_dir, "ai_experiments")
    rows = []

    try:
        activation_policy = build_activation_policy(args.interference_model)
        logger.info("AI experiments | interference_model=%s | fixed_k=%d", args.interference_model, args.fixed_k)
        moe_cases = [
            (WorkloadCase("mixtral_8x7b_macro", "moe", [0.10, 0.20, 0.30, 0.40]), make_mixtral_workload()),
            (WorkloadCase("llama4_maverick_macro", "moe", [0.10, 0.20, 0.30, 0.40]), make_llama_maverick_workload()),
        ]
        graph_cases = [
            (WorkloadCase("resnet50_macro", "graph", [0.20, 0.40, 0.60, 0.80]), make_resnet50_macro_workload()),
            (WorkloadCase("inception_v3_macro", "graph", [0.20, 0.40, 0.60, 0.80]), make_inception_v3_macro_workload()),
        ]

        moe_net = make_three_workstation_gpu_cluster()
        moe_wireless = AlwaysOnProcess(moe_net)
        logger.info("MoE network summary: %s", moe_net.summary())
        for case, commodity in moe_cases:
            case_dir = ensure_dir(out_dir / case.name)
            case_rows = []
            for policy in ["DCNC-DAG-H", "Lazarus-style", "FlexMoE-style"]:
                policy_fixed_k = args.fixed_k if policy == "DCNC-DAG-H" else 1
                for rate in case.rates:
                    for seed in range(args.seeds):
                        logger.info("MoE start | case=%s | policy=%s | rate=%.4f | seed=%d", case.name, policy, rate, seed)
                        if policy == "DCNC-DAG-H":
                            if args.dcnc_solver == "dynvmp_bridge":
                                solver = DynVMPBridgeSolver(
                                    moe_net,
                                    bridge_cmd=shlex.split(args.dynvmp_cmd) if args.dynvmp_cmd else None,
                                    seed=1000 + seed,
                                    logger=logger,
                                )
                            else:
                                solver = QueueAwareGreedySolver(moe_net, seed=1000 + seed, logger=logger)
                        elif policy == "Lazarus-style":
                            solver = LeastUsedReplicaSolver(moe_net, seed=1000 + seed, logger=logger)
                        else:
                            solver = RoundRobinReplicaSolver(moe_net, seed=1000 + seed, logger=logger)
                        sim = DCNCSimulator(
                            network=moe_net,
                            commodity_cfgs=[CommodityConfig(commodity, rate, solver)],
                            wireless_process=moe_wireless,
                            total_slots=args.slots,
                            seed=2000 + seed,
                            scheduler="nto",
                            activation_policy=activation_policy,
                            fixed_k=policy_fixed_k,
                            logger=logger,
                            run_label=f"{case.name}_{policy}_rate{rate:.4f}_seed{seed}",
                            progress_every=args.progress_every,
                        )
                        stats = sim.run()
                        row = {
                            "case": case.name,
                            "family": case.family,
                            "policy": policy,
                            "seed": seed,
                            "arrival_rate": rate,
                            "interference_model": args.interference_model,
                            "fixed_k": policy_fixed_k,
                            "avg_delay_completed": stats.avg_delay_completed,
                            "avg_delay_with_penalty": stats.avg_delay_with_penalty,
                            "achieved_throughput": stats.delivered_packets / float(args.slots),
                            "delivered_packets": stats.delivered_packets,
                            "pending_packets": stats.pending_packets,
                            "routing_oracle_calls": stats.routing_oracle_calls,
                            "routing_cache_hits": stats.routing_cache_hits,
                        }
                        rows.append(row)
                        case_rows.append(row)
                        logger.info(
                            "MoE done | case=%s | policy=%s | rate=%.4f | seed=%d | throughput=%.6f | oracle_calls=%d | cache_hits=%d",
                            case.name,
                            policy,
                            rate,
                            seed,
                            row["achieved_throughput"],
                            stats.routing_oracle_calls,
                            stats.routing_cache_hits,
                        )
            df = pd.DataFrame(case_rows)
            save_dataframe(df, case_dir / f"{case.name}_results.csv")
            plot_delay_curve(
                df.groupby(["policy", "arrival_rate"], as_index=False)["avg_delay_with_penalty"].mean(),
                x="arrival_rate",
                y="avg_delay_with_penalty",
                hue="policy",
                out_path=case_dir / f"{case.name}_delay_curve.png",
                xlabel="Arrival rate per slot",
                ylabel="Average delay with unfinished-packet penalty",
            )
            logger.info("Finished MoE case: %s", case.name)

        graph_net = make_cpu_gpu_cluster()
        graph_wireless = AlwaysOnProcess(graph_net)
        logger.info("Graph network summary: %s", graph_net.summary())
        for case, commodity in graph_cases:
            case_dir = ensure_dir(out_dir / case.name)
            case_rows = []
            for policy in ["DCNC-DAG-H", "HSDAG-style"]:
                policy_fixed_k = args.fixed_k if policy == "DCNC-DAG-H" else 1
                for rate in case.rates:
                    for seed in range(args.seeds):
                        logger.info("Graph start | case=%s | policy=%s | rate=%.4f | seed=%d", case.name, policy, rate, seed)
                        if policy == "DCNC-DAG-H":
                            if args.dcnc_solver == "dynvmp_bridge":
                                solver = DynVMPBridgeSolver(
                                    graph_net,
                                    bridge_cmd=shlex.split(args.dynvmp_cmd) if args.dynvmp_cmd else None,
                                    seed=4000 + seed,
                                    logger=logger,
                                )
                            else:
                                solver = QueueAwareGreedySolver(graph_net, seed=4000 + seed, logger=logger)
                        else:
                            solver = StaticPlacementSolver(graph_net, seed=4000 + seed, logger=logger)
                        sim = DCNCSimulator(
                            network=graph_net,
                            commodity_cfgs=[CommodityConfig(commodity, rate, solver)],
                            wireless_process=graph_wireless,
                            total_slots=args.slots,
                            seed=5000 + seed,
                            scheduler="nto",
                            activation_policy=activation_policy,
                            fixed_k=policy_fixed_k,
                            logger=logger,
                            run_label=f"{case.name}_{policy}_rate{rate:.4f}_seed{seed}",
                            progress_every=args.progress_every,
                        )
                        stats = sim.run()
                        row = {
                            "case": case.name,
                            "family": case.family,
                            "policy": policy,
                            "seed": seed,
                            "arrival_rate": rate,
                            "interference_model": args.interference_model,
                            "fixed_k": policy_fixed_k,
                            "avg_delay_completed": stats.avg_delay_completed,
                            "avg_delay_with_penalty": stats.avg_delay_with_penalty,
                            "achieved_throughput": stats.delivered_packets / float(args.slots),
                            "delivered_packets": stats.delivered_packets,
                            "pending_packets": stats.pending_packets,
                            "routing_oracle_calls": stats.routing_oracle_calls,
                            "routing_cache_hits": stats.routing_cache_hits,
                        }
                        rows.append(row)
                        case_rows.append(row)
                        logger.info(
                            "Graph done | case=%s | policy=%s | rate=%.4f | seed=%d | throughput=%.6f | oracle_calls=%d | cache_hits=%d",
                            case.name,
                            policy,
                            rate,
                            seed,
                            row["achieved_throughput"],
                            stats.routing_oracle_calls,
                            stats.routing_cache_hits,
                        )
            df = pd.DataFrame(case_rows)
            save_dataframe(df, case_dir / f"{case.name}_results.csv")
            plot_delay_curve(
                df.groupby(["policy", "arrival_rate"], as_index=False)["avg_delay_with_penalty"].mean(),
                x="arrival_rate",
                y="avg_delay_with_penalty",
                hue="policy",
                out_path=case_dir / f"{case.name}_delay_curve.png",
                xlabel="Arrival rate per slot",
                ylabel="Average delay with unfinished-packet penalty",
            )
            logger.info("Finished graph case: %s", case.name)

        save_dataframe(pd.DataFrame(rows), out_dir / "ai_experiments_all_results.csv")
        logger.info("All AI-experiment results written to: %s", out_dir)
    finally:
        close_logger(logger)


if __name__ == "__main__":
    main()
