from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D


# ============================================================
# Basic settings
# ============================================================

ROOT = Path(".").resolve()
INPUT_CSV = ROOT / "plot_completed_delay_data.csv"
OUT_DIR = ROOT / "figures_completed_delay"
OUT_DIR.mkdir(parents=True, exist_ok=True)

METRIC = "avg_delay_completed"
ERROR_COL = "delay_se"
X_COL = "arrival_rate"

DPI = 300

# The "plot window" means the axes area containing the data curves.
# The axes area keeps the original aspect ratio.
# Starting from the previous 75% axes size, it was further reduced by 30%.
AXES_SCALE = 0.75 * 0.70

# Original axes reference size.
BASE_AXES_SIZE = (6.2, 4.35)

# The axes width is automatically expanded if the legend is wider.
AUTO_EXPAND_AXES_TO_LEGEND = True
LEGEND_CLEARANCE_RATIO = 0.03

# Margins around the axes in inches. These margins only provide room for
# tick labels, axis labels, and the top legend. The exported file is cropped
# to visible artists and then given about 2% outer whitespace.
LEFT_MARGIN_IN = 1.22
RIGHT_MARGIN_IN = 0.05
BOTTOM_MARGIN_IN = 1.00
TOP_MARGIN_IN = 1.55

# Crop the exported figure to the visible artists, then leave about 2%
# blank space on each side of the tight content bounding box.
OUTER_MARGIN_RATIO = 0.02

# Small internal blank space inside the data axes.
X_PAD_RATIO = 0.05
Y_PAD_RATIO = 0.03


# ============================================================
# Font settings
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

# Final font scale:
# previous version: 1.40 * 1.50 * 1.10 = 2.31
# current version:  1.40 * 1.50 * 1.10 * 1.10 = 2.541
FONT_SCALE = 1.40 * 1.50 * 1.10 * 1.10

plt.rcParams.update({
    "font.family": FONT_NAME,
    "font.size": 9 * FONT_SCALE,          # 22.869
    "axes.labelsize": 10 * FONT_SCALE,    # 25.41
    "axes.titlesize": 14 * FONT_SCALE,    # 35.574
    "xtick.labelsize": 8 * FONT_SCALE,    # 20.328
    "ytick.labelsize": 8 * FONT_SCALE,    # 20.328
    "legend.fontsize": 7.5 * FONT_SCALE,  # 19.0575
    "mathtext.fontset": "custom",
    "mathtext.rm": "Times New Roman",
    "mathtext.it": "Times New Roman:italic",
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
})


# ============================================================
# Line and marker settings
# ============================================================

# Keep the line width and marker size exactly consistent with the uploaded
# style template.
CURVE_LINEWIDTH = 1.4 * 1.10 * 1.15 * 1.15 * 1.4
CURVE_MARKERSIZE = 4.0 * 1.10 * 1.15 * 1.15 * 1.4


# ============================================================
# Workload and policy settings
# ============================================================

POLICY_ORDER = ["DCNC-DAG-H", "CTS", "Random"]
WORKFLOW_ORDER = ["SRA-Search-22", "SIPHT-31"]

POLICY_MARKERS = {
    "DCNC-DAG-H": "D",
    "CTS": "s",
    "Random": "^",
}

FILE_TAG = {
    "SRA-Search-22": "srasearch22",
    "SIPHT-31": "sipht31",
}

# These labels are not plotted. They are used only to reproduce the axes-size
# calculation of the uploaded style template. In that template, the common axes
# size was expanded according to the wider of:
#   1) a 4-item policy-comparison legend, and
#   2) an 8-item K-ablation legend.
# If the workflow script sizes the axes only from its three plotted policies,
# the axes become narrower while the absolute font size remains unchanged; the
# resulting figure therefore looks like it has larger fonts.
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
# Legend settings
# ============================================================

# Multi-row legends:
# policy comparison: 4 reference items -> 2 columns x 2 rows
# K ablation: 8 reference items -> 3 columns across multiple rows
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
# Helper functions
# ============================================================

def ordered(items, preferred):
    items = list(items)
    out = [x for x in preferred if x in items]
    out += [x for x in items if x not in out]
    return out


def load_plot_data() -> pd.DataFrame:
    if not INPUT_CSV.exists():
        raise FileNotFoundError(
            f"Cannot find {INPUT_CSV.name}. Run 01_build_completed_delay_plot_csv.py first."
        )

    df = pd.read_csv(INPUT_CSV)
    required = ["workflow", "policy", X_COL, METRIC, ERROR_COL]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise RuntimeError(f"Missing required columns in {INPUT_CSV.name}: {missing}")

    df[X_COL] = pd.to_numeric(df[X_COL], errors="coerce")
    df[METRIC] = pd.to_numeric(df[METRIC], errors="coerce")
    df[ERROR_COL] = pd.to_numeric(df[ERROR_COL], errors="coerce").fillna(0.0)
    df = df.dropna(subset=["workflow", "policy", X_COL, METRIC])
    return df


def estimate_legend_width_inches(labels, ncol: int) -> float:
    """
    Estimate the actual legend width in inches under the current font,
    marker, line width, and legend layout.
    """
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


def get_common_axes_size():
    """
    Compute one shared axes size exactly following the uploaded style template.

    The baseline axes area is first set by BASE_AXES_SIZE * AXES_SCALE. If the
    wider reference legend exceeds this axes width, the axes width is expanded
    and the axes height is adjusted to preserve the original aspect ratio.
    """
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
        print(f"  baseline axes width  = {base_width * AXES_SCALE:.4f} in")
        print(f"  policy legend width  = {policy_legend_width:.4f} in")
        print(f"  K legend width       = {k_legend_width:.4f} in")
        print(f"  final axes width     = {axes_width:.4f} in")
        print(f"  final axes height    = {axes_height:.4f} in")

    return axes_width, axes_height


def make_figure_and_axis(axes_width: float, axes_height: float):
    """
    Create a figure with explicitly controlled axes size.

    All workflow figures use the same axes width, axes height, figure width,
    and figure height before export. The exported images are then cropped to
    visible artists with about 2% external whitespace.
    """
    fig_width = LEFT_MARGIN_IN + axes_width + RIGHT_MARGIN_IN
    fig_height = BOTTOM_MARGIN_IN + axes_height + TOP_MARGIN_IN

    fig = plt.figure(figsize=(fig_width, fig_height))
    ax = fig.add_axes([
        LEFT_MARGIN_IN / fig_width,
        BOTTOM_MARGIN_IN / fig_height,
        axes_width / fig_width,
        axes_height / fig_height,
    ])

    return fig, ax


def compute_axis_limits(df: pd.DataFrame, x_pad_ratio=X_PAD_RATIO, y_pad_ratio=Y_PAD_RATIO):
    x_max = df[X_COL].max()
    y_max = (df[METRIC] + df[ERROR_COL]).max()

    if pd.isna(x_max) or x_max <= 0:
        x_max = 1.0
    if pd.isna(y_max) or y_max <= 0:
        y_max = 1.0

    x_upper = x_max * (1 + x_pad_ratio)
    y_upper = y_max * (1 + y_pad_ratio)

    return 0.0, x_upper, 0.0, y_upper


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
    line = ax.plot(
        df[X_COL],
        df[METRIC],
        marker=marker,
        linewidth=CURVE_LINEWIDTH,
        markersize=CURVE_MARKERSIZE,
        label=label,
    )[0]
    ax.fill_between(
        df[X_COL],
        df[METRIC] - df[ERROR_COL],
        df[METRIC] + df[ERROR_COL],
        color=line.get_color(),
        alpha=0.15,
        linewidth=0,
    )


def add_top_legend(ax, ncol: int):
    """
    Add a compact multi-row legend above the axes.

    The legend is centered with respect to the axes. The number of columns
    controls the number of rows. Fewer columns prevent the legend box from
    becoming wider than the data-axes region.
    """
    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, LEGEND_Y_ANCHOR),
        ncol=ncol,
        **LEGEND_STYLE,
    )


def get_export_bbox(fig, margin_ratio: float = OUTER_MARGIN_RATIO):
    """
    Return a tight export bounding box with about 2% blank margin on each side.

    The padding is proportional to the tight content size, so the apparent
    outer whitespace is controlled as a percentage of the image size.
    """
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    tight_bbox = fig.get_tightbbox(renderer)

    return tight_bbox.expanded(
        1 + 2 * margin_ratio,
        1 + 2 * margin_ratio,
    )


def save_figure(fig, pdf_path: Path, png_path: Path):
    """
    Save with minimal external whitespace.

    The axes and legend geometry are unchanged. The exported PDF/PNG is cropped
    to all visible artists, and then about 2% whitespace is retained on the
    top, bottom, left, and right sides.
    """
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


def output_paths(workflow: str):
    tag = FILE_TAG.get(workflow, workflow.lower().replace(" ", "_").replace("/", "_"))
    png_path = OUT_DIR / f"{tag}_avg_delay_completed.png"
    pdf_path = OUT_DIR / f"{tag}_avg_delay_completed.pdf"
    return pdf_path, png_path


def plot_one_workflow(df: pd.DataFrame, workflow: str, axes_width: float, axes_height: float):
    g = df[df["workflow"] == workflow].copy()
    if g.empty:
        print(f"[skip] no data for workflow={workflow}")
        return

    fig, ax = make_figure_and_axis(axes_width, axes_height)

    for policy in ordered(g["policy"].unique(), POLICY_ORDER):
        pg = g[g["policy"] == policy].sort_values(X_COL)
        if pg.empty:
            continue

        marker = POLICY_MARKERS.get(policy, "o")
        plot_curve(ax, pg, ("Randomized" if policy == "Random" else policy), marker)

    x_min, x_max, y_min, y_max = compute_axis_limits(g)
    setup_axis(ax, x_min, x_max, y_min, y_max)

    add_top_legend(ax, ncol=POLICY_LEGEND_NCOL)

    pdf_path, png_path = output_paths(workflow)
    save_figure(fig, pdf_path, png_path)
    plt.close(fig)

    print(f"[write] {pdf_path}")
    print(f"[write] {png_path}")


def main():
    df = load_plot_data()

    print(f"Using font: {FONT_NAME}")
    print(f"Using metric: {METRIC}")
    print("[input] plot_completed_delay_data.csv")
    print(df.groupby(["workflow", "policy"]).size().to_string())

    axes_width, axes_height = get_common_axes_size()

    for workflow in ordered(df["workflow"].unique(), WORKFLOW_ORDER):
        plot_one_workflow(df, workflow, axes_width, axes_height)

    print(f"[done] figures are under: {OUT_DIR}")


if __name__ == "__main__":
    main()
