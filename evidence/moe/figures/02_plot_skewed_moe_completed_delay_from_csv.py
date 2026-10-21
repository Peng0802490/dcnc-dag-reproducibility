#!/usr/bin/env python3
"""
02_plot_skewed_moe_completed_delay_from_csv.py

Run inside:

    skewed_moe_final_50000_seed012_supportable_only_merged/

Input:

    skewed_moe_completed_delay_plot_data.csv

Required input columns:

    workload
    policy
    arrival_rate
    avg_delay_completed

Output:

    figures_skewed_moe_completed_delay/
        mixtral_skewed_completed_delay.pdf/png
        llama_skewed_completed_delay.pdf/png
        skewed_moe_completed_delay_two_panel.pdf/png

This script reads only the minimal plotting CSV and plots completed average
packet delay versus arrival rate.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D


# ============================================================
# Active version stamp
# ============================================================

STYLE_VERSION = "STYLE_TEMPLATE_EXACT_V5_Y_AXIS_AUTO_ACTIVE"


# ============================================================
# Basic paths
# ============================================================

ROOT = Path(".").resolve()
INPUT_CSV = ROOT / "skewed_moe_completed_delay_plot_data.csv"
OUT_DIR = ROOT / "figures_skewed_moe_completed_delay"
OUT_DIR.mkdir(parents=True, exist_ok=True)

METRIC = "avg_delay_completed"
X_COL = "arrival_rate"
DPI = 300


# ============================================================
# Figure geometry copied from the style template
# ============================================================

AXES_SCALE = 0.75 * 0.70
BASE_AXES_SIZE = (6.2, 4.35)

AUTO_EXPAND_AXES_TO_LEGEND = True
LEGEND_CLEARANCE_RATIO = 0.03

LEFT_MARGIN_IN = 1.22
RIGHT_MARGIN_IN = 0.05
BOTTOM_MARGIN_IN = 1.00
TOP_MARGIN_IN = 1.55

OUTER_MARGIN_RATIO = 0.02

X_PAD_RATIO = 0.05

# Do not force y-axis to start from zero.
USE_ZERO_BASELINE = False

# Padding around the y-data range.
Y_LOWER_PAD_RATIO = 0.08
Y_UPPER_PAD_RATIO = 0.03

# Minimum absolute margin for y-axis when the data range is small.
MIN_Y_MARGIN_ABS = 0.5

PANEL_GAP_IN = 0.55


# ============================================================
# Font settings copied from the style template
# ============================================================

# Times New Roman is not installed system-wide on this machine, so the
# bundled faces must be registered before the probe below. Registering them
# afterwards leaves FONT_NAME on DejaVu Serif while only mathtext gets Times.
MATH_FONT_DIR = Path(__file__).resolve().parents[2] / "PLOT" / "fonts"
for font_file in (MATH_FONT_DIR / "times.ttf", MATH_FONT_DIR / "timesi.ttf"):
    if font_file.exists():
        font_manager.fontManager.addfont(font_file)

available_fonts = {f.name for f in font_manager.fontManager.ttflist}

if "Times New Roman" in available_fonts:
    FONT_NAME = "Times New Roman"
else:
    FONT_NAME = "DejaVu Serif"
    print("Warning: Times New Roman is not installed. Using DejaVu Serif instead.")

FONT_SCALE = 1.40 * 1.50 * 1.10 * 1.10

plt.rcParams.update(
    {
        "font.family": FONT_NAME,
        "font.size": 9 * FONT_SCALE,
        "axes.labelsize": 10 * FONT_SCALE,
        "axes.titlesize": 14 * FONT_SCALE,
        "xtick.labelsize": 8 * FONT_SCALE,
        "ytick.labelsize": 8 * FONT_SCALE,
        "legend.fontsize": 7.5 * FONT_SCALE,
        "mathtext.fontset": "custom",
        "mathtext.rm": "Times New Roman",
        "mathtext.it": "Times New Roman:italic",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    }
)


# ============================================================
# Line / marker settings copied from the style template
# ============================================================

CURVE_LINEWIDTH = 1.4 * 1.10 * 1.15 * 1.15 * 1.4
CURVE_MARKERSIZE = 4.0 * 1.10 * 1.15 * 1.15 * 1.4


# ============================================================
# Data labels
# ============================================================

WORKLOAD_ORDER = ["Mixtral-skewed", "Llama-skewed"]
POLICY_ORDER = ["DCNC-DAG-H", "Lazarus", "FlexMoE"]

WORKLOAD_FILE_TAGS = {
    "Mixtral-skewed": "mixtral_skewed",
    "Llama-skewed": "llama_skewed",
}

POLICY_MARKERS = {
    "DCNC-DAG-H": "D",
    "Lazarus": "s",
    "FlexMoE": "^",
}

# These are used only for layout-size calculation, to match the earlier template.
REFERENCE_POLICY_LABELS_FOR_LAYOUT = [
    r"DCNC-DAG ($T_f$=1)",
    "CTS",
    "Randomized",
    "DCNC-DAG-H",
]

REFERENCE_K_LABELS_FOR_LAYOUT = [
    r"$T_f$=1",
    r"$T_f$=2",
    r"$T_f$=4",
    r"$T_f$=8",
    r"$T_f$=16",
    r"$T_f$=32",
    r"$T_f$=64",
    r"$T_f$=128",
]


# ============================================================
# Legend style copied from the template
# ============================================================

POLICY_LEGEND_NCOL = 2
K_LEGEND_NCOL = 3
LEGEND_Y_ANCHOR = 1.05

LEGEND_STYLE = {
    "frameon": True,
    "borderaxespad": 0.0,
    "columnspacing": 0.12,
    "handlelength": 0.85,
    "handletextpad": 0.12,
    "borderpad": 0.16,
    "labelspacing": 0.16,
    "markerscale": 0.95,
}


# ============================================================
# Utility functions
# ============================================================

def ordered(items, preferred_order):
    items = list(items)
    out = [x for x in preferred_order if x in items]
    out.extend([x for x in items if x not in out])
    return out


def file_tag(text: str) -> str:
    return (
        str(text)
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
        .replace("__", "_")
    )


def normalize_workload_name(value: str) -> str:
    s = str(value)
    sl = s.lower()

    if "mixtral" in sl:
        return "Mixtral-skewed"
    if "llama" in sl:
        return "Llama-skewed"

    return s


def normalize_policy_name(value: str) -> str:
    s = str(value)

    if s == "DCNC-DAG":
        return "DCNC-DAG-H"

    return s


def load_plot_data() -> pd.DataFrame:
    if not INPUT_CSV.exists():
        raise FileNotFoundError(
            f"Cannot find {INPUT_CSV.name}. "
            "Run 01_build_skewed_moe_completed_delay_plot_csv.py first."
        )

    df = pd.read_csv(INPUT_CSV)

    required = ["workload", "policy", X_COL, METRIC]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise RuntimeError(
            f"Missing required columns in {INPUT_CSV.name}: {missing}\n"
            f"Available columns: {list(df.columns)}"
        )

    df = df.copy()
    df["workload"] = df["workload"].map(normalize_workload_name)
    df["policy"] = df["policy"].map(normalize_policy_name)
    df[X_COL] = pd.to_numeric(df[X_COL], errors="coerce")
    df[METRIC] = pd.to_numeric(df[METRIC], errors="coerce")

    df = df.dropna(subset=["workload", "policy", X_COL, METRIC])
    df = df.sort_values(["workload", "policy", X_COL])

    return df


def estimate_legend_width_inches(labels, ncol: int) -> float:
    fig = plt.figure(figsize=(8.0, 4.0))
    ax = fig.add_subplot(111)

    handles = [
        Line2D(
            [0],
            [0],
            marker="o",
            linewidth=CURVE_LINEWIDTH,
            markersize=CURVE_MARKERSIZE,
            label=label,
        )
        for label in labels
    ]

    legend = ax.legend(
        handles=handles,
        labels=labels,
        loc="center",
        ncol=ncol,
        **LEGEND_STYLE,
    )

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    bbox = legend.get_window_extent(renderer=renderer)
    width_in = bbox.width / fig.dpi

    plt.close(fig)
    return width_in


def get_common_axes_size() -> tuple[float, float]:
    base_width, base_height = BASE_AXES_SIZE
    base_aspect = base_width / base_height

    axes_width = base_width * AXES_SCALE
    axes_height = base_height * AXES_SCALE

    if AUTO_EXPAND_AXES_TO_LEGEND:
        policy_legend_width = estimate_legend_width_inches(
            REFERENCE_POLICY_LABELS_FOR_LAYOUT,
            ncol=POLICY_LEGEND_NCOL,
        )

        k_legend_width = estimate_legend_width_inches(
            REFERENCE_K_LABELS_FOR_LAYOUT,
            ncol=K_LEGEND_NCOL,
        )

        required_width = max(policy_legend_width, k_legend_width) * (
            1 + LEGEND_CLEARANCE_RATIO
        )

        if required_width > axes_width:
            axes_width = required_width
            axes_height = axes_width / base_aspect

        print("Axes/legend sizing:")
        print(f"  baseline axes width = {base_width * AXES_SCALE:.4f} in")
        print(f"  policy legend width = {policy_legend_width:.4f} in")
        print(f"  K legend width      = {k_legend_width:.4f} in")
        print(f"  final axes width    = {axes_width:.4f} in")
        print(f"  final axes height   = {axes_height:.4f} in")

    return axes_width, axes_height


def make_figure_and_axis(axes_width: float, axes_height: float):
    fig_width = LEFT_MARGIN_IN + axes_width + RIGHT_MARGIN_IN
    fig_height = BOTTOM_MARGIN_IN + axes_height + TOP_MARGIN_IN

    fig = plt.figure(figsize=(fig_width, fig_height))
    ax = fig.add_axes(
        [
            LEFT_MARGIN_IN / fig_width,
            BOTTOM_MARGIN_IN / fig_height,
            axes_width / fig_width,
            axes_height / fig_height,
        ]
    )

    return fig, ax


def make_two_panel_figure_and_axes(axes_width: float, axes_height: float):
    fig_width = (
        LEFT_MARGIN_IN
        + axes_width
        + PANEL_GAP_IN
        + axes_width
        + RIGHT_MARGIN_IN
    )
    fig_height = BOTTOM_MARGIN_IN + axes_height + TOP_MARGIN_IN

    fig = plt.figure(figsize=(fig_width, fig_height))

    ax0 = fig.add_axes(
        [
            LEFT_MARGIN_IN / fig_width,
            BOTTOM_MARGIN_IN / fig_height,
            axes_width / fig_width,
            axes_height / fig_height,
        ]
    )

    ax1 = fig.add_axes(
        [
            (LEFT_MARGIN_IN + axes_width + PANEL_GAP_IN) / fig_width,
            BOTTOM_MARGIN_IN / fig_height,
            axes_width / fig_width,
            axes_height / fig_height,
        ]
    )

    return fig, [ax0, ax1]


def compute_axis_limits_from_group(
    g: pd.DataFrame,
    x_pad_ratio: float = X_PAD_RATIO,
    y_lower_pad_ratio: float = Y_LOWER_PAD_RATIO,
    y_upper_pad_ratio: float = Y_UPPER_PAD_RATIO,
    use_zero_baseline: bool = USE_ZERO_BASELINE,
):
    x_vals = pd.to_numeric(g[X_COL], errors="coerce").dropna().to_numpy()
    y_vals = pd.to_numeric(g[METRIC], errors="coerce").dropna().to_numpy()

    if len(x_vals) == 0 or len(y_vals) == 0:
        return 0.0, 1.0, 0.0, 1.0

    x_min_data = float(x_vals.min())
    x_max_data = float(x_vals.max())
    y_min_data = float(y_vals.min())
    y_max_data = float(y_vals.max())

    x_span = max(x_max_data - x_min_data, 1e-9)
    y_span = max(y_max_data - y_min_data, 1e-9)

    # Keep x-axis starting from zero for visual consistency.
    x_min = 0.0
    x_max = x_max_data + max(x_span * x_pad_ratio, 0.1)

    # Adaptive y-axis upper bound.
    y_max = y_max_data + max(y_span * y_upper_pad_ratio, 0.3)

    # Adaptive y-axis lower bound. Do not force zero unless requested.
    if use_zero_baseline or y_min_data <= 0:
        y_min = 0.0
    else:
        y_min = max(
            0.0,
            y_min_data - max(y_span * y_lower_pad_ratio, MIN_Y_MARGIN_ABS),
        )

    if y_max <= y_min:
        y_max = y_min + 1.0

    return x_min, x_max, y_min, y_max


def setup_axis(ax, x_min: float, x_max: float, y_min: float, y_max: float):
    ax.set_xlabel("Arrival rate")
    ax.set_ylabel("Avg. completion delay (slots)")

    ax.set_xlim(x_min, x_max)
    ax.set_ylim(y_min, y_max)

    ax.grid(True, alpha=0.3)

    for spine in ax.spines.values():
        spine.set_linewidth(0.9)

    ax.tick_params(width=0.9, length=3.5)


def plot_curve(ax, df: pd.DataFrame, label: str, marker: str):
    ax.plot(
        df[X_COL],
        df[METRIC],
        marker=marker,
        linewidth=CURVE_LINEWIDTH,
        markersize=CURVE_MARKERSIZE,
        label=label,
    )


def add_top_legend(ax, ncol: int):
    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, LEGEND_Y_ANCHOR),
        ncol=ncol,
        **LEGEND_STYLE,
    )


def get_export_bbox(fig, margin_ratio: float = OUTER_MARGIN_RATIO):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    tight_bbox = fig.get_tightbbox(renderer)

    return tight_bbox.expanded(
        1 + 2 * margin_ratio,
        1 + 2 * margin_ratio,
    )


def unlink_if_exists(path: Path):
    if path.exists():
        path.unlink()


def save_figure(fig, pdf_path: Path, png_path: Path):
    unlink_if_exists(pdf_path)
    unlink_if_exists(png_path)

    export_bbox = get_export_bbox(fig)

    fig.savefig(
        pdf_path,
        bbox_inches=export_bbox,
        pad_inches=0.0,
    )
    fig.savefig(
        png_path,
        dpi=DPI,
        bbox_inches=export_bbox,
        pad_inches=0.0,
    )


def draw_one_workload(
    df: pd.DataFrame,
    workload: str,
    axes_width: float,
    axes_height: float,
):
    g = df[df["workload"] == workload].copy()

    if g.empty:
        print(f"[skip] no data for workload={workload}")
        return

    fig, ax = make_figure_and_axis(axes_width, axes_height)

    for policy in ordered(g["policy"].unique(), POLICY_ORDER):
        pg = g[g["policy"] == policy].sort_values(X_COL)
        if pg.empty:
            continue

        marker = POLICY_MARKERS.get(policy, "o")
        plot_curve(ax, pg, {"Lazarus": "Lazarus-inspired", "FlexMoE": "FlexMoE-inspired"}.get(policy, policy), marker)

    x_min, x_max, y_min, y_max = compute_axis_limits_from_group(g)
    setup_axis(ax, x_min, x_max, y_min, y_max)
    add_top_legend(ax, ncol=POLICY_LEGEND_NCOL)

    tag = WORKLOAD_FILE_TAGS.get(workload, file_tag(workload))
    pdf_path = OUT_DIR / f"{tag}_completed_delay.pdf"
    png_path = OUT_DIR / f"{tag}_completed_delay.png"

    save_figure(fig, pdf_path, png_path)
    plt.close(fig)

    print(f"[write] {pdf_path}")
    print(f"[write] {png_path}")


def draw_two_panel(
    df: pd.DataFrame,
    axes_width: float,
    axes_height: float,
):
    workloads = ordered(df["workload"].unique(), WORKLOAD_ORDER)

    if len(workloads) < 2:
        print("[skip] two-panel figure requires at least two workloads")
        return

    fig, axes = make_two_panel_figure_and_axes(axes_width, axes_height)

    for ax, workload in zip(axes, workloads[:2]):
        g = df[df["workload"] == workload].copy()

        for policy in ordered(g["policy"].unique(), POLICY_ORDER):
            pg = g[g["policy"] == policy].sort_values(X_COL)
            if pg.empty:
                continue

            marker = POLICY_MARKERS.get(policy, "o")
            plot_curve(ax, pg, {"Lazarus": "Lazarus-inspired", "FlexMoE": "FlexMoE-inspired"}.get(policy, policy), marker)

        x_min, x_max, y_min, y_max = compute_axis_limits_from_group(g)
        setup_axis(ax, x_min, x_max, y_min, y_max)
        add_top_legend(ax, ncol=POLICY_LEGEND_NCOL)

    pdf_path = OUT_DIR / "skewed_moe_completed_delay_two_panel.pdf"
    png_path = OUT_DIR / "skewed_moe_completed_delay_two_panel.png"

    save_figure(fig, pdf_path, png_path)
    plt.close(fig)

    print(f"[write] {pdf_path}")
    print(f"[write] {png_path}")


def write_stamp_file():
    stamp = OUT_DIR / f"{STYLE_VERSION}.txt"
    stamp.write_text(
        f"{STYLE_VERSION}\n"
        f"FONT_NAME={FONT_NAME}\n"
        f"FONT_SCALE={FONT_SCALE}\n"
        f"CURVE_LINEWIDTH={CURVE_LINEWIDTH}\n"
        f"CURVE_MARKERSIZE={CURVE_MARKERSIZE}\n"
        f"AXES_SCALE={AXES_SCALE}\n"
        f"BASE_AXES_SIZE={BASE_AXES_SIZE}\n"
        f"USE_ZERO_BASELINE={USE_ZERO_BASELINE}\n"
        f"Y_LOWER_PAD_RATIO={Y_LOWER_PAD_RATIO}\n"
        f"Y_UPPER_PAD_RATIO={Y_UPPER_PAD_RATIO}\n"
        f"MIN_Y_MARGIN_ABS={MIN_Y_MARGIN_ABS}\n"
        f"LEGEND_Y_ANCHOR={LEGEND_Y_ANCHOR}\n"
        f"OUTPUT_DIR={OUT_DIR.resolve()}\n",
        encoding="utf-8",
    )
    print(f"[stamp] {stamp}")


def main():
    print(STYLE_VERSION)
    print(f"FONT_NAME={FONT_NAME}")
    print(f"FONT_SCALE={FONT_SCALE}")
    print(f"CURVE_LINEWIDTH={CURVE_LINEWIDTH}")
    print(f"CURVE_MARKERSIZE={CURVE_MARKERSIZE}")
    print(f"USE_ZERO_BASELINE={USE_ZERO_BASELINE}")
    print(f"Y_LOWER_PAD_RATIO={Y_LOWER_PAD_RATIO}")
    print(f"Y_UPPER_PAD_RATIO={Y_UPPER_PAD_RATIO}")
    print(f"INPUT_CSV={INPUT_CSV.resolve()}")
    print(f"OUT_DIR={OUT_DIR.resolve()}")

    # Remove old output files to avoid looking at stale figures.
    for pattern in ["*.pdf", "*.png", "*.txt"]:
        for path in OUT_DIR.glob(pattern):
            path.unlink()

    df = load_plot_data()

    print("[groups]")
    print(df.groupby(["workload", "policy"]).size().to_string())

    axes_width, axes_height = get_common_axes_size()

    for workload in ordered(df["workload"].unique(), WORKLOAD_ORDER):
        draw_one_workload(df, workload, axes_width, axes_height)

    draw_two_panel(df, axes_width, axes_height)

    write_stamp_file()

    print("[done]")


if __name__ == "__main__":
    main()
