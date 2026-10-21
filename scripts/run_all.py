from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], cwd: Path) -> None:
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Run all simulation groups for the paper.")
    ap.add_argument("--output-dir", default="results")
    ap.add_argument("--boundary-slots", type=int, default=600)
    ap.add_argument("--edge-slots", type=int, default=800)
    ap.add_argument("--ai-slots", type=int, default=500)
    ap.add_argument("--fifo-slots", type=int, default=2000)
    ap.add_argument("--fixed-k", type=int, default=1, help="Frame length K for the Fixed-K routing extension.")
    ap.add_argument(
        "--interference-model",
        choices=["none", "primary"],
        default="none",
        help="Interference model passed to the boundary / edge / AI experiment groups.",
    )
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    python = sys.executable

    shared = ["--fixed-k", str(args.fixed_k), "--interference-model", args.interference_model]
    run(
        [
            python,
            "scripts/run_boundary_validation.py",
            "--output-dir",
            f"{args.output_dir}/boundary_validation",
            "--slots",
            str(args.boundary_slots),
            *shared,
        ],
        root,
    )
    run(
        [
            python,
            "scripts/run_edge_experiments.py",
            "--output-dir",
            f"{args.output_dir}/edge_experiments",
            "--slots",
            str(args.edge_slots),
            *shared,
        ],
        root,
    )
    run(
        [
            python,
            "scripts/run_ai_experiments.py",
            "--output-dir",
            f"{args.output_dir}/ai_experiments",
            "--slots",
            str(args.ai_slots),
            *shared,
        ],
        root,
    )
    run(
        [
            python,
            "scripts/run_fifo_counterexample.py",
            "--output-dir",
            f"{args.output_dir}/fifo_counterexample",
            "--slots",
            str(args.fifo_slots),
        ],
        root,
    )
    print(f"All experiment groups completed. Results are under: {args.output_dir}")


if __name__ == "__main__":
    main()
