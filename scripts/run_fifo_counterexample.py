from __future__ import annotations

import argparse

import pandas as pd

from dcnc_sim.mapping import FixedMappingSolver
from dcnc_sim.plotting import plot_backlog_series
from dcnc_sim.simulator import CommodityConfig, DCNCSimulator
from dcnc_sim.wireless import AlwaysOnProcess
from dcnc_sim.workloads import make_fifo_counterexample

from common import build_run_logger, close_logger, ensure_dir, save_dataframe


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the FIFO-vs-NTO counterexample simulation.")
    ap.add_argument("--output-dir", default="results/fifo_counterexample")
    ap.add_argument("--slots", type=int, default=2000)
    ap.add_argument("--arrival-rate", type=float, default=0.97)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--progress-every", type=int, default=100)
    args = ap.parse_args()

    out_dir = ensure_dir(args.output_dir)
    logger, _ = build_run_logger("fifo_counterexample", out_dir, "fifo_counterexample")
    net, commodity, fixed_assignment = make_fifo_counterexample()
    wireless = AlwaysOnProcess(net)

    try:
        rows = []
        backlog_series = {}
        logger.info("FIFO counterexample network summary: %s", net.summary())
        for scheduler in ["nto", "fifo"]:
            logger.info("Scheduler start | scheduler=%s | arrival_rate=%.4f | slots=%d", scheduler.upper(), args.arrival_rate, args.slots)
            solver = FixedMappingSolver(net, fixed_assignment, logger=logger)
            sim = DCNCSimulator(
                network=net,
                commodity_cfgs=[CommodityConfig(commodity, args.arrival_rate, solver)],
                wireless_process=wireless,
                total_slots=args.slots,
                seed=args.seed,
                scheduler=scheduler,
                logger=logger,
                run_label=f"fifo_counterexample_{scheduler}",
                progress_every=args.progress_every,
            )
            stats = sim.run()
            rows.append(
                {
                    "scheduler": scheduler.upper(),
                    "arrival_rate": args.arrival_rate,
                    "delivered_packets": stats.delivered_packets,
                    "pending_packets": stats.pending_packets,
                    "avg_delay_completed": stats.avg_delay_completed,
                    "avg_delay_with_penalty": stats.avg_delay_with_penalty,
                    "final_backlog": stats.physical_backlog_series[-1],
                }
            )
            backlog_series[scheduler.upper()] = stats.physical_backlog_series
            logger.info("Scheduler done | scheduler=%s | final_backlog=%d", scheduler.upper(), stats.physical_backlog_series[-1])

        df = pd.DataFrame(rows)
        save_dataframe(df, out_dir / "fifo_counterexample_results.csv")
        plot_backlog_series(backlog_series, out_dir / "fifo_vs_nto_backlog.png")
        logger.info("FIFO counterexample results written to: %s", out_dir)
    finally:
        close_logger(logger)


if __name__ == "__main__":
    main()
