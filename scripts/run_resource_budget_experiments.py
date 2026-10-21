from __future__ import annotations

import argparse
import copy
import shlex
from dataclasses import dataclass

import pandas as pd

from dcnc_sim.interference import build_activation_policy
from dcnc_sim.mapping import DynVMPBridgeSolver, NearestToSourceSolver, QueueAwareGreedySolver, RandomSolver, StaticMinCostSolver
from dcnc_sim.simulator import CommodityConfig, DCNCSimulator
from dcnc_sim.wireless import IIDOnOffProcess
from dcnc_sim.workloads import load_legacy_config

from common import build_run_logger, close_logger, ensure_dir, save_dataframe, save_json


PAPER_DYNAMIC_EDGES = {
    "milan": [
        ("1", "3"), ("3", "1"),
        ("6", "7"), ("7", "6"),
        ("10", "12"), ("12", "10"),
        ("28", "23"), ("23", "28"),
    ],
    "random": [
        ("31", "7"), ("7", "31"),
        ("35", "3"), ("3", "35"),
        ("40", "7"), ("7", "40"),
        ("18", "30"), ("30", "18"),
        ("20", "28"), ("28", "20"),
        ("5", "46"), ("46", "5"),
    ],
}


def _parse_edge_list(items: list[str] | None, p_on: float) -> dict[tuple[str, str], float]:
    dynamic: dict[tuple[str, str], float] = {}
    for item in items or []:
        if "->" not in item:
            raise ValueError(f"dynamic edge must look like u->v, got {item!r}")
        u, v = item.split("->", 1)
        dynamic[(u.strip(), v.strip())] = float(p_on)
    return dynamic


def _default_dynamic_edges(case_name: str, p_on: float) -> dict[tuple[str, str], float]:
    key = "milan" if "milan" in case_name.lower() else "random" if "random" in case_name.lower() else ""
    if key in PAPER_DYNAMIC_EDGES:
        return {e: float(p_on) for e in PAPER_DYNAMIC_EDGES[key]}
    return {}


def _dynamic_edges_from_metadata(net, fallback_p_on: float) -> dict[tuple[str, str], float]:
    dynamic: dict[tuple[str, str], float] = {}
    for item in net.metadata.get("dynamic_edges", []) or []:
        dynamic[(str(item["from"]), str(item["to"]))] = float(item.get("p_on", fallback_p_on))
    return dynamic


def _scale_network(net, gamma: float):
    net2 = copy.deepcopy(net)
    g = float(gamma)
    net2.node_capacities = {u: cap * g for u, cap in net2.node_capacities.items()}
    net2.edge_capacities = {e: cap * g for e, cap in net2.edge_capacities.items()}
    return net2


def _make_solver(policy: str, net, args, idx: int, seed: int, logger):
    if policy in {"DCNC-DAG", "DCNC-DAG-Cost"}:
        if args.dcnc_solver == "dynvmp_bridge":
            return DynVMPBridgeSolver(
                net,
                bridge_cmd=shlex.split(args.dynvmp_cmd) if args.dynvmp_cmd else None,
                seed=2000 + 100 * idx + seed,
                logger=logger,
            )
        return QueueAwareGreedySolver(net, seed=2000 + 100 * idx + seed, logger=logger)
    if policy == "CTS":
        return NearestToSourceSolver(net, seed=2000 + 100 * idx + seed, logger=logger)
    if policy == "Static-MinCost":
        return StaticMinCostSolver(net, seed=2000 + 100 * idx + seed, logger=logger)
    if policy == "Random":
        return RandomSolver(net, seed=2000 + 100 * idx + seed, logger=logger)
    raise ValueError(f"unknown policy: {policy}")


def _summarize_budget(df: pd.DataFrame, baseline_policy: str, completion_threshold: float, delay_threshold: float | None) -> pd.DataFrame:
    if df.empty:
        return df
    agg = df.groupby(["case", "policy", "gamma"], as_index=False).agg(
        job_completion_ratio=("job_completion_ratio", "mean"),
        job_throughput=("job_throughput", "mean"),
        avg_delay_with_penalty=("avg_delay_with_penalty", "mean"),
        completed_total_cost_norm_per_job=("completed_total_cost_norm_per_job", "mean"),
    )
    stable = agg["job_completion_ratio"] >= float(completion_threshold)
    if delay_threshold is not None:
        stable &= agg["avg_delay_with_penalty"] <= float(delay_threshold)
    agg["stable"] = stable

    rows = []
    for (case, policy), g in agg.groupby(["case", "policy"]):
        ok = g[g["stable"]].sort_values("gamma")
        if ok.empty:
            gamma_star = pd.NA
        else:
            gamma_star = float(ok.iloc[0]["gamma"])
        rows.append({"case": case, "policy": policy, "gamma_star": gamma_star})
    budget = pd.DataFrame(rows)
    if baseline_policy in set(budget["policy"]):
        base = budget[budget["policy"] == baseline_policy][["case", "gamma_star"]].rename(columns={"gamma_star": "baseline_gamma_star"})
        budget = budget.merge(base, on="case", how="left")
        budget["budget_saving_vs_" + baseline_policy] = (
            (budget["baseline_gamma_star"] - budget["gamma_star"]) / budget["baseline_gamma_star"]
        )
    return agg, budget


def main() -> None:
    ap = argparse.ArgumentParser(description="Search the minimum resource-scaling budget gamma needed to support a fixed task load.")
    ap.add_argument("--output-dir", default="results/resource_budget")
    ap.add_argument("--config-file", default="config_driving_Milan.json")
    ap.add_argument("--case-name", default="driving_milan")
    ap.add_argument("--target-rate", type=float, required=True, help="Total arrival rate of the fixed task load.")
    ap.add_argument("--gammas", nargs="*", type=float, default=[0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2])
    ap.add_argument("--slots", type=int, default=2000)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--seed-start", type=int, default=0)
    ap.add_argument("--progress-every", type=int, default=200)
    ap.add_argument("--fixed-k", type=int, default=1)
    ap.add_argument("--interference-model", choices=["none", "primary"], default="primary")
    ap.add_argument("--dcnc-solver", choices=["greedy", "dynvmp_bridge"], default="greedy")
    ap.add_argument("--dynvmp-cmd", default=None)
    ap.add_argument("--resource-alpha", type=float, default=1.0)
    ap.add_argument("--resource-beta", type=float, default=1.0)
    ap.add_argument("--resource-cost-weight", type=float, default=1.0)
    ap.add_argument("--completion-threshold", type=float, default=0.98)
    ap.add_argument("--delay-threshold", type=float, default=None)
    ap.add_argument("--baseline-policy", default="CTS")
    ap.add_argument("--dynamic-edge-p-on", type=float, default=0.8)
    ap.add_argument("--dynamic-edges", nargs="*", default=None, help="Optional list like e1->e2 n1->n2. If omitted, script uses paper defaults for Milan/Random and no dynamic edges otherwise.")
    ap.add_argument(
        "--policies",
        nargs="*",
        default=["DCNC-DAG", "DCNC-DAG-Cost", "CTS", "Static-MinCost", "Random"],
        choices=["DCNC-DAG", "DCNC-DAG-Cost", "CTS", "Static-MinCost", "Random"],
    )
    args = ap.parse_args()

    out_dir = ensure_dir(args.output_dir)
    logger, log_path = build_run_logger("resource_budget", out_dir, "resource_budget")
    rows = []

    try:
        base_net, comms = load_legacy_config(args.config_file)
        dynamic_edges = _parse_edge_list(args.dynamic_edges, args.dynamic_edge_p_on)
        if not dynamic_edges:
            dynamic_edges = _dynamic_edges_from_metadata(base_net, args.dynamic_edge_p_on)
        if not dynamic_edges:
            dynamic_edges = _default_dynamic_edges(args.case_name, args.dynamic_edge_p_on)
        activation_policy = build_activation_policy(args.interference_model)
        logger.info("Resource budget case=%s config=%s target_rate=%.6f gammas=%s", args.case_name, args.config_file, args.target_rate, args.gammas)
        logger.info("Dynamic edges=%s", dynamic_edges)

        for gamma in sorted(args.gammas):
            net = _scale_network(base_net, gamma)
            per_rate = args.target_rate / max(len(comms), 1)
            for policy in args.policies:
                policy_fixed_k = args.fixed_k if policy in {"DCNC-DAG", "DCNC-DAG-Cost"} else 1
                for seed in range(args.seed_start, args.seed_start + args.seeds):
                    logger.info("Start | gamma=%.4f policy=%s seed=%d", gamma, policy, seed)
                    wireless = IIDOnOffProcess(net, dynamic_edges, seed=1000 + seed)
                    commodity_cfgs = [
                        CommodityConfig(
                            commodity,
                            per_rate,
                            _make_solver(policy, net, args, idx, seed, logger),
                        )
                        for idx, commodity in enumerate(comms)
                    ]
                    sim = DCNCSimulator(
                        network=net,
                        commodity_cfgs=commodity_cfgs,
                        wireless_process=wireless,
                        total_slots=args.slots,
                        seed=3000 + seed,
                        scheduler="nto",
                        activation_policy=activation_policy,
                        fixed_k=policy_fixed_k,
                        logger=logger,
                        run_label=f"{args.case_name}_{policy}_gamma{gamma:.4f}_seed{seed}",
                        progress_every=args.progress_every,
                        resource_alpha=args.resource_alpha,
                        resource_beta=args.resource_beta,
                        resource_cost_weight=args.resource_cost_weight if policy == "DCNC-DAG-Cost" else 0.0,
                    )
                    stats = sim.run()
                    row = {
                        "case": args.case_name,
                        "policy": policy,
                        "gamma": gamma,
                        "seed": seed,
                        "target_rate": args.target_rate,
                        "per_commodity_arrival_rate": per_rate,
                        "interference_model": args.interference_model,
                        "fixed_k": policy_fixed_k,
                        "total_jobs": stats.total_jobs,
                        "completed_jobs": stats.completed_jobs,
                        "pending_jobs": stats.pending_jobs,
                        "job_throughput": stats.completed_jobs / float(args.slots),
                        "job_completion_ratio": stats.completed_jobs / float(max(1, stats.total_jobs)),
                        "avg_delay_completed": stats.avg_delay_completed,
                        "avg_delay_with_penalty": stats.avg_delay_with_penalty,
                        "completed_total_cost_norm_per_job": stats.completed_total_cost_norm_per_job,
                        "completed_total_cost_norm_per_slot": stats.completed_total_cost_norm_per_slot,
                        "routing_oracle_calls": stats.routing_oracle_calls,
                        "routing_cache_hits": stats.routing_cache_hits,
                    }
                    rows.append(row)

        df = pd.DataFrame(rows)
        save_dataframe(df, out_dir / "resource_budget_runs.csv")
        stable_summary, budget_summary = _summarize_budget(
            df,
            baseline_policy=args.baseline_policy,
            completion_threshold=args.completion_threshold,
            delay_threshold=args.delay_threshold,
        )
        save_dataframe(stable_summary, out_dir / "resource_budget_stability_by_gamma.csv")
        save_dataframe(budget_summary, out_dir / "resource_budget_gamma_star.csv")
        save_json(
            {
                "case": args.case_name,
                "config_file": args.config_file,
                "target_rate": args.target_rate,
                "gammas": args.gammas,
                "policies": args.policies,
                "completion_threshold": args.completion_threshold,
                "delay_threshold": args.delay_threshold,
                "baseline_policy": args.baseline_policy,
                "dynamic_edges": {f"{u}->{v}": p for (u, v), p in dynamic_edges.items()},
                "log_file": str(log_path),
            },
            out_dir / "resource_budget_metadata.json",
        )
        logger.info("Resource budget results written to: %s", out_dir)
    finally:
        close_logger(logger)


if __name__ == "__main__":
    main()
