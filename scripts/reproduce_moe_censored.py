"""Regenerate the latest MoE figure data and a portable numeric redraw."""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

if __package__:
    from .verify_moe_censored import ROOT, displayed_rows, read_csv, verify_results
else:
    from verify_moe_censored import ROOT, displayed_rows, read_csv, verify_results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-figures", action="store_true")
    args = parser.parse_args()
    print(verify_results())
    source = ROOT / "evidence/moe_censored"
    output = ROOT / "results/moe_censored"
    output.mkdir(parents=True, exist_ok=True)
    rows = displayed_rows(read_csv(source / "plot_data.csv"))
    with (output / "plotted_points.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    if args.skip_figures:
        return
    os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".runtime/matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    policies = ("DCNC-DAG-H", "Lazarus-style", "FlexMoE-style")
    for model in ("mixtral", "llama"):
        figure, axes = plt.subplots(figsize=(5.85, 4.9))
        for policy, marker in zip(policies, ("D", "s", "^")):
            group = sorted([row for row in rows if (row["model"], row["policy"]) == (model, policy)], key=lambda row: float(row["arrival_rate"]))
            axes.plot([float(row["arrival_rate"]) for row in group], [float(row["mean_lower_bound"]) for row in group], marker=marker, label=policy.replace("-style", "-inspired"))
        axes.set(xlabel="Arrival rate", ylabel="Mean service-delay lower bound (slots)", title=model.capitalize())
        axes.set_ylim(bottom=0)
        axes.grid(alpha=0.3)
        axes.legend()
        figure.tight_layout()
        for extension in ("pdf", "png"):
            figure.savefig(output / f"{model}_censored_delay.{extension}", dpi=200)
        plt.close(figure)
    print(output)


if __name__ == "__main__":
    main()
