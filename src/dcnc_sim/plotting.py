from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, Mapping, Sequence

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def plot_delay_curve(
    df: pd.DataFrame,
    x: str,
    y: str,
    hue: str,
    out_path: str | Path,
    xlabel: str,
    ylabel: str,
    vline: float | None = None,
) -> None:
    out_path = Path(out_path)
    plt.figure(figsize=(6, 4))
    for name, g in df.groupby(hue):
        g = g.sort_values(x)
        plt.plot(g[x], g[y], marker="o", label=str(name))
    if vline is not None:
        plt.axvline(vline, linestyle="--", linewidth=1)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=200)
    plt.close()


def plot_backlog_series(
    series_dict: Mapping[str, Sequence[float]],
    out_path: str | Path,
    xlabel: str = "Time slot",
    ylabel: str = "Total backlog",
) -> None:
    out_path = Path(out_path)
    plt.figure(figsize=(6, 4))
    for label, series in series_dict.items():
        plt.plot(list(range(len(series))), list(series), label=str(label))
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=200)
    plt.close()
