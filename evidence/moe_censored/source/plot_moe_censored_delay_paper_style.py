"""Redraw the audited 107-point delay data in the penalized PDF style.

Input: MoE_censored_delay_plot_data.csv (three-seed means, T=100000).
Unfinished requests contribute T minus their recorded arrival slot.
Reuse the exact style module used by MoE_{model}_penalized_delay.pdf;
The source retains all confirmed points. At the user's request, the Llama
plot omits DCNC-DAG-H's final arrival-rate point and rescales its y-axis.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".runtime" / "matplotlib"))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from plot_moe_penalized_delay_diagnostic import load_original_style_module
from run_moe_censored_delay_preview import load_rates


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=("llama", "mixtral"))
    args = parser.parse_args()
    frame = pd.read_csv(ROOT / "MoE_censored_delay_plot_data.csv")
    rates = load_rates(
        ROOT / "moe_milan_v2/figures/skewed_moe_completed_delay_plot_data.csv"
    )
    expected = {
        (model, policy, rate)
        for model, policies in rates.items()
        for policy, points in policies.items()
        for rate in points
    }
    actual = set(zip(frame.model, frame.policy, frame.arrival_rate))
    if actual != expected or len(frame) != len(expected):
        raise ValueError("Plot data must contain the exact confirmed 107-point grid")
    if not frame.seeds.eq(3).all():
        raise ValueError("Every plotting point must average three seeds")
    if not np.isfinite(frame.mean_lower_bound).all() or (frame.mean_lower_bound < 0).any():
        raise ValueError("Delay values must be finite and nonnegative")

    style = load_original_style_module()
    style.METRIC = "mean_lower_bound"
    axes_width, axes_height = style.get_common_axes_size()
    audit_path = ROOT / ".runtime/censored_paper_style/audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else {"models": {}}
    audit.update(source="MoE_censored_delay_plot_data.csv", source_points=len(frame),
                 metric=style.METRIC)
    for model in ((args.model,) if args.model else ("llama", "mixtral")):
        group = frame[frame.model == model].copy()
        omitted = []
        if model == "llama":
            last = group[group.policy == "DCNC-DAG-H"].arrival_rate.idxmax()
            omitted = group.loc[[last], ["policy", "arrival_rate", "mean_lower_bound"]].to_dict("records")
            group = group.drop(index=last)
        counts = group.groupby("policy").size().to_dict()
        group["policy"] = group.policy.replace(
            {"Lazarus-style": "Lazarus", "FlexMoE-style": "FlexMoE"}
        )
        fig, ax = style.make_figure_and_axis(axes_width, axes_height)
        for policy in style.ordered(group.policy.unique(), style.POLICY_ORDER):
            points = group[group.policy == policy].sort_values(style.X_COL)
            label = {"Lazarus": "Lazarus-inspired", "FlexMoE": "FlexMoE-inspired"}.get(
                policy, policy
            )
            style.plot_curve(ax, points, label, style.POLICY_MARKERS[policy])
        limits = style.compute_axis_limits_from_group(group)
        if model == "llama":
            limits = (*limits[:2], 0.0, float(np.ceil(limits[3] / 500.0) * 500.0))
        style.setup_axis(ax, *limits)
        ax.set_ylabel("Avg. completion delay (slots)")
        style.add_top_legend(ax, ncol=style.POLICY_LEGEND_NCOL)
        if sum(len(line.get_xdata()) for line in ax.lines) != len(group):
            raise RuntimeError("A confirmed plotting point was omitted")

        stem = ROOT / f"MoE_{model.capitalize()}_censored_delay_full_grid"
        pdf, png = stem.with_suffix(".pdf"), stem.with_suffix(".png")
        try:
            style.save_figure(fig, pdf, png)
        except PermissionError:
            stem = stem.with_name(stem.name + "_paper_style")
            pdf, png = stem.with_suffix(".pdf"), stem.with_suffix(".png")
            style.save_figure(fig, pdf, png)
        audit["models"][model] = {
            "points": len(group), "counts": counts,
            "omitted_points": omitted, "y_limits": list(ax.get_ylim()),
            "pdf": pdf.name, "png": png.name,
            "font": style.FONT_NAME,
            "axes_size_inches": [axes_width, axes_height],
            "linewidth": style.CURVE_LINEWIDTH,
            "markersize": style.CURVE_MARKERSIZE,
            "legend_columns": style.POLICY_LEGEND_NCOL,
            "curves": [{"label": line.get_label(), "color": line.get_color(),
                        "marker": line.get_marker(), "points": len(line.get_xdata())}
                       for line in ax.lines],
        }
        plt.close(fig)
        print(pdf)

    audit["points"] = sum(model["points"] for model in audit["models"].values())
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit))


if __name__ == "__main__":
    main()
