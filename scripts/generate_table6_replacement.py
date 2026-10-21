"""Generate a traceable Table 6 replacement without editing the manuscript."""

from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path

if __package__:
    from .verify_table6_results import read_csv, verify_results
else:
    from verify_table6_results import read_csv, verify_results


ROOT = Path(__file__).resolve().parents[1]


def replacement_files(root: Path = ROOT) -> dict[str, str]:
    manifest = json.loads((root / "manifests/claims.json").read_text(encoding="utf-8"))
    claims = manifest["claims"]
    claim = claims["table6"]
    verify_results(root, claim)
    summaries = {(row["case"], int(row["fixed_k"])): row for row in read_csv(root / claim["summary_evidence"])}
    rows = []
    latex_rows = []
    for frame in (1, 4, 16, 64, 256):
        cells = [str(frame)]
        for topology, case in (("Milan", "driving_milan"), ("Random", "driving_random")):
            summary = summaries[(case, frame)]
            calls = float(summary["mean_dynvmp_calls"])
            seconds = float(summary["mean_dynvmp_wall_time_sec"]) / claim["slots"]
            threshold = claims["frame_length"]["thresholds"][topology][str(frame)]
            formatted = f"{seconds:.4f}" if seconds < 0.1 else f"{seconds:.3f}"
            cells.extend([f"{threshold:.2f}", f"{calls:.1f}", formatted])
            rows.append({"topology": topology, "frame_length": frame, "lambda_hat": f"{threshold:.2f}", "mapping_calls": calls, "mapping_seconds_per_slot": seconds, "printed_seconds_per_slot": formatted, "bound_pdf_seconds_per_slot": claim["historical_pdf_seconds_per_slot"][case][str(frame)]})
        latex_rows.append(" & ".join(cells) + r" \\")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    reductions = {}
    for topology, case in (("Milan", "driving_milan"), ("Random", "driving_random")):
        baseline = summaries[(case, 1)]
        endpoint = summaries[(case, 256)]
        reductions[topology] = {
            "mapping_calls_percent": 100 * (1 - float(endpoint["mean_dynvmp_calls"]) / float(baseline["mean_dynvmp_calls"])),
            "mapping_time_percent": 100 * (1 - float(endpoint["mean_dynvmp_wall_time_sec"]) / float(baseline["mean_dynvmp_wall_time_sec"])),
        }
    text = (
        "As $T_f$ increases from 1 to 256, the number of exact mapping calls "
        f"per commodity decreases by {reductions['Milan']['mapping_calls_percent']:.1f}\\% on Milan "
        f"and {reductions['Random']['mapping_calls_percent']:.1f}\\% on the Random topology, "
        "while the amortized mapping computation time per slot decreases by "
        f"{reductions['Milan']['mapping_time_percent']:.1f}\\% and "
        f"{reductions['Random']['mapping_time_percent']:.1f}\\%, respectively.\n\n"
        "Mapping time covers the complete mapping call, including bridge serialization, "
        "process startup, solving, and result parsing. The measurements were collected "
        "with up to 75 concurrent experiment processes on a 64-core host and include "
        "host contention; they are not isolated solver CPU times.\n"
    )
    correction = [
        "# Table 6 data correction",
        "",
        "Historical comparison: these corrected numbers are now verified in the",
        "updated LaTeX project. The old PDF remains a historical baseline; no",
        "updated compiled PDF was supplied or verified. See `../paper_update/`.",
        "",
        f"Bound PDF SHA-256: `{manifest['paper']['sha256']}`.",
        "",
        "Source: all 150 verified runs in `evidence/table6/raw/`, aggregated in",
        f"`{claim['summary_evidence']}`. Each topology/frame row averages",
        "three seeds and five arrival rates, with 100,000 slots per run.",
        "",
        "| Topology | Frame length | Bound PDF seconds/slot | Verified replacement seconds/slot |",
        "|---|---:|---:|---:|",
    ]
    for row in rows:
        correction.append(
            f"| {row['topology']} | {row['frame_length']} | "
            f"{row['bound_pdf_seconds_per_slot']:g} | "
            f"{row['printed_seconds_per_slot']} |"
        )
    correction.extend([
        "",
        "Supported rates and invocation counts are unchanged at paper precision.",
        "Using full-precision values before rounding, mapping time decreases by",
        f"{reductions['Milan']['mapping_time_percent']:.1f}% on Milan and "
        f"{reductions['Random']['mapping_time_percent']:.1f}% on Random from frame length 1 to 256.",
        "",
        "These are complete mapping-call wall times, including bridge I/O, process",
        "startup, solving, parsing, and contention from up to 75 experiment",
        "processes on a 64-core host. They are not isolated solver CPU times.",
        "",
        "The numeric rows and reductions have been applied in the supplied project.",
        "The additional method paragraph in `table6_text.tex` is a suggested",
        "handoff only: the owner declined adding it to the manuscript. The",
        "full-precision historical comparison remains in `table6.csv`.",
        "",
    ])
    return {
        "table6.csv": stream.getvalue(),
        "table6_rows.tex": "\n".join(latex_rows) + "\n",
        "table6_text.tex": text,
        "reductions.json": json.dumps(reductions, indent=2) + "\n",
        "CORRECTION.md": "\n".join(correction),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results/table6_replacement")
    args = parser.parse_args()
    output = ROOT / "evidence/table6/replacement" if args.check else args.output_dir.resolve()
    if not output.is_relative_to(ROOT):
        raise ValueError("Replacement output must stay inside the artifact")
    files = replacement_files()
    if args.check:
        for name, content in files.items():
            if (output / name).read_bytes() != content.encode("utf-8"):
                raise ValueError(f"Table 6 replacement drift: {name}")
        print("Table 6 replacement matches all 150 verified raw runs")
    else:
        output.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            (output / name).write_text(content, encoding="utf-8", newline="\n")
        print(output)


if __name__ == "__main__":
    main()
