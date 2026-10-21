from __future__ import annotations

import argparse
import shlex
from pathlib import Path

import numpy as np
import pandas as pd

from dcnc_sim.interference import build_activation_policy
from dcnc_sim.mapping import DynVMPBridgeSolver, QueueAwareGreedySolver
from dcnc_sim.simulator import CommodityConfig, DCNCSimulator
from dcnc_sim.wireless import IIDOnOffProcess
from dcnc_sim.workloads import load_legacy_config

from common import build_run_logger, close_logger, ensure_dir, save_dataframe, save_json
from run_edge_experiments import DEFAULT_CASES, PAPER_DYNAMIC_EDGES, _selected_rates, _union_allowed_compute_nodes


def _rate_tag(rate: float) -> str:
    return (f"{rate:g}".replace(".", "p").replace("-", "m"))


def _safe(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-", "p"} else "_" for ch in str(text))


def _runtime_summary(samples: list[float]) -> dict[str, float]:
    if not samples:
        return {
            "oracle_runtime_mean_sec": 0.0,
            "oracle_runtime_median_sec": 0.0,
            "oracle_runtime_p95_sec": 0.0,
            "oracle_runtime_max_sec": 0.0,
        }
    arr = np.asarray(samples, dtype=float)
    return {
        "oracle_runtime_mean_sec": float(np.mean(arr)),
        "oracle_runtime_median_sec": float(np.median(arr)),
        "oracle_runtime_p95_sec": float(np.percentile(arr, 95)),
        "oracle_runtime_max_sec": float(np.max(arr)),
    }


def _build_solver(args: argparse.Namespace, net, seed: int, logger):
    if args.dcnc_solver == "dynvmp_bridge":
        return DynVMPBridgeSolver(
            net,
            bridge_cmd=shlex.split(args.dynvmp_cmd) if args.dynvmp_cmd else None,
            seed=seed,
            logger=logger,
        )
    return QueueAwareGreedySolver(net, seed=seed, logger=logger)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Run runtime-aware asynchronous DCNC-DAG experiments.  In async_reuse mode, "
            "cold-start requests wait for the first mapping; after that, arrivals reuse the "
            "latest ready mapping while the next DynVMP job is computed."
        )
    )
    ap.add_argument("--output-dir", default="results/runtime_aware_async")
    ap.add_argument("--slots", type=int, default=20000)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--seed-start", type=int, default=0)
    ap.add_argument("--progress-every", type=int, default=1000)
    ap.add_argument("--cases", nargs="*", default=["driving_milan", "driving_random"], choices=list(DEFAULT_CASES.keys()))
    ap.add_argument("--rates", nargs="*", type=float, default=None)
    ap.add_argument("--rate", type=float, default=None)
    ap.add_argument("--modes", nargs="*", default=["ideal_fixed_k", "async_reuse"], choices=["ideal_fixed_k", "async_reuse"])
    ap.add_argument("--fixed-k", type=int, default=1, help="K for the ideal_fixed_k baseline.")
    ap.add_argument("--slot-secs", nargs="*", type=float, default=[0.001], help="Physical duration of one simulation slot, in seconds.")
    ap.add_argument("--oracle-workers", type=int, default=1)
    ap.add_argument("--oracle-min-delay-slots", type=int, default=1)
    ap.add_argument("--async-refresh-policy", choices=["continuous", "on_arrival", "none"], default="continuous")
    ap.add_argument("--interference-model", choices=["none", "primary"], default="primary")
    ap.add_argument("--arrival-mode", choices=["poisson", "bounded"], default="poisson")
    ap.add_argument("--dcnc-solver", choices=["greedy", "dynvmp_bridge"], default="dynvmp_bridge")
    ap.add_argument("--dynvmp-cmd", default="bash ./tools/run_dynvmp_bridge.sh")
    ap.add_argument("--record-timeseries", action="store_true", help="Write one per-slot CSV per run. Useful but can be large.")
    args = ap.parse_args()

    out_dir = ensure_dir(args.output_dir)
    detail_dir = ensure_dir(out_dir / "run_details")
    logger, log_path = build_run_logger("runtime_aware", out_dir, "runtime_aware")
    all_rows: list[dict] = []

    try:
        activation_policy = build_activation_policy(args.interference_model)
        logger.info(
            "Runtime-aware experiments | modes=%s | solver=%s | cases=%s | slot_secs=%s | workers=%d | min_delay_slots=%d",
            args.modes,
            args.dcnc_solver,
            args.cases,
            args.slot_secs,
            args.oracle_workers,
            args.oracle_min_delay_slots,
        )
        for case_name in args.cases:
            spec = DEFAULT_CASES[case_name]
            case_dir = ensure_dir(out_dir / case_name)
            net, comms = load_legacy_config(spec.config_file)
            topology_key = "milan" if "milan" in case_name else "random"
            dynamic_edges = {e: spec.p_on for e in PAPER_DYNAMIC_EDGES[topology_key]}
            compute_nodes = _union_allowed_compute_nodes(comms, net)
            rates = _selected_rates(args, spec)
            logger.info("Case=%s | %s | compute_nodes=%d | rates=%s", case_name, net.summary(), len(compute_nodes), rates)

            rows: list[dict] = []
            for slot_sec in args.slot_secs:
                for mode in args.modes:
                    routing_mode = "fixed_k" if mode == "ideal_fixed_k" else "async_refresh"
                    fixed_k = args.fixed_k if mode == "ideal_fixed_k" else 1
                    for rate in rates:
                        per_rate = rate / max(len(comms), 1)
                        for seed in range(args.seed_start, args.seed_start + args.seeds):
                            run_id = _safe(f"{case_name}_{mode}_slot{slot_sec:g}_r{_rate_tag(rate)}_s{seed}")
                            logger.info(
                                "Run start | run_id=%s | case=%s | mode=%s | rate=%.6f | seed=%d | slots=%d | slot_sec=%.6g",
                                run_id,
                                case_name,
                                mode,
                                rate,
                                seed,
                                args.slots,
                                slot_sec,
                            )
                            wireless = IIDOnOffProcess(net, dynamic_edges, seed=1000 + seed)
                            commodity_cfgs = []
                            for idx, commodity in enumerate(comms):
                                solver = _build_solver(args, net, seed=2000 + 100 * idx + seed, logger=logger)
                                commodity_cfgs.append(CommodityConfig(commodity, per_rate, solver))
                            sim = DCNCSimulator(
                                network=net,
                                commodity_cfgs=commodity_cfgs,
                                wireless_process=wireless,
                                total_slots=args.slots,
                                seed=3000 + seed,
                                scheduler="nto",
                                activation_policy=activation_policy,
                                fixed_k=fixed_k,
                                arrival_mode=args.arrival_mode,
                                logger=logger,
                                run_label=run_id,
                                progress_every=args.progress_every,
                                routing_mode=routing_mode,
                                slot_sec=slot_sec,
                                oracle_workers=args.oracle_workers,
                                oracle_min_delay_slots=args.oracle_min_delay_slots,
                                async_refresh_policy=args.async_refresh_policy,
                                record_timeseries=args.record_timeseries,
                            )
                            stats = sim.run()
                            runtime_cols = _runtime_summary(stats.routing_oracle_runtime_samples_sec)
                            dynvmp_exact = args.dcnc_solver == "dynvmp_bridge"
                            row = {
                                "run_id": run_id,
                                "case": case_name,
                                "mode": mode,
                                "routing_mode": routing_mode,
                                "seed": seed,
                                "total_slots": args.slots,
                                "slot_sec": slot_sec,
                                "simulated_time_sec": args.slots * slot_sec,
                                "total_arrival_rate": rate,
                                "per_commodity_arrival_rate": per_rate,
                                "interference_model": args.interference_model,
                                "fixed_k": fixed_k,
                                "dcnc_solver": args.dcnc_solver,
                                "oracle_workers": args.oracle_workers,
                                "oracle_min_delay_slots": args.oracle_min_delay_slots,
                                "async_refresh_policy": args.async_refresh_policy,
                                "avg_delay_completed": stats.avg_delay_completed,
                                "avg_delay_with_penalty": stats.avg_delay_with_penalty,
                                "avg_service_delay_completed": stats.avg_service_delay_completed,
                                "avg_service_delay_with_penalty": stats.avg_service_delay_with_penalty,
                                "avg_packet_control_wait_completed": stats.avg_packet_control_wait_completed,
                                "avg_packet_network_delay_completed": stats.avg_packet_network_delay_completed,
                                "avg_service_control_wait_completed": stats.avg_service_control_wait_completed,
                                "avg_service_network_delay_completed": stats.avg_service_network_delay_completed,
                                "delivered_packets": stats.delivered_packets,
                                "pending_packets": stats.pending_packets,
                                "completed_service_units": stats.completed_service_units,
                                "total_service_units": stats.total_service_units,
                                "pending_service_units": stats.pending_service_units,
                                "routing_oracle_calls": stats.routing_oracle_calls,
                                "routing_cache_hits": stats.routing_cache_hits,
                                "routing_oracle_wall_time_sec": stats.routing_oracle_wall_time_sec,
                                "simulation_wall_time_sec": stats.simulation_wall_time_sec,
                                "dynvmp_calls": stats.routing_oracle_calls if dynvmp_exact else 0,
                                "dynvmp_wall_time_sec": stats.routing_oracle_wall_time_sec if dynvmp_exact else 0.0,
                                "dynvmp_calls_per_slot": stats.routing_oracle_calls / max(args.slots, 1),
                                "dynvmp_time_per_call_ms": (1000.0 * stats.routing_oracle_wall_time_sec / stats.routing_oracle_calls) if stats.routing_oracle_calls else 0.0,
                                "async_mapping_updates": stats.async_mapping_updates,
                                "async_refresh_triggers": stats.async_refresh_triggers,
                                "async_reuse_service_units": stats.async_reuse_service_units,
                                "async_cold_start_buffered_service_units": stats.async_cold_start_buffered_service_units,
                                "async_control_wait_sum_slots_injected": stats.async_control_wait_sum_slots_injected,
                                "async_control_wait_avg_slots_injected": stats.async_control_wait_avg_slots_injected,
                                "async_control_wait_p95_slots_injected": stats.async_control_wait_p95_slots_injected,
                                "async_control_wait_max_slots_injected": stats.async_control_wait_max_slots_injected,
                                "async_effective_update_interval_avg_slots": stats.async_effective_update_interval_avg_slots,
                                "async_mapping_age_avg_slots": stats.async_mapping_age_avg_slots,
                                "async_mapping_age_max_slots": stats.async_mapping_age_max_slots,
                                "async_controller_utilization": stats.async_controller_utilization,
                                "async_controller_queue_wait_sum_slots": stats.async_controller_queue_wait_sum_slots,
                                "final_control_buffer_service_units": stats.control_buffer_sum_series[-1] if stats.control_buffer_sum_series else 0,
                                "mean_physical_backlog": float(np.mean(stats.physical_backlog_series)) if stats.physical_backlog_series else 0.0,
                                "max_physical_backlog": float(np.max(stats.physical_backlog_series)) if stats.physical_backlog_series else 0.0,
                                "mean_vq_link_sum": float(np.mean(stats.vq_link_sum_series)) if stats.vq_link_sum_series else 0.0,
                                "mean_vq_node_sum": float(np.mean(stats.vq_node_sum_series)) if stats.vq_node_sum_series else 0.0,
                                **runtime_cols,
                            }
                            rows.append(row)
                            all_rows.append(row)

                            # Detailed per-run records.
                            jobs_df = pd.DataFrame(stats.oracle_job_records)
                            save_dataframe(jobs_df, detail_dir / f"{run_id}_oracle_jobs.csv")
                            if args.record_timeseries:
                                save_dataframe(pd.DataFrame(stats.timeseries_records), detail_dir / f"{run_id}_timeseries.csv")
                            save_json(
                                {
                                    "run_id": run_id,
                                    "case": case_name,
                                    "mode": mode,
                                    "routing_mode": routing_mode,
                                    "config_file": spec.config_file,
                                    "rate": rate,
                                    "seed": seed,
                                    "slots": args.slots,
                                    "slot_sec": slot_sec,
                                    "solver": args.dcnc_solver,
                                    "dynamic_edges": {f"{u}->{v}": p for (u, v), p in dynamic_edges.items()},
                                    "compute_nodes": compute_nodes,
                                    "log_file": str(log_path),
                                },
                                detail_dir / f"{run_id}_metadata.json",
                            )
                            logger.info(
                                "Run done | run_id=%s | service_delay=%.6f | ctrl_wait=%.6f | network_delay=%.6f | oracle_calls=%d | oracle_time=%.6fs | sim_time=%.6fs | ctrl_util=%.4f",
                                run_id,
                                stats.avg_service_delay_completed,
                                stats.avg_service_control_wait_completed,
                                stats.avg_service_network_delay_completed,
                                stats.routing_oracle_calls,
                                stats.routing_oracle_wall_time_sec,
                                stats.simulation_wall_time_sec,
                                stats.async_controller_utilization,
                            )
            case_df = pd.DataFrame(rows)
            save_dataframe(case_df, case_dir / f"{case_name}_runtime_aware_results.csv")
            save_json(
                {
                    "case": case_name,
                    "config_file": spec.config_file,
                    "rates": rates,
                    "slot_secs": args.slot_secs,
                    "modes": args.modes,
                    "solver": args.dcnc_solver,
                    "interference_model": args.interference_model,
                    "oracle_workers": args.oracle_workers,
                    "oracle_min_delay_slots": args.oracle_min_delay_slots,
                    "async_refresh_policy": args.async_refresh_policy,
                    "log_file": str(log_path),
                },
                case_dir / "case_metadata.json",
            )

        all_df = pd.DataFrame(all_rows)
        save_dataframe(all_df, out_dir / "runtime_aware_all_results.csv")
        logger.info("All runtime-aware results written to: %s", out_dir)
    finally:
        close_logger(logger)


if __name__ == "__main__":
    main()
