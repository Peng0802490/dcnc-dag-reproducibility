from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from dcnc_sim.capacity import maximum_single_commodity_rate, maximum_single_commodity_rate_iid_onoff_with_activation
from dcnc_sim.interference import build_activation_policy
from dcnc_sim.mapping import ExactEnumerationSolver, NearestToSourceSolver, RandomSolver, enumerate_all_valid_mappings_small
from dcnc_sim.plotting import plot_backlog_series, plot_delay_curve
from dcnc_sim.simulator import CommodityConfig, DCNCSimulator
from dcnc_sim.wireless import IIDOnOffProcess
from dcnc_sim.workloads import make_grid_boundary_case

from common import build_run_logger, close_logger, ensure_dir, save_dataframe, save_json


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the small-grid boundary-validation experiment.")
    ap.add_argument("--output-dir", default="results/boundary_validation")
    ap.add_argument("--slots", type=int, default=600)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--progress-every", type=int, default=50)
    ap.add_argument("--fixed-k", type=int, default=1, help="Frame length K for the Fixed-K routing extension. Use 1 for the exact policy.")
    ap.add_argument(
        "--interference-model",
        choices=["none", "primary"],
        default="none",
        help="Interference model used by the physical/virtual scheduler and by the exact small-network capacity LP.",
    )
    ap.add_argument(
        "--factors",
        type=float,
        nargs="*",
        default=[0.70, 0.80, 0.90, 0.95, 0.99, 1.05, 1.10],
        help="Normalized offered loads relative to lambda*.",
    )
    args = ap.parse_args()

    out_dir = ensure_dir(args.output_dir)
    logger, log_path = build_run_logger("boundary_validation", out_dir, "boundary_validation")

    try:
        net, commodity, dynamic_edges = make_grid_boundary_case()
        wireless = IIDOnOffProcess(net, dynamic_edges, seed=1)
        activation_policy = build_activation_policy(args.interference_model)
        logger.info("Boundary network summary: %s", net.summary())
        logger.info("Boundary commodity: %s | DAG=%s", commodity.name, commodity.service_dag.summary())
        logger.info("Dynamic wireless edges: %s", dynamic_edges)
        logger.info("Interference model: %s | fixed_k=%d", args.interference_model, args.fixed_k)

        all_mappings = enumerate_all_valid_mappings_small(net, commodity.service_dag, commodity)
        if args.interference_model == "none":
            lambda_star = maximum_single_commodity_rate(
                net,
                commodity.service_dag,
                commodity,
                all_mappings,
                wireless.average_capacities(),
            )
        else:
            lambda_star = maximum_single_commodity_rate_iid_onoff_with_activation(
                net,
                commodity.service_dag,
                commodity,
                all_mappings,
                dynamic_edges,
                activation_policy,
            )
        logger.info("Theoretical lambda*: %.6f", lambda_star)
        logger.info("Enumerated valid mappings: %d", len(all_mappings))

        rows = []
        policies = [
            ("DCNC-DAG", ExactEnumerationSolver),
            ("CTS", NearestToSourceSolver),
            ("Random", RandomSolver),
        ]
        for policy_name, solver_cls in policies:
            policy_fixed_k = args.fixed_k if policy_name == "DCNC-DAG" else 1
            for factor in args.factors:
                for seed in range(args.seeds):
                    logger.info(
                        "Case start | policy=%s | factor=%.3f | seed=%d | arrival_rate=%.6f",
                        policy_name,
                        factor,
                        seed,
                        factor * lambda_star,
                    )
                    wireless_proc = IIDOnOffProcess(net, dynamic_edges, seed=1000 + seed)
                    solver = solver_cls(net, seed=2000 + seed, logger=logger)
                    sim = DCNCSimulator(
                        network=net,
                        commodity_cfgs=[CommodityConfig(commodity, factor * lambda_star, solver)],
                        wireless_process=wireless_proc,
                        total_slots=args.slots,
                        seed=3000 + seed,
                        scheduler="nto",
                        activation_policy=activation_policy,
                        fixed_k=policy_fixed_k,
                        logger=logger,
                        run_label=f"{policy_name}_factor{factor:.3f}_seed{seed}",
                        progress_every=args.progress_every,
                    )
                    stats = sim.run()
                    row = {
                        "policy": policy_name,
                        "seed": seed,
                        "load_factor": factor,
                        "arrival_rate": factor * lambda_star,
                        "lambda_star": lambda_star,
                        "interference_model": args.interference_model,
                        "fixed_k": policy_fixed_k,
                        "avg_delay_completed": stats.avg_delay_completed,
                        "avg_delay_with_penalty": stats.avg_delay_with_penalty,
                        "delivered_packets": stats.delivered_packets,
                        "pending_packets": stats.pending_packets,
                        "routing_oracle_calls": stats.routing_oracle_calls,
                        "routing_cache_hits": stats.routing_cache_hits,
                    }
                    rows.append(row)
                    logger.info(
                        "Case done | policy=%s | factor=%.3f | seed=%d | delivered=%d | pending=%d | avg_delay_penalty=%.6f | oracle_calls=%d | cache_hits=%d",
                        policy_name,
                        factor,
                        seed,
                        stats.delivered_packets,
                        stats.pending_packets,
                        stats.avg_delay_with_penalty,
                        stats.routing_oracle_calls,
                        stats.routing_cache_hits,
                    )
        df = pd.DataFrame(rows)
        save_dataframe(df, out_dir / "boundary_delay_results.csv")

        grouped = df.groupby(["policy", "load_factor"], as_index=False)["avg_delay_with_penalty"].mean()
        plot_delay_curve(
            grouped,
            x="load_factor",
            y="avg_delay_with_penalty",
            hue="policy",
            out_path=out_dir / "boundary_delay_curve.png",
            xlabel=r"Normalized load $\lambda/\lambda^{\star}$",
            ylabel="Average delay with unfinished-packet penalty",
            vline=1.0,
        )

        backlog_series = {}
        backlog_rows = []
        for factor in [0.95, 0.99, 1.05]:
            logger.info("Backlog series run | factor=%.2f", factor)
            wireless_proc = IIDOnOffProcess(net, dynamic_edges, seed=9000 + int(100 * factor))
            solver = ExactEnumerationSolver(net, seed=9100 + int(100 * factor), logger=logger)
            sim = DCNCSimulator(
                network=net,
                commodity_cfgs=[CommodityConfig(commodity, factor * lambda_star, solver)],
                wireless_process=wireless_proc,
                total_slots=args.slots,
                seed=9200 + int(100 * factor),
                scheduler="nto",
                activation_policy=activation_policy,
                fixed_k=args.fixed_k,
                logger=logger,
                run_label=f"backlog_factor{factor:.2f}",
                progress_every=args.progress_every,
            )
            stats = sim.run()
            total_virtual_backlog = [a + b for a, b in zip(stats.vq_link_sum_series, stats.vq_node_sum_series)]
            backlog_series[rf"{factor:.2f}$\lambda^*$"] = total_virtual_backlog
            backlog_rows.extend(
                {"load_factor": factor, "slot": slot, "total_virtual_backlog": val}
                for slot, val in enumerate(total_virtual_backlog)
            )
        save_dataframe(pd.DataFrame(backlog_rows), out_dir / "boundary_backlog_series.csv")
        plot_backlog_series(
            backlog_series,
            out_dir / "boundary_backlog_series.png",
            ylabel="Total virtual backlog",
        )

        save_json(
            {
                "lambda_star": lambda_star,
                "num_valid_mappings": len(all_mappings),
                "dynamic_edges": {f"{u}->{v}": p for (u, v), p in dynamic_edges.items()},
                "interference_model": args.interference_model,
                "fixed_k": args.fixed_k,
                "log_file": str(log_path),
            },
            out_dir / "boundary_metadata.json",
        )

        logger.info("Boundary-validation results written to: %s", out_dir)
        logger.info("Theoretical lambda*: %.6f", lambda_star)
    finally:
        close_logger(logger)


if __name__ == "__main__":
    main()
