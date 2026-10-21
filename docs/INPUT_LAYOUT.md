# Experiment input layout

Version 0.1.1 reorganizes the former `legacy_inputs/` directory. It does not
change the simulations, numerical evidence, or the paper's existing v0.1.0
reference. All 104 previous files are retained, with a per-file migration
record in `manifests/input_layout.json`.

| Location | Contents |
|---|---|
| `inputs/topologies/` | 13 fixed network topologies, byte-identical to v0.1.0 |
| `inputs/dags/` | 31 fixed service DAGs, byte-identical to v0.1.0 |
| `inputs/configs/` | 56 experiment configurations; only file references change |
| `inputs/command_csv/` | Maintained command matrices using the current paths |
| `inputs/archive/` | Original historical random5/random6 ZIP and tutorial |
| `tools/` | Maintained input generation, validation, and run-table utilities |

Configuration references are relative to the configuration file: network
paths use `../topologies/`, and service DAG paths use `../dags/`. Capacities,
dependencies, placements, and all other configuration values are unchanged.
Archived tutorials describe historical layouts, not the current commands.
No files under `evidence/` are rewritten; old paths in those records retain
their original provenance and must not be treated as current defaults.

The historical MoE protocol retains its original source hashes. Its verifier
maps the relocated Milan JSON and reverses exactly the declared topology-path
literal in the maintained Milan runner before checking the original hash.
Every other byte must still match; regression tests reject unrelated source
or topology changes. Fresh runs record their actual current source hashes.

## Current usage

Run commands from the repository root after installing the package:

```bash
python scripts/run_workflow_case.py --config inputs/configs/config_workflow_srasearch22_random_allnodes.json --output-dir results/workflow_smoke --slots 100 --seeds 1 --rate 0.01 --policy CTS --interference-model primary
python tools/validate_random56_configs.py
```

Input generation utilities can overwrite fixed inputs. They are not needed
to reproduce results from the already supplied files; use a separate working
copy when exploring alternate topologies or capacities.

## Compatibility

The maintained workflow runner accepts the former
`--config legacy_inputs/config_*.json` arguments as well as the new paths.
`dcnc_sim.workloads.load_legacy_config()` remains an alias-compatible wrapper
around `load_config()`; both also accept a bundled configuration basename.
An existing explicit file takes precedence and resolves its own references
relative to its parent directory. Missing external files are not silently
redirected to similarly named bundled inputs.

There is no duplicate `legacy_inputs/` tree and no symlink requirement.
Historical scripts that directly open old filenames, rather than using the
maintained loaders, should be run from the unchanged v0.1.0 release.

The auxiliary `scripts/run_project_case.py` entry point has a pre-existing
`StaticMinCostSolver` import error, also present in v0.1.0. Its configuration
paths are migrated, but that entry point is not claimed as runtime-validated
by this directory-only update. The workflow and MoE runners are validated
separately; no mapping algorithm is changed here.

## Verification

```bash
python -m unittest discover -s tests -v
python scripts/verify_claims.py --strict
python scripts/maintain_artifact.py verify --strict
```

Regression tests verify every moved input, check configuration equivalence
apart from path strings, resolve every referenced topology/DAG, and exercise
both new and supported old configuration arguments. The published v0.1.0
tag and its ZIP/checksum/metadata attachments remain unchanged.
