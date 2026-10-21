#!/usr/bin/env python3
"""Rebuild paper-facing CSVs and regenerable figures without editing evidence."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
RESULTS = ROOT / "results"


def run(command: list[str], cwd: Path = ROOT) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def prepare_fifo_workspace(
    evidence_root: Path = EVIDENCE, results_root: Path = RESULTS
) -> Path:
    """Copy FIFO inputs and plotting code so reproduction cannot edit evidence."""
    source_root = evidence_root / "fifo"
    output_root = results_root / "fifo"
    if output_root.exists():
        shutil.rmtree(output_root)
    shutil.copytree(source_root / "data", output_root / "data")
    script_root = output_root / "scripts"
    script_root.mkdir()
    script_path = script_root / "plot_backlog_results.py"
    shutil.copy2(source_root / "scripts" / script_path.name, script_path)
    return script_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-figures", action="store_true", help="Build and verify CSVs only.")
    args = parser.parse_args()
    plot_root = RESULTS / "plots"
    policy_jsonl = [
        "pilot.jsonl", "main.jsonl", "ext.jsonl", "phase2.jsonl",
        "followup.jsonl", "access.jsonl", "common.jsonl", "dense.jsonl",
    ]
    run(
        [
            sys.executable,
            str(ROOT / "tools" / "build_plot_csvs.py"),
            "--jsonl",
            *[str(EVIDENCE / "main_sweeps" / name) for name in policy_jsonl],
            "--map",
            str(ROOT / "tools" / "csvmap_policy.json"),
            "--root",
            str(plot_root),
        ]
    )
    run(
        [
            sys.executable,
            str(ROOT / "tools" / "build_plot_csvs.py"),
            "--jsonl",
            str(EVIDENCE / "main_sweeps" / "k100k.jsonl"),
            "--map",
            str(ROOT / "tools" / "csvmap_k100k.json"),
            "--root",
            str(plot_root),
        ]
    )
    run([sys.executable, str(ROOT / "tools" / "paper_numbers.py"), str(plot_root)])
    run([sys.executable, str(ROOT / "scripts" / "verify_claims.py")])
    run([sys.executable, str(ROOT / "scripts" / "reproduce_moe_censored.py"), *(["--skip-figures"] if args.skip_figures else [])])

    if args.skip_figures:
        return 0

    workflow_out = RESULTS / "workflow"
    workflow_out.mkdir(parents=True, exist_ok=True)
    for name in ("plot_completed_delay_data.csv", "02_plot_completed_delay_three_seed.py"):
        shutil.copy2(EVIDENCE / "workflow" / name, workflow_out / name)
    run([sys.executable, "02_plot_completed_delay_three_seed.py"], workflow_out)

    moe_out = RESULTS / "moe"
    moe_out.mkdir(parents=True, exist_ok=True)
    for name in ("skewed_moe_completed_delay_plot_data.csv", "02_plot_skewed_moe_completed_delay_from_csv.py"):
        shutil.copy2(EVIDENCE / "moe" / "figures" / name, moe_out / name)
    run([sys.executable, "02_plot_skewed_moe_completed_delay_from_csv.py"], moe_out)

    run([sys.executable, str(prepare_fifo_workspace())])
    print(f"results written below {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
