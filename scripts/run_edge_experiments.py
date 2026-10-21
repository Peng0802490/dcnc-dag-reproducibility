from __future__ import annotations

import argparse
import shlex
from dataclasses import dataclass

import pandas as pd

from dcnc_sim.interference import build_activation_policy
from dcnc_sim.mapping import (
    DynVMPBridgeSolver,
    ExactDPSolver,
    NearestToSourceSolver,
    QueueAwareGreedySolver,
    RandomSolver,
)
from dcnc_sim.plotting import plot_delay_curve
from dcnc_sim.simulator import CommodityConfig, DCNCSimulator
from dcnc_sim.wireless import IIDOnOffProcess
from dcnc_sim.workloads import load_legacy_config

from common import build_run_logger, close_logger, ensure_dir, save_dataframe, save_json


@dataclass
class CaseSpec:
    name: str
    config_file: str
    rates: list[float]
    p_on: float = 0.8


DEFAULT_CASES = {
    "driving_milan": CaseSpec("driving_milan", "config_driving_Milan.json", [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]),
    "driving_random": CaseSpec("driving_random", "config_driving_Random.json", [0.5, 1.0, 1.5, 2.0, 2.5]),
    "random3_milan": CaseSpec("random3_milan", "config_random3_Milan.json", [0.5, 1.0, 1.5, 2.0]),
    "random3_random": CaseSpec("random3_random", "config_random3_Random.json", [0.5, 1.0, 1.5, 2.0]),
    "random4_milan": CaseSpec("random4_milan", "config_random4_Milan.json", [0.4, 0.8, 1.2, 1.6]),
    "random4_random": CaseSpec("random4_random", "config_random4_Random.json", [0.4, 0.8, 1.2, 1.6]),
    "random5_milan": CaseSpec("random5_milan", "config_random5_Milan.json", [0.4, 0.8, 1.2, 1.6]),
    "random5_random": CaseSpec("random5_random", "config_random5_Random.json", [0.4, 0.8, 1.2, 1.6]),
    "random6_milan": CaseSpec("random6_milan", "config_random6_Milan.json", [0.4, 0.8, 1.2, 1.6]),
    "random6_random": CaseSpec("random6_random", "config_random6_Random.json", [0.4, 0.8, 1.2, 1.6]),
}


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


def _union_allowed_compute_nodes(comms, net):
    allowed = set()
    for commodity in comms:
        for func in commodity.service_dag.nodes_all():
            allowed.update(commodity.allowed_nodes(net, func))
    return sorted(allowed)


def _selected_rates(args: argparse.Namespace, spec: CaseSpec) -> list[float]:
    if args.rate is not None:
        return [float(args.rate)]
    if args.rates:
        return [float(x) for x in args.rates]
    return list(spec.rates)


def main() -> None:
    ap = argparse.ArgumentParser(description="Run dynamic edge-network experiments under ON/OFF wireless access links.")
    ap.add_argument("--output-dir", default="results/edge_experiments")
    ap.add_argument("--slots", type=int, default=800)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--seed-start", type=int, default=0, help="Starting seed index. With --seeds 1, this lets you launch one seed per terminal.")
    ap.add_argument("--progress-every", type=int, default=50)
    ap.add_argument("--fixed-k", type=int, default=1, help="Frame length K for the Fixed-K routing extension. Use 1 for the exact per-slot policy.")
    ap.add_argument(
        "--interference-model",
        choices=["none", "primary"],
        default="none",
        help="Feasible-link-activation model used by the scheduler.",
    )
    ap.add_argument("--dcnc-solver", choices=["greedy", "dynvmp_bridge", "exact_dp"], default="greedy")
    ap.add_argument("--dynvmp-cmd", default=None, help="Command used to invoke the DynVMP bridge when --dcnc-solver dynvmp_bridge is selected.")
    ap.add_argument(
        "--cases",
        nargs="*",
        default=list(DEFAULT_CASES.keys()),
        choices=list(DEFAULT_CASES.keys()),
    )
    ap.add_argument(
        "--policies",
        nargs="*",
        default=["DCNC-DAG", "CTS", "Random"],
        choices=["DCNC-DAG", "CTS", "Random"],
    )
    ap.add_argument(
        "--rates",
        nargs="*",
        type=float,
        default=None,
        help="Optional override for the rate list of every selected case. For a single-point run, prefer --rate.",
    )
    ap.add_argument(
        "--rate",
        type=float,
        default=None,
        help="Run a single total-arrival-rate point. Useful for one-terminal-per-(K,rate,seed) parallelism.",
    )
    args = ap.parse_args()

    out_dir = ensure_dir(args.output_dir)
    logger, log_path = build_run_logger("edge_experiments", out_dir, "edge_experiments")
    all_rows = []

    try:
        activation_policy = build_activation_policy(args.interference_model)
        logger.info(
            "Edge experiments | interference_model=%s | fixed_k=%d | seed_start=%d | seeds=%d | single_rate=%s",
            args.interference_model,
            args.fixed_k,
            args.seed_start,
            args.seeds,
            args.rate,
        )
        for case_name in args.cases:
            spec = DEFAULT_CASES[case_name]
            case_dir = ensure_dir(out_dir / case_name)
            net, comms = load_legacy_config(spec.config_file)
            topology_key = "milan" if "milan" in case_name else "random"
            dynamic_edges = {e: spec.p_on for e in PAPER_DYNAMIC_EDGES[topology_key]}
            compute_nodes = _union_allowed_compute_nodes(comms, net)
            rates = _selected_rates(args, spec)

            logger.info("Case=%s | network=%s | compute_nodes=%s", case_name, net.summary(), compute_nodes)
            logger.info("Case=%s | dynamic ingress-adjacent edges=%s | p_on=%.3f", case_name, dynamic_edges, spec.p_on)

            rows = []
            for policy in args.policies:
                policy_fixed_k = args.fixed_k if policy == "DCNC-DAG" else 1
                for rate in rates:
                    for seed in range(args.seed_start, args.seed_start + args.seeds):
                        logger.info(
                            "Case start | case=%s | policy=%s | total_rate=%.4f | seed=%d | slots=%d",
                            case_name,
                            policy,
                            rate,
                            seed,
                            args.slots,
                        )
                        wireless = IIDOnOffProcess(net, dynamic_edges, seed=1000 + seed)
                        commodity_cfgs = []
                        per_rate = rate / max(len(comms), 1)
                        for idx, commodity in enumerate(comms):
                            if policy == "DCNC-DAG":
                                if args.dcnc_solver == "dynvmp_bridge":
                                    solver = DynVMPBridgeSolver(
                                        net,
                                        bridge_cmd=shlex.split(args.dynvmp_cmd) if args.dynvmp_cmd else None,
                                        seed=2000 + 100 * idx + seed,
                                        logger=logger,
                                    )
                                elif args.dcnc_solver == "exact_dp":
                                    solver = ExactDPSolver(net, seed=2000 + 100 * idx + seed, logger=logger)
                                else:
                                    solver = QueueAwareGreedySolver(net, seed=2000 + 100 * idx + seed, logger=logger)
                            elif policy == "CTS":
                                solver = NearestToSourceSolver(net, seed=2000 + 100 * idx + seed, logger=logger)
                            else:
                                solver = RandomSolver(net, seed=2000 + 100 * idx + seed, logger=logger)
                            commodity_cfgs.append(CommodityConfig(commodity, per_rate, solver))
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
                            run_label=f"{case_name}_{policy}_rate{rate:.4f}_seed{seed}",
                            progress_every=args.progress_every,
                        )
                        stats = sim.run()
                        is_dynvmp_exact = policy == "DCNC-DAG" and args.dcnc_solver in ("dynvmp_bridge", "exact_dp")
                        row = {
                            "case": case_name,
                            "policy": policy,
                            "seed": seed,
                            "total_slots": args.slots,
                            "total_arrival_rate": rate,
                            "per_commodity_arrival_rate": per_rate,
                            "interference_model": args.interference_model,
                            "fixed_k": policy_fixed_k,
                            "dcnc_solver": args.dcnc_solver if policy == "DCNC-DAG" else "",
                            "avg_delay_completed": stats.avg_delay_completed,
                            "avg_delay_with_penalty": stats.avg_delay_with_penalty,
                            "delivered_packets": stats.delivered_packets,
                            "pending_packets": stats.pending_packets,
                            "dynamic_edges": len(dynamic_edges),
                            "num_compute_nodes": len(compute_nodes),
                            "routing_oracle_calls": stats.routing_oracle_calls,
                            "routing_cache_hits": stats.routing_cache_hits,
                            "routing_oracle_wall_time_sec": stats.routing_oracle_wall_time_sec,
                            "simulation_wall_time_sec": stats.simulation_wall_time_sec,
                            "dynvmp_calls": stats.routing_oracle_calls if is_dynvmp_exact else 0,
                            "dynvmp_wall_time_sec": stats.routing_oracle_wall_time_sec if is_dynvmp_exact else 0.0,
                        }
                        rows.append(row)
                        all_rows.append(row)
                        logger.info(
                            "Case done | case=%s | policy=%s | total_rate=%.4f | seed=%d | delivered=%d | pending=%d | avg_delay_penalty=%.6f | oracle_calls=%d | oracle_time=%.6fs | sim_time=%.6fs | cache_hits=%d",
                            case_name,
                            policy,
                            rate,
                            seed,
                            stats.delivered_packets,
                            stats.pending_packets,
                            stats.avg_delay_with_penalty,
                            stats.routing_oracle_calls,
                            stats.routing_oracle_wall_time_sec,
                            stats.simulation_wall_time_sec,
                            stats.routing_cache_hits,
                        )
            df = pd.DataFrame(rows)
            save_dataframe(df, case_dir / f"{case_name}_results.csv")
            if not df.empty:
                grouped = df.groupby(["policy", "total_arrival_rate"], as_index=False)["avg_delay_with_penalty"].mean()
                plot_delay_curve(
                    grouped,
                    x="total_arrival_rate",
                    y="avg_delay_with_penalty",
                    hue="policy",
                    out_path=case_dir / f"{case_name}_delay_curve.png",
                    xlabel="Total arrival rate per slot",
                    ylabel="Average delay with unfinished-packet penalty",
                )
            save_json(
                {
                    "case": case_name,
                    "config_file": spec.config_file,
                    "compute_nodes": compute_nodes,
                    "dynamic_edges": {f"{u}->{v}": p for (u, v), p in dynamic_edges.items()},
                    "p_on": spec.p_on,
                    "interference_model": args.interference_model,
                    "fixed_k": args.fixed_k,
                    "dcnc_solver": args.dcnc_solver,
                    "seed_start": args.seed_start,
                    "seeds": args.seeds,
                    "rates": rates,
                    "single_rate": args.rate,
                    "log_file": str(log_path),
                },
                case_dir / "case_metadata.json",
            )
            logger.info("Finished case: %s", case_name)

        save_dataframe(pd.DataFrame(all_rows), out_dir / "edge_experiments_all_results.csv")
        logger.info("All edge-experiment results written to: %s", out_dir)
    finally:
        close_logger(logger)


if __name__ == "__main__":
    main()
