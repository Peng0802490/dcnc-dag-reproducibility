# Table 6 timing provenance audit

Current release note, 2026-10-21: the corrected LaTeX project is now numerically
aligned with all 150 runs; see `paper_update/`. The audit below describes the
older PDF and remains unchanged as historical evidence. It is not the current
release-gate decision. No updated compiled PDF was verified.

Status updated 2026-10-20: all 150 successful 100k run CSVs are now archived.
Their ten mean invocation counts match the paper at its printed precision.
Their ten mean time-per-slot values differ from the paper; the timing
reconciliation gate remains open. See `IMPORT_20261020.md` for the comparison
and reproducible aggregation command. The historical audit below is retained.

## What the code measures

`Simulation._compute_mapping_with_runtime` starts `time.perf_counter()` before
`solver.compute(...)`, stops it after the mapping returns, and accumulates the
result as `routing_oracle_wall_time_sec`. With `dynvmp_bridge`, that boundary
includes Python-side payload construction, temporary files, shell and Python 2
process startup, the DynVMP solve, result parsing, and any wait caused by other
work on the host. It excludes the remaining simulator, plotting, and summary
generation.

This is a legitimate end-to-end control-plane cost, but it is not a pure
solver CPU-time measurement. Host load and campaign concurrency are therefore
part of the protocol.

## Traceable evidence

The server still contains the earlier 20k-slot campaign summary. Its byte-exact
copy is `legacy_20k_summary.csv` (remote SHA-256
`064a04081f989e85835609429e2cd9534510c57d48036bab4b41c7df8e1f101e`).
That campaign used seeds 0/1/2 and 75 scheduler panes. It completed all fifteen
runs per row except Random, K=256, which contains only five runs over two rates.

The latest PDF reports a 100k-slot, seed-1/2/3 protocol. The values first appear
in the available Overleaf history at commit
`defdbafd17aae3a10fa1d71f398eb879dee2ac42`. The available paper tree and
server project contain no 100k raw timing table or generation script for those
printed numbers.

An additional manuscript-adjacent file was found in the parent paper worktree
during the 2026-09-27 audit. It was untracked, had a local last-write time of
2026-09-12 21:15:51, and therefore has no Git provenance. Its exact bytes are
archived as `paper_intermediate_20260912.md` with SHA-256
`e0b4545ff0a6d848692801224038d4291b2506dc50cbf112c6fdde34fc48bfc6`.
The file is retained as a lineage clue, not classified as raw simulation
evidence.

## Numerical comparison

Dividing the legacy cumulative wall time by 20,000 gives its seconds-per-slot
value. The paper value divided by that legacy value is:

| Topology | K=1 | K=4 | K=16 | K=64 | K=256 |
|---|---:|---:|---:|---:|---:|
| Milan | 0.539745 | 0.541592 | 0.539666 | 0.541459 | 0.539977 |
| Random | 0.764268 | 0.764413 | 0.765325 | 0.764923 | 0.653493* |

For Milan, the mean ratio is 0.540488 with coefficient of variation 0.00177.
For the four complete five-rate Random rows, it is 0.764732 with coefficient
of variation 0.000634. The starred Random K=256 row is not comparable because
the legacy value used only two rates.

This near-constant topology-specific ratio is mathematically consistent with
a rescaling of the old timing values or with a distinct benchmark that happened
to preserve the same ratios. It does not prove which occurred. No undocumented
formula is applied in this artifact.

The manuscript intermediate adds a second, independent relationship. Its call
counts differ from the PDF by at most 0.107% for Milan and 0.082% for Random.
After converting milliseconds to seconds, all five Milan timing values equal
the PDF values. For Random, the PDF/intermediate ratios are 1.99824, 1.99743,
2, 2, and 2. This is consistent with an approximately twofold transformation
plus printed rounding, but neither the file nor the repository documents such
a transformation. Without source rows or a generation formula, this numerical
relationship cannot establish provenance for the PDF's absolute timings.

## Completed rerun and release decision

The 150-job campaign finished on 2026-10-17 at 13:25:08 (UTC+08:00).
It used the paper's 100k horizon, seeds 1/2/3, all five rates per topology/K,
the real DynVMP bridge, and up to 75 concurrent scheduler panes on the
recorded AMD EPYC 7763 host. It is valid evidence for deterministic invocation
counts and for a documented loaded-host timing measurement. Because up to
75 workers shared a 64-core host and jobs entered in command-matrix order, it is
not an isolated single-worker latency benchmark.

All 150 run rows have been imported and the ten aggregates generated
mechanically. Counts reproduce the paper, but absolute timings differ.
The paper must be updated or the original evidence supporting its printed
times supplied. Campaign completion alone does not close that release gate.

All numbers and inferences above are recomputed by `scripts/verify_claims.py`
from `timing_audit.json`, `paper_intermediate_20260912.md`, and
`legacy_20k_summary.csv`.
