# New Section 7.2 Simulation - Reproduction Record

Date: 2026-07-23

## Canonical environment

- Host: `paper-server` (`pcni-Super-Server`)
- Simulator root: `${ARTIFACT_ROOT}`
- Python executable: `python`
- Python: 3.10.20
- NetworkX: 3.4.2
- NumPy: 2.2.6
- pandas: 2.3.3
- SciPy: 1.15.3
- Gurobi: 13.0.2
- Required process environment: `PYTHONHASHSEED=0`

The simulator directory is not a Git working tree. The second-pass audit
therefore records SHA-256 values for every simulator module on the exercised
capacity, interference, mapping, physical, virtual, wireless, and simulation
paths.

## Commands

Run these from the simulator root on `paper-server` after placing the packaged
scripts in `scripts/`.

```bash
PYTHONHASHSEED=0 python \
  scripts/verify_new_7_2_instance_contract.py \
  --output results/new_7_2_contract_audit_20260723/instance_contract_audit.json

PYTHONHASHSEED=0 python \
  scripts/run_new_7_2_wireless_mixed_mapping.py \
  --output-dir \
  results/new_7_2_wireless_mixed_mapping_canonical_incremental_hash0_20260723 \
  --slots 100000 --seeds 5 --workers 75 --metric-mode incremental

PYTHONHASHSEED=0 python \
  scripts/second_pass_new_7_2_audit.py \
  --formal-runs \
  results/new_7_2_wireless_mixed_mapping_canonical_incremental_hash0_20260723/runs.csv \
  --output-dir results/new_7_2_second_pass_canonical_hash0_20260723 \
  --slots 100000 --seeds 5 --workers 25

PYTHONHASHSEED=0 python \
  scripts/audit_new_7_2_wireless_paths.py \
  --formal-runs \
  results/new_7_2_wireless_mixed_mapping_canonical_incremental_hash0_20260723/runs.csv \
  --output-dir results/new_7_2_wireless_path_audit_canonical_hash0_20260723 \
  --slots 100000 --seeds 5
```

Run the independent LP audit from the paper repository. It imports no
`dcnc_sim` module.

```powershell
$env:PYTHONPATH=(Resolve-Path .codex\vendor).Path
python scripts\validate_new_7_2_capacity_lp.py `
  --output-dir results_new_7_2_validation_20260723
```

After copying the canonical remote output into the local result directory, run:

```powershell
$env:PYTHONPATH=(Resolve-Path .codex\vendor).Path
python scripts\audit_new_7_2_results.py `
  --campaign-dir results_new_7_2_validation_20260723\canonical
```

## Deterministic seed contract

- Logical seeds: `0,1,2,3,4`
- Arrival simulator seed: `30000 + logical_seed`
- Mapping solver seed: `20000 + logical_seed`
- Wireless seed: `10000 + 101 * logical_seed`
- Arrival mode: bounded (`floor(lambda) + Bernoulli(frac(lambda))`)
- Main and fixed-`m1` runs use identical arrival and wireless paths for a given
  offered rate and logical seed.
- The physical network consumes one wireless draw during construction. Path
  hashes and wireless statistics exclude that initialization draw and cover
  exactly 100,000 simulated slots.
- Incremental physical metrics use exact integer units of 0.1 workload and are
  validated against full queue scans by
  `scripts/validate_new_7_2_metric_observer.py`.
