# New Section 7.2 Simulation Deliverables

Canonical delivery date: 2026-07-23

## Definitive result

The proposed wireless mixed-mapping fork-join instance is internally
consistent and suitable for the intended boundary-validation role.

- Exact capacity: `lambda*=1.000000`.
- Unique boundary mixture: `f_m1=f_m2=0.5`.
- Capacity of either mapping alone: `0.5`.
- Wireless-only equal-mixture capacity: `1.428571`.
- Canonical campaign: 95 runs, 100,000 slots each, 5 logical seeds.
- First tested overload point flagged in all five seeds by the corrected
  physical-or-virtual workload diagnostic: `lambda=1.05` (5% above capacity).
- The `lambda=1.03` (3%) crossing belongs only to the explicitly labeled
  physical object-count sensitivity diagnostic and is not the paper-facing
  workload result.

Use `docs/new_7.2_instance_simulation_report.md` as the human-readable result
and `results/canonical/paper_table_main.csv` plus
`results/canonical/paper_table_ablation.csv` as the paper-table source.

## Contents

- `docs/`: specification, final report, correction log, and exact reproduction
  commands.
- `scripts/`: canonical runner and independent instance, LP, result,
  second-pass, wireless-path, and packaging audits.
- `results/canonical/`: all 95 raw run records, formal aggregation, metadata,
  paper-facing tables, LP decomposition, and integrity report.
- `results/capacity/`: simulator-independent SciPy LP result and link audit.
- `results/instance_contract/`: checks of the actual simulator instance,
  mappings, load vectors, state/action enumeration, and Gurobi/SciPy agreement.
- `results/second_pass/`: independent passive metrics for all 35 main runs,
  exact reproduction report, and simulator-module hashes.
- `results/wireless/`: per-seed path hashes, all 16 joint-state counts, and
  marginal/correlation diagnostics over 500,000 slot samples.
- `results/observer_validation/`: 64-row full-scan reference and the
  machine-readable proof that incremental metric collection is equivalent.
- `SHA256SUMS.txt`: SHA-256 for every other file in this delivery.

## Result hierarchy

The `results/canonical` directory is authoritative. The package intentionally
excludes the superseded first-pass raw data so it cannot be mistaken for a
paper-facing result. The reason for supersession and its quantified impact are
preserved in `docs/new_7.2_instance_simulation_correction_log.md`.

The simulation is finite-horizon evidence, not a proof of stochastic
stability. The rigorous capacity claim comes from the exact state-averaged LP;
the simulation verifies that the implemented policy exhibits the predicted
boundary, mixture, and ablation behavior on the stated grid.

## Integrity check

From the extracted delivery root, verify the per-file hashes with a SHA-256
tool against `SHA256SUMS.txt`. The ZIP itself was also opened and every entry
fully decompressed after creation; its archive SHA-256 is reported alongside
the download path in the completion message.
