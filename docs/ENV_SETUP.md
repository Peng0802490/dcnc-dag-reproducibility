# DCNC-DAG installation and runtime setup

This project uses two conda environments:

- `dcnc_dag`: the main Python 3 environment for the simulator.
- `dynvmp-py2`: the Python 2.7 environment required by the exact DynVMP solver.

## 1. Directory layout

The release ZIP is self-contained apart from the two Conda environments and a
separately licensed Gurobi installation. Its relevant layout is:

```text
~/dcnc_dag_py3/
├── third_party/alib/
├── third_party/vnep_approx/
└── tools/run_dynvmp_bridge.sh
```

The wrapper automatically prefers these vendored, MIT-licensed snapshots. A
legacy sibling workspace at `../workspace/dcnc_dynvmp` remains an optional
fallback but is not required for the release artifact.

## 2. Create the conda environments

From the project root:

```bash
cd ~/dcnc_dag_py3
conda env create -n dcnc_dag -f environment_dcnc_dag.yml
conda env create -n dynvmp-py2 -f environment_dynvmp_py2.yml
```

## 3. Install the main Python 3 package

```bash
conda activate dcnc_dag
cd ~/dcnc_dag_py3
python -m pip install -e .
```

For a pip-only verification environment (including CI), constrain resolution
to the exact pip package set captured inside `environment_dcnc_dag.yml`:

```bash
python -m pip install pip==26.0.1 setuptools==82.0.1 wheel==0.46.3
python -m pip install --no-build-isolation \
  --constraint constraints-main.txt --editable .
```

`scripts/maintain_artifact.py verify` rejects any drift between that constraint
file and the Conda environment's pip block.

## 4. About the exact DynVMP path

The updated bridge now defaults to an internal **heuristic tree-decomposition builder** for the request graph. This means:

- exact DynVMP runs still use the DynVMP dynamic program itself,
- but they no longer require Java/PACE in the default configuration,
- which makes deployment on a new server much simpler and avoids the earlier `StopIteration` failure caused by an empty tree decomposition.

The bridge wrapper still needs the Python 2 environment and Gurobi 9.1.2, but
the required `alib` and `vnep_approx` source snapshots are included under
`third_party/`. The wrapper exports `PYTHONPATH` to these directories
automatically, so a separate editable install inside `dynvmp-py2` is optional.

## 5. New terminal startup

Every time you open a new terminal:

```bash
cd ~/dcnc_dag_py3
source ./setup_runtime_env.sh
```

This script automatically:

- activates `dcnc_dag` when conda is available,
- exports `PYTHONPATH` for `src/`,
- sets `DCNC_DYNVMP_CMD` to `tools/run_dynvmp_bridge.sh`,
- points the wrapper to the vendored `third_party` snapshots, with the legacy
  external workspace retained only as a fallback,
- sets `DCNC_TD_MODE=heuristic` by default.

## 6. Verify the installation

Run:

```bash
./verify_runtime.sh
```

Then check the exact bridge entry point:

```bash
$DCNC_DYNVMP_CMD --help
```

## 7. Optional: switch the tree decomposition mode

Default mode:

```bash
export DCNC_TD_MODE=heuristic
```

Other modes:

- `heuristic`: always use the built-in min-fill heuristic decomposition.
- `auto`: try PACE first, fall back to the heuristic decomposition if PACE fails.
- `pace`: require PACE; fail if PACE fails.
- `pace-strict`: same idea, but no fallback.

For the paper experiments, keep the default:

```bash
export DCNC_TD_MODE=heuristic
```

This removes the Java/PACE dependency from the normal experiment path.
