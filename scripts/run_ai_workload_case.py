from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path
from typing import Callable

import pandas as pd

from dcnc_sim.interference import build_activation_policy
from dcnc_sim.mapping import (
    DynVMPBridgeSolver,
    LeastUsedReplicaSolver,
    QueueAwareGreedySolver,
    RoundRobinReplicaSolver,
    StaticPlacementSolver,
)
from dcnc_sim.simulator import CommodityConfig, DCNCSimulator
from dcnc_sim.wireless import AlwaysOnProcess
from dcnc_sim.workloads import (
    make_cpu_gpu_cluster,
    make_inception_v3_macro_workload,
    make_llama_maverick_workload,
    make_mixtral_workload,
    make_resnet50_macro_workload,
    make_three_workstation_gpu_cluster,
)

from common import build_run_logger, close_logger, ensure_dir, save_dataframe


MOE_WORKLOADS = {
    "mixtral_8x7b_macro": make_mixtral_workload,
    "llama4_maverick_macro": make_llama_maverick_workload,
}
GRAPH_WORKLOADS = {
    "resnet50_macro": make_resnet50_macro_workload,
    "inception_v3_macro": make_inception_v3_macro_workload,
}

POLICY_ALIASES = {
    "DCNC-DAG-H": "DCNC-DAG-H",
    "DCNC-DAG": "DCNC-DAG-H",
    "Lazarus": "Lazarus-style",
    "Lazarus-style": "Lazarus-style",
    "FlexMoE": "FlexMoE-style",
    "FlexMoE-style": "FlexMoE-style",
    "HSDAG": "HSDAG-style",
    "HSDAG-style": "HSDAG-style",
}

CASE_FAMILY = {
    "mixtral_8x7b_macro": "moe",
    "llama4_maverick_macro": "moe",
    "resnet50_macro": "graph",
    "inception_v3_macro": "graph",
}


def build_network_and_commodity(workload: str):
    if workload in MOE_WORKLOADS:
        return make_three_workstation_gpu_cluster(), MOE_WORKLOADS[workload]()
    if workload in GRAPH_WORKLOADS:
        return make_cpu_gpu_cluster(), GRAPH_WORKLOADS[workload]()
    raise ValueError(f"Unknown workload: {workload}")


def validate_policy_for_workload(workload: str, policy: str) -> None:
    family = CASE_FAMILY[workload]
    if family == "moe":
        allowed = {"DCNC-DAG-H", "Lazarus-style", "FlexMoE-style"}
    else:
        allowed = {"DCNC-DAG-H", "HSDAG-style"}
    if policy not in allowed:
        raise ValueError(
            f"Policy {policy!r} is not compatible with workload {workload!r} (family={family}). "
            f"Allowed policies: {sorted(allowed)}"
        )


def build_solver(
    policy: str,
    network,
    seed: int,
    logger,
    dcnc_solver: str,
    dynvmp_cmd: str | None,
):
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
    if policy == "HSDAG-style":
        return StaticPlacementSolver(network, seed=400000 + seed, logger=logger)
    raise ValueError(f"Unknown policy: {policy}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Run one AI workload / one policy / one arrival-rate point for tmux CSV scheduling."
    )
    ap.add_argument(
        "--workload",
        required=True,
        choices=sorted(list(MOE_WORKLOADS.keys()) + list(GRAPH_WORKLOADS.keys())),
    )
    ap.add_argument("--policy", required=True, choices=sorted(POLICY_ALIASES.keys()))
    ap.add_argument("--rate", type=float, required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--slots", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--fixed-k", type=int, default=1)
    ap.add_argument("--progress-every", type=int, default=500)
    ap.add_argument(
        "--interference-model",
        choices=["none", "primary"],
        default="none",
        help="AI benchmark clusters use always-on links by default, so 'none' is the default.",
    )
    ap.add_argument("--dcnc-solver", choices=["greedy", "dynvmp_bridge"], default="greedy")
    ap.add_argument("--dynvmp-cmd", default=None)
    args = ap.parse_args()

    workload = args.workload
    policy = POLICY_ALIASES[args.policy]
    validate_policy_for_workload(workload, policy)

    out_dir = ensure_dir(args.output_dir)
    logger, _ = build_run_logger("ai_workload_case", out_dir, "ai_workload_case")

    try:
        network, commodity = build_network_and_commodity(workload)
        activation_policy = build_activation_policy(args.interference_model)
        wireless_process = AlwaysOnProcess(network)
        solver = build_solver(policy, network, args.seed, logger, args.dcnc_solver, args.dynvmp_cmd)

        policy_fixed_k = args.fixed_k if policy == "DCNC-DAG-H" else 1
        logger.info(
            "AI workload start | workload=%s | family=%s | policy=%s | rate=%.6f | slots=%d | seed=%d | fixed_k=%d | interference=%s | network=%s",
            workload,
            CASE_FAMILY[workload],
            policy,
            args.rate,
            args.slots,
            args.seed,
            policy_fixed_k,
            args.interference_model,
            network.summary(),
        )

        sim = DCNCSimulator(
            network=network,
            commodity_cfgs=[CommodityConfig(commodity, args.rate, solver)],
            wireless_process=wireless_process,
            total_slots=args.slots,
            seed=500000 + args.seed,
            scheduler="nto",
            activation_policy=activation_policy,
            fixed_k=policy_fixed_k,
            logger=logger,
            run_label=f"{workload}_{policy}_rate{args.rate:.6f}_seed{args.seed}",
            progress_every=args.progress_every,
        )
        stats = sim.run()

        row = {
            "workload": workload,
            "family": CASE_FAMILY[workload],
            "policy": policy,
            "seed": args.seed,
            "arrival_rate": args.rate,
            "slots": args.slots,
            "interference_model": args.interference_model,
            "fixed_k": policy_fixed_k,
            "dcnc_solver": args.dcnc_solver if policy == "DCNC-DAG-H" else "baseline",
            "avg_delay_completed": stats.avg_delay_completed,
            "avg_delay_with_penalty": stats.avg_delay_with_penalty,
            "achieved_throughput": stats.delivered_packets / float(args.slots),
            "delivered_packets": stats.delivered_packets,
            "pending_packets": stats.pending_packets,
            "routing_oracle_calls": stats.routing_oracle_calls,
            "routing_cache_hits": stats.routing_cache_hits,
        }
        df = pd.DataFrame([row])
        save_dataframe(df, out_dir / "ai_workload_case_result.csv")
        (out_dir / "ai_workload_case_metadata.json").write_text(
            json.dumps(
                {
                    "workload": workload,
                    "family": CASE_FAMILY[workload],
                    "policy": policy,
                    "rate": args.rate,
                    "slots": args.slots,
                    "seed": args.seed,
                    "network_summary": network.summary(),
                    "commodity_name": commodity.name,
                    "service_dag_summary": commodity.service_dag.summary(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        logger.info(
            "AI workload done | workload=%s | policy=%s | rate=%.6f | seed=%d | completed_delay=%.6f | penalty_delay=%.6f | throughput=%.6f | delivered=%d | pending=%d",
            workload,
            policy,
            args.rate,
            args.seed,
            row["avg_delay_completed"],
            row["avg_delay_with_penalty"],
            row["achieved_throughput"],
            stats.delivered_packets,
            stats.pending_packets,
        )
        print(df.to_string(index=False))
    finally:
        close_logger(logger)


if __name__ == "__main__":
    main()
