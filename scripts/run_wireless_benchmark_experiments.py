from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path

import pandas as pd

from dcnc_sim.interference import build_activation_policy
from dcnc_sim.mapping import DynVMPBridgeSolver, NearestToSourceSolver, QueueAwareGreedySolver, RandomSolver
from dcnc_sim.plotting import plot_delay_curve
from dcnc_sim.simulator import CommodityConfig, DCNCSimulator
from dcnc_sim.wireless import IIDOnOffProcess
from dcnc_sim.workloads import LEGACY_ROOT, load_legacy_config

from common import build_run_logger, close_logger, ensure_dir, save_dataframe, save_json

DEFAULT_CASES = {
    "flocklab_random3": "config_random3_FlockLab.json",
    "flocklab_random4": "config_random4_FlockLab.json",
    "flocklab_random5": "config_random5_FlockLab.json",
    "flocklab_random6": "config_random6_FlockLab.json",
    "flocklab_driving": "config_driving_FlockLab.json",
    "roofnet_random3": "config_random3_Roofnet38.json",
    "roofnet_random4": "config_random4_Roofnet38.json",
    "roofnet_random5": "config_random5_Roofnet38.json",
    "roofnet_random6": "config_random6_Roofnet38.json",
    "roofnet_driving": "config_driving_Roofnet38.json",
}

DEFAULT_RATES = [0.005, 0.01, 0.02, 0.05, 0.1, 0.2]


def dynamic_edges_from_config(config_name: str) -> dict[tuple[str, str], float]:
    cfg_path = LEGACY_ROOT / config_name
    with cfg_path.open("r", encoding="utf-8") as f:
        cfg = json.load(f)
    network_path = LEGACY_ROOT / cfg["network"]["file"]
    with network_path.open("r", encoding="utf-8") as f:
        net_json = json.load(f)
    dynamic: dict[tuple[str, str], float] = {}
    for e in net_json.get("edges", []):
        if bool(e.get("dynamic", False)):
            dynamic[(str(e["from"]), str(e["to"]))] = float(e.get("p_on", 1.0))
    return dynamic


def _union_allowed_compute_nodes(comms, net):
    allowed = set()
    for commodity in comms:
        for func in commodity.service_dag.nodes_all():
            allowed.update(commodity.allowed_nodes(net, func))
    return sorted(allowed)


def main() -> None:
    ap = argparse.ArgumentParser(description="Run Roofnet/FlockLab wireless benchmark experiments.")
    ap.add_argument("--output-dir", default="results/wireless_benchmarks")
    ap.add_argument("--case", choices=sorted(DEFAULT_CASES), required=True)
    ap.add_argument("--slots", type=int, default=8000)
    ap.add_argument("--seed-start", type=int, default=0)
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--progress-every", type=int, default=200)
    ap.add_argument("--rate", type=float, default=None)
    ap.add_argument("--rates", nargs="*", type=float, default=None)
    ap.add_argument("--fixed-k", type=int, default=1)
    ap.add_argument("--interference-model", choices=["none", "primary"], default="primary")
    ap.add_argument("--dcnc-solver", choices=["greedy", "dynvmp_bridge"], default="greedy")
    ap.add_argument("--dynvmp-cmd", default=None)
    ap.add_argument("--policies", nargs="*", default=["DCNC-DAG", "CTS", "Random"], choices=["DCNC-DAG", "CTS", "Random"])
    args = ap.parse_args()

    config_name = DEFAULT_CASES[args.case]
    rates = [args.rate] if args.rate is not None else (args.rates if args.rates else DEFAULT_RATES)
    out_dir = ensure_dir(Path(args.output_dir) / args.case)
    logger, log_path = build_run_logger("wireless_benchmark", out_dir, "wireless_benchmark")
    all_rows = []
    try:
        net, comms = load_legacy_config(config_name)
        dynamic_edges = dynamic_edges_from_config(config_name)
        compute_nodes = _union_allowed_compute_nodes(comms, net)
        activation_policy = build_activation_policy(args.interference_model)
        logger.info("Wireless benchmark start | case=%s | config=%s | network=%s | dynamic_edges=%d", args.case, config_name, net.summary(), len(dynamic_edges), extra={"console": True})
        rows = []
        for policy in args.policies:
            policy_fixed_k = args.fixed_k if policy == "DCNC-DAG" else 1
            for rate in rates:
                for seed in range(args.seed_start, args.seed_start + args.seeds):
                    logger.info("Case start | case=%s | policy=%s | rate=%.6f | seed=%d | slots=%d", args.case, policy, rate, seed, args.slots, extra={"console": True})
                    wireless = IIDOnOffProcess(net, dynamic_edges, seed=1000 + seed)
                    commodity_cfgs = []
                    per_rate = float(rate) / max(len(comms), 1)
                    for idx, commodity in enumerate(comms):
                        if policy == "DCNC-DAG":
                            if args.dcnc_solver == "dynvmp_bridge":
                                solver = DynVMPBridgeSolver(net, bridge_cmd=shlex.split(args.dynvmp_cmd) if args.dynvmp_cmd else None, seed=2000 + 100 * idx + seed, logger=logger)
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
                        run_label=f"{args.case}_{policy}_rate{rate:.6f}_seed{seed}",
                        progress_every=args.progress_every,
                    )
                    stats = sim.run()
                    is_dynvmp_exact = policy == "DCNC-DAG" and args.dcnc_solver == "dynvmp_bridge"
                    row = {
                        "case": args.case,
                        "config": config_name,
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
                    logger.info("Case done | case=%s | policy=%s | rate=%.6f | seed=%d | delivered=%d | pending=%d | avg_delay_penalty=%.6f | oracle_calls=%d | oracle_time=%.6fs | sim_time=%.6fs", args.case, policy, rate, seed, stats.delivered_packets, stats.pending_packets, stats.avg_delay_with_penalty, stats.routing_oracle_calls, stats.routing_oracle_wall_time_sec, stats.simulation_wall_time_sec, extra={"console": True})
        df = pd.DataFrame(rows)
        save_dataframe(df, out_dir / f"{args.case}_results.csv")
        save_dataframe(pd.DataFrame(all_rows), out_dir / "wireless_benchmark_all_results.csv")
        if not df.empty:
            grouped = df.groupby(["policy", "total_arrival_rate"], as_index=False)["avg_delay_with_penalty"].mean()
            plot_delay_curve(grouped, x="total_arrival_rate", y="avg_delay_with_penalty", hue="policy", out_path=out_dir / f"{args.case}_delay_curve.png", xlabel="Total arrival rate per slot", ylabel="Average delay with unfinished-packet penalty")
        save_json({"case": args.case, "config": config_name, "network": net.summary(), "compute_nodes": compute_nodes, "dynamic_edges": len(dynamic_edges), "log_file": str(log_path), "rates": rates}, out_dir / "case_metadata.json")
        logger.info("Wireless benchmark results written to: %s", out_dir, extra={"console": True})
    finally:
        close_logger(logger)


if __name__ == "__main__":
    main()
