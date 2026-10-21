from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path
from typing import Dict, Iterable, List

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Make this script executable both through ``python scripts/...`` and from IDEs.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import build_run_logger, close_logger, ensure_dir, save_dataframe, save_json

from dcnc_sim.capacity_gurobi import (
    CapacityLPResult,
    solve_single_commodity_capacity_gurobi,
    solve_single_commodity_capacity_scipy,
)
from dcnc_sim.interference import build_activation_policy
from dcnc_sim.mapping import DynVMPBridgeSolver, ExactEnumerationSolver, enumerate_all_valid_mappings_small
from dcnc_sim.simulator import CommodityConfig, DCNCSimulator
from dcnc_sim.synthetic_instances import get_synthetic_throughput_cases, list_synthetic_throughput_cases
from dcnc_sim.wireless import AlwaysOnProcess, IIDOnOffProcess


def _tail_slope(values: List[float], start_fraction: float = 0.5) -> float:
    if len(values) < 4:
        return 0.0
    start = int(len(values) * start_fraction)
    y = np.asarray(values[start:], dtype=float)
    x = np.arange(len(y), dtype=float)
    if len(y) < 2:
        return 0.0
    slope = np.polyfit(x, y, 1)[0]
    return float(slope)


def _make_solver(name: str, net, seed: int, logger, dynvmp_cmd: str | None):
    key = name.strip().lower()
    if key in {"exact", "exact_enum", "enumeration"}:
        return ExactEnumerationSolver(net, seed=seed, logger=logger)
    if key in {"dynvmp", "dynvmp_bridge"}:
        bridge_cmd = None
        if dynvmp_cmd:
            import shlex

            bridge_cmd = shlex.split(dynvmp_cmd)
        return DynVMPBridgeSolver(net, bridge_cmd=bridge_cmd, seed=seed, logger=logger)
    raise ValueError(f"unknown DCNC solver: {name}")


def _solve_capacity(args, case, activation_policy, mappings, logger) -> CapacityLPResult:
    if args.lp_solver == "gurobi":
        logger.info("Solving capacity LP with Gurobi | case=%s | mappings=%d", case.name, len(mappings))
        return solve_single_commodity_capacity_gurobi(
            network=case.network,
            dag=case.commodity.service_dag,
            commodity=case.commodity,
            mappings=mappings,
            dynamic_edge_p_on=case.dynamic_edge_p_on,
            activation_policy=activation_policy,
            time_limit=args.gurobi_time_limit,
            output_flag=args.gurobi_output,
        )
    logger.info("Solving capacity LP with SciPy fallback | case=%s | mappings=%d", case.name, len(mappings))
    return solve_single_commodity_capacity_scipy(
        network=case.network,
        dag=case.commodity.service_dag,
        commodity=case.commodity,
        mappings=mappings,
        dynamic_edge_p_on=case.dynamic_edge_p_on,
        activation_policy=activation_policy,
    )


def _plot_case_factor_summary(factor_df: pd.DataFrame, case_name: str, lambda_star: float, out_dir: Path) -> None:
    sub = factor_df[factor_df["case"] == case_name].copy()
    if sub.empty:
        return
    x = sub["arrival_rate"].to_numpy(dtype=float)

    fig = plt.figure(figsize=(5.0, 3.2))
    plt.plot(x, sub["mean_completed_service_throughput"], marker="o", label="DCNC-DAG simulated throughput")
    plt.plot(x, x, linestyle="--", label="offered load")
    plt.axvline(lambda_star, linestyle=":", label=r"LP $\lambda^\star$")
    plt.xlabel("Arrival rate")
    plt.ylabel("Service-unit throughput")
    plt.title(case_name)
    plt.legend(fontsize=8)
    plt.tight_layout()
    fig.savefig(out_dir / f"{case_name}_throughput_vs_lp.pdf")
    fig.savefig(out_dir / f"{case_name}_throughput_vs_lp.png", dpi=220)
    plt.close(fig)

    fig = plt.figure(figsize=(5.0, 3.2))
    plt.plot(sub["load_factor"], sub["mean_completion_ratio"], marker="o", label="completion ratio")
    plt.axvline(1.0, linestyle=":", label=r"LP boundary")
    plt.ylim(0.0, 1.05)
    plt.xlabel(r"Normalized load $\lambda/\lambda^\star$")
    plt.ylabel("Completed service units / admitted service units")
    plt.title(case_name)
    plt.legend(fontsize=8)
    plt.tight_layout()
    fig.savefig(out_dir / f"{case_name}_completion_ratio.pdf")
    fig.savefig(out_dir / f"{case_name}_completion_ratio.png", dpi=220)
    plt.close(fig)


def _latex_case_summary(case_summary: pd.DataFrame, out_path: Path) -> None:
    cols = [
        "case",
        "lp_lambda_star",
        "empirical_max_stable_rate",
        "relative_gap",
        "near_lp_supported",
        "above_lp_rejected",
    ]
    df = case_summary[cols].copy()
    rename = {
        "case": "Instance",
        "lp_lambda_star": r"LP $\lambda^\star$",
        "empirical_max_stable_rate": r"Sim. $\hat\lambda$",
        "relative_gap": "Rel. gap",
        "near_lp_supported": r"$<\lambda^\star$ stable",
        "above_lp_rejected": r"$>\lambda^\star$ unstable",
    }
    df = df.rename(columns=rename)
    with out_path.open("w", encoding="utf-8") as f:
        f.write(df.to_latex(index=False, float_format=lambda x: f"{x:.4f}", escape=False))


def main() -> None:
    available_cases = get_synthetic_throughput_cases()
    ap = argparse.ArgumentParser(description="Validate DCNC-DAG throughput optimality on small synthetic instances by LP-vs-simulation comparison.")
    ap.add_argument("--output-dir", default="results/throughput_optimality_validation")
    ap.add_argument("--cases", nargs="*", default=list_synthetic_throughput_cases(), choices=list_synthetic_throughput_cases())
    ap.add_argument("--slots", type=int, default=20000)
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--fixed-k", type=int, default=1, help="Use K=1 for exact per-slot DCNC-DAG; fixed K>1 can also be checked.")
    ap.add_argument("--dcnc-solver", choices=["exact_enum", "dynvmp_bridge"], default="exact_enum")
    ap.add_argument("--dynvmp-cmd", default=os.environ.get("DCNC_DYNVMP_CMD", ""))
    ap.add_argument("--lp-solver", choices=["gurobi", "scipy"], default="gurobi")
    ap.add_argument("--gurobi-time-limit", type=float, default=None)
    ap.add_argument("--gurobi-output", action="store_true")
    ap.add_argument(
        "--factors",
        type=float,
        nargs="*",
        default=[0.70, 0.85, 0.95, 0.99, 1.01, 1.05, 1.10],
        help="Offered-load factors relative to LP lambda*.",
    )
    ap.add_argument("--progress-every", type=int, default=1000)
    ap.add_argument("--arrival-mode", choices=["bounded", "poisson"], default="bounded", help="Use bounded arrivals by default to match the bounded-arrival assumption.")
    ap.add_argument("--stable-completion-ratio", type=float, default=0.98)
    ap.add_argument("--stable-physical-slope", type=float, default=5.0e-2)
    ap.add_argument("--stable-virtual-slope", type=float, default=5.0e-2)
    ap.add_argument("--stable-fraction", type=float, default=0.6, help="A factor is treated as stable if at least this fraction of seeds pass the stability checks.")
    args = ap.parse_args()

    out_dir = ensure_dir(args.output_dir)
    logger, log_path = build_run_logger("throughput_optimality_validation", out_dir, "throughput_validation")

    try:
        lp_rows = []
        run_rows = []
        metadata = {
            "slots": args.slots,
            "seeds": args.seeds,
            "fixed_k": args.fixed_k,
            "dcnc_solver": args.dcnc_solver,
            "lp_solver": args.lp_solver,
            "arrival_mode": args.arrival_mode,
            "factors": args.factors,
            "log_file": str(log_path),
        }

        for case_name in args.cases:
            case = available_cases[case_name]
            activation_policy = build_activation_policy(case.default_interference_model)
            logger.info("=== Case %s ===", case.name)
            logger.info("Description: %s", case.description)
            logger.info("Network: %s", case.network.summary())
            logger.info("DAG: %s", case.commodity.service_dag.summary())
            logger.info("Interference model: %s", case.default_interference_model)
            logger.info("Dynamic ON/OFF edges: %s", case.dynamic_edge_p_on)

            mappings = enumerate_all_valid_mappings_small(case.network, case.commodity.service_dag, case.commodity)
            lp_res = _solve_capacity(args, case, activation_policy, mappings, logger)
            lambda_star = lp_res.objective
            logger.info("LP done | case=%s | lambda*=%.8f | mappings=%d", case.name, lambda_star, len(mappings))
            lp_rows.append(
                {
                    "case": case.name,
                    "description": case.description,
                    "lp_lambda_star": lambda_star,
                    "lp_solver": lp_res.solver,
                    "lp_status": lp_res.status,
                    "num_valid_mappings": lp_res.num_mappings,
                    "interference_model": case.default_interference_model,
                    "dynamic_edges": ";".join(f"{u}->{v}:{p}" for (u, v), p in sorted(case.dynamic_edge_p_on.items())),
                }
            )

            for factor in args.factors:
                arrival_rate = float(factor) * lambda_star
                for seed_idx in range(args.seeds):
                    logger.info(
                        "Run start | case=%s | factor=%.4f | arrival=%.8f | seed=%d",
                        case.name,
                        factor,
                        arrival_rate,
                        seed_idx,
                    )
                    wireless_seed = 10000 + 101 * seed_idx
                    if case.dynamic_edge_p_on:
                        wireless_process = IIDOnOffProcess(case.network, case.dynamic_edge_p_on, seed=wireless_seed)
                    else:
                        wireless_process = AlwaysOnProcess(case.network)
                    solver = _make_solver(args.dcnc_solver, case.network, seed=20000 + seed_idx, logger=logger, dynvmp_cmd=args.dynvmp_cmd or None)
                    sim = DCNCSimulator(
                        network=case.network,
                        commodity_cfgs=[CommodityConfig(case.commodity, arrival_rate, solver)],
                        wireless_process=wireless_process,
                        total_slots=args.slots,
                        seed=30000 + seed_idx,
                        scheduler="nto",
                        activation_policy=activation_policy,
                        fixed_k=args.fixed_k,
                        arrival_mode=args.arrival_mode,
                        logger=logger,
                        run_label=f"{case.name}_f{factor:.4f}_seed{seed_idx}",
                        progress_every=args.progress_every,
                    )
                    stats = sim.run()
                    completed = int(stats.completed_service_units)
                    total = int(stats.total_service_units)
                    pending_service = int(stats.pending_service_units)
                    completion_ratio = completed / total if total > 0 else 1.0
                    achieved_service_throughput = completed / float(args.slots)
                    physical_slope = _tail_slope(stats.physical_backlog_series)
                    virtual_total = [a + b for a, b in zip(stats.vq_link_sum_series, stats.vq_node_sum_series)]
                    virtual_slope = _tail_slope(virtual_total)
                    stable = (
                        completion_ratio >= args.stable_completion_ratio
                        and physical_slope <= args.stable_physical_slope
                        and virtual_slope <= args.stable_virtual_slope
                    )
                    row = {
                        "case": case.name,
                        "seed": seed_idx,
                        "load_factor": float(factor),
                        "arrival_rate": arrival_rate,
                        "lp_lambda_star": lambda_star,
                        "completed_service_units": completed,
                        "total_service_units": total,
                        "pending_service_units": pending_service,
                        "completion_ratio": completion_ratio,
                        "achieved_service_throughput": achieved_service_throughput,
                        "avg_service_delay_completed": stats.avg_service_delay_completed,
                        "avg_packet_delay_completed": stats.avg_delay_completed,
                        "avg_packet_delay_with_penalty": stats.avg_delay_with_penalty,
                        "physical_tail_slope": physical_slope,
                        "virtual_tail_slope": virtual_slope,
                        "final_physical_backlog": stats.physical_backlog_series[-1] if stats.physical_backlog_series else 0.0,
                        "final_virtual_backlog": virtual_total[-1] if virtual_total else 0.0,
                        "routing_oracle_calls": stats.routing_oracle_calls,
                        "routing_cache_hits": stats.routing_cache_hits,
                        "stable_flag": bool(stable),
                        "fixed_k": args.fixed_k,
                        "dcnc_solver": args.dcnc_solver,
                    }
                    run_rows.append(row)
                    logger.info(
                        "Run done | case=%s | factor=%.4f | seed=%d | throughput=%.8f | completed=%d/%d | ratio=%.4f | physical_slope=%.6g | virtual_slope=%.6g | stable=%s",
                        case.name,
                        factor,
                        seed_idx,
                        achieved_service_throughput,
                        completed,
                        total,
                        completion_ratio,
                        physical_slope,
                        virtual_slope,
                        stable,
                    )

        lp_df = pd.DataFrame(lp_rows)
        runs_df = pd.DataFrame(run_rows)
        save_dataframe(lp_df, out_dir / "throughput_lp_summary.csv")
        save_dataframe(runs_df, out_dir / "throughput_validation_runs.csv")

        factor_summary = (
            runs_df.groupby(["case", "load_factor", "arrival_rate", "lp_lambda_star"], as_index=False)
            .agg(
                mean_completed_service_throughput=("achieved_service_throughput", "mean"),
                std_completed_service_throughput=("achieved_service_throughput", "std"),
                mean_completion_ratio=("completion_ratio", "mean"),
                mean_physical_tail_slope=("physical_tail_slope", "mean"),
                mean_virtual_tail_slope=("virtual_tail_slope", "mean"),
                stable_fraction=("stable_flag", "mean"),
                mean_pending_service_units=("pending_service_units", "mean"),
            )
            .sort_values(["case", "load_factor"])
        )
        factor_summary["factor_stable"] = factor_summary["stable_fraction"] >= float(args.stable_fraction)
        save_dataframe(factor_summary, out_dir / "throughput_validation_factor_summary.csv")

        case_rows = []
        for case_name, sub in factor_summary.groupby("case"):
            sub = sub.sort_values("load_factor")
            lambda_star = float(sub["lp_lambda_star"].iloc[0])
            stable_sub = sub[sub["factor_stable"]]
            empirical_max_stable_rate = float(stable_sub["arrival_rate"].max()) if not stable_sub.empty else 0.0
            empirical_max_stable_factor = empirical_max_stable_rate / lambda_star if lambda_star > 0 else math.nan
            below = sub[sub["load_factor"] < 1.0]
            above = sub[sub["load_factor"] > 1.0]
            near_below = below.iloc[(below["load_factor"] - 1.0).abs().argmin()] if not below.empty else None
            near_above = above.iloc[(above["load_factor"] - 1.0).abs().argmin()] if not above.empty else None
            near_lp_supported = bool(near_below["factor_stable"]) if near_below is not None else False
            above_lp_rejected = bool(not near_above["factor_stable"]) if near_above is not None else False
            case_rows.append(
                {
                    "case": case_name,
                    "lp_lambda_star": lambda_star,
                    "empirical_max_stable_rate": empirical_max_stable_rate,
                    "empirical_max_stable_factor": empirical_max_stable_factor,
                    "relative_gap": (empirical_max_stable_rate - lambda_star) / lambda_star if lambda_star > 0 else math.nan,
                    "near_lp_supported": near_lp_supported,
                    "above_lp_rejected": above_lp_rejected,
                    "nearest_below_factor": float(near_below["load_factor"]) if near_below is not None else math.nan,
                    "nearest_above_factor": float(near_above["load_factor"]) if near_above is not None else math.nan,
                }
            )
            _plot_case_factor_summary(factor_summary, case_name, lambda_star, out_dir)

        case_summary = pd.DataFrame(case_rows).sort_values("case")
        save_dataframe(case_summary, out_dir / "throughput_validation_case_summary.csv")
        _latex_case_summary(case_summary, out_dir / "throughput_validation_case_summary.tex")
        save_json(metadata, out_dir / "throughput_validation_metadata.json")

        logger.info("Results written to %s", out_dir)
        logger.info("Case summary:\n%s", case_summary.to_string(index=False))
    finally:
        close_logger(logger)


if __name__ == "__main__":
    main()
